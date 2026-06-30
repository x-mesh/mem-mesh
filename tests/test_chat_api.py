"""Chat HTTP API tests (settings round-trip) with overridden temporary DB."""

import os
import tempfile
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database.base import Database
from app.web.common.dependencies import get_database
from app.web.dashboard.route_modules.chat import router as chat_router


@asynccontextmanager
async def _temp_db():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path)
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
        for ext in ["", "-wal", "-shm"]:
            path = db_path + ext
            if os.path.exists(path):
                os.unlink(path)


def _app(db: Database) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router, prefix="/api")
    app.dependency_overrides[get_database] = lambda: db
    return app


@pytest.mark.asyncio
async def test_chat_settings_round_trip_masks_key_and_records_source():
    async with _temp_db() as db:
        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            # initial: nothing in DB
            r = await client.get("/api/chat/v1/settings")
            assert r.status_code == 200
            body = r.json()
            assert body["llm_api_key"]["secret"] is True
            assert body["llm_api_key"]["value"] is None

            # persist
            r = await client.put(
                "/api/chat/v1/settings",
                json={
                    "llm_provider": "OpenAI",
                    "llm_api_key": "sk-secret",
                    "llm_model": "gpt-4o",
                    "llm_base_url": "https://api.groq.com/openai/v1",
                },
            )
            assert r.status_code == 200
            body = r.json()
            # provider normalized + sourced from DB
            assert body["llm_provider"]["value"] == "openai"
            assert body["llm_provider"]["source"] == "db"
            assert body["llm_model"]["value"] == "gpt-4o"
            # key configured but never echoed back
            assert body["llm_api_key"]["configured"] is True
            assert body["llm_api_key"]["value"] is None

            # persisted to app_config under chat.llm_*
            assert await db.get_app_config("chat.llm_provider") == "openai"
            assert await db.get_app_config("chat.llm_api_key") == "sk-secret"


@pytest.mark.asyncio
async def test_chat_settings_rejects_bad_provider():
    async with _temp_db() as db:
        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.put(
                "/api/chat/v1/settings", json={"llm_provider": "gemini"}
            )
            assert r.status_code == 422


@pytest.mark.asyncio
async def test_chat_test_rejects_bad_provider_override():
    async with _temp_db() as db:
        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/api/chat/v1/test", json={"provider": "gemini"})
            assert r.status_code == 422


@pytest.mark.asyncio
async def test_chat_settings_clear_key_deletes_db_row():
    async with _temp_db() as db:
        await db.set_app_config("chat.llm_api_key", "sk-old")
        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.put("/api/chat/v1/settings", json={"llm_api_key": "   "})
            assert r.status_code == 200
            assert await db.get_app_config("chat.llm_api_key") is None


def test_build_agent_system_prompt_describes_page():
    from app.core.schemas.chat import ChatPageContext
    from app.web.dashboard.route_modules.chat import _build_agent_system_prompt

    # no page -> base prompt only, no page-specific clauses
    base = _build_agent_system_prompt(None)
    assert "mem-mesh assistant" in base
    assert "Current project_id is" not in base
    assert "get_memory_context" not in base
    assert "page." not in base

    # project page -> project_id wired in
    p = _build_agent_system_prompt(
        ChatPageContext(
            route="/project/acme", label="project detail", project_id="acme"
        )
    )
    assert "project detail" in p
    assert "'acme'" in p
    assert "list_pins" in p

    # memory page -> instructs get_memory_context
    m = _build_agent_system_prompt(
        ChatPageContext(route="/memory/abc", label="memory detail", memory_id="abc")
    )
    assert "get_memory_context" in m
    assert "'abc'" in m

    # plain page -> route label mentioned, no project/memory clauses
    s = _build_agent_system_prompt(ChatPageContext(route="/settings", label="settings"))
    assert "settings page" in s
    assert "project_id is" not in s
    assert "get_memory_context" not in s


@pytest.mark.asyncio
async def test_chat_status_and_enable_toggle():
    async with _temp_db() as db:
        app = _app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            # nothing configured -> unavailable
            s = (await client.get("/api/chat/v1/status")).json()
            assert s["configured"] is False
            assert s["available"] is False

            # configure a key -> available (enabled defaults true)
            await client.put(
                "/api/chat/v1/settings",
                json={"llm_provider": "anthropic", "llm_api_key": "sk"},
            )
            s = (await client.get("/api/chat/v1/status")).json()
            assert s["configured"] is True
            assert s["enabled"] is True
            assert s["available"] is True
            assert s["provider"] == "anthropic"

            # disable via toggle -> unavailable but still configured
            r = await client.put("/api/chat/v1/settings", json={"enabled": False})
            assert r.json()["enabled"] is False
            assert r.json()["available"] is False
            s = (await client.get("/api/chat/v1/status")).json()
            assert s["configured"] is True
            assert s["enabled"] is False
            assert s["available"] is False
            assert await db.get_app_config("chat.enabled") == "false"


class _FakeMem:
    content = "old content that is plenty long enough"
    category = "task"
    tags = '["x"]'


class _FakeMemoryService:
    def __init__(self):
        self.updated = None

    async def get(self, mid):
        return _FakeMem() if mid == "m1" else None

    async def update(self, mid, content=None, category=None, tags=None):
        self.updated = {
            "id": mid,
            "content": content,
            "category": category,
            "tags": tags,
        }


class _FakeRefineChatService:
    async def is_configured(self, s):
        return True

    async def is_enabled(self, s):
        return True

    async def refine_memory_content(self, *, content, category, tags, settings):
        return {
            "content": "## WHY\nbetter version of the memory",
            "category": "decision",
            "tags": ["a", "b"],
            "summary": "s",
            "rationale": "r",
        }


@pytest.mark.asyncio
async def test_chat_refine_and_apply():
    from app.web.common.dependencies import get_memory_service
    from app.web.dashboard.route_modules import chat as chat_route

    async with _temp_db() as db:
        memsvc = _FakeMemoryService()
        app = FastAPI()
        app.include_router(chat_route.router, prefix="/api")
        app.dependency_overrides[get_database] = lambda: db
        app.dependency_overrides[chat_route.get_chat_service] = (
            lambda: _FakeRefineChatService()
        )
        app.dependency_overrides[get_memory_service] = lambda: memsvc
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/api/chat/v1/refine", json={"memory_id": "m1"})
            assert r.status_code == 200
            body = r.json()
            assert body["original"]["content"].startswith("old content")
            assert body["original"]["tags"] == ["x"]
            assert body["proposed"]["category"] == "decision"
            assert "WHY" in body["proposed"]["content"]
            assert body["proposed"]["tags"] == ["a", "b"]

            # unknown memory -> 404
            r404 = await client.post("/api/chat/v1/refine", json={"memory_id": "nope"})
            assert r404.status_code == 404

            # apply the approved version
            ra = await client.post(
                "/api/chat/v1/refine/apply",
                json={
                    "memory_id": "m1",
                    "content": "final approved content goes here",
                    "category": "decision",
                    "tags": ["a"],
                },
            )
            assert ra.status_code == 200
            assert memsvc.updated["content"] == "final approved content goes here"
            assert memsvc.updated["category"] == "decision"
            assert memsvc.updated["tags"] == ["a"]


class _FakeSaveMemoryService:
    def __init__(self):
        self.created = None

    async def create(
        self,
        content=None,
        project_id=None,
        category=None,
        source=None,
        client=None,
        tags=None,
    ):
        self.created = {
            "content": content,
            "project_id": project_id,
            "category": category,
            "source": source,
            "client": client,
            "tags": tags,
        }

        class _R:
            id = "new-mem-id"
            status = "saved"

        return _R()


class _FakeSaveChatService:
    async def is_configured(self, s):
        return True

    async def is_enabled(self, s):
        return True

    async def summarize_for_memory(self, *, text, settings):
        return {
            "content": "## WHY\nlasting decision content",
            "category": "decision",
            "tags": ["a", "b"],
            "summary": "s",
        }


@pytest.mark.asyncio
async def test_chat_summarize_and_save_memory():
    from app.web.common.dependencies import get_memory_service
    from app.web.dashboard.route_modules import chat as chat_route

    async with _temp_db() as db:
        memsvc = _FakeSaveMemoryService()
        app = FastAPI()
        app.include_router(chat_route.router, prefix="/api")
        app.dependency_overrides[get_database] = lambda: db
        app.dependency_overrides[chat_route.get_chat_service] = (
            lambda: _FakeSaveChatService()
        )
        app.dependency_overrides[get_memory_service] = lambda: memsvc
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post(
                "/api/chat/v1/summarize", json={"text": "we decided X because Y"}
            )
            assert r.status_code == 200
            assert r.json()["proposed"]["category"] == "decision"
            assert r.json()["proposed"]["tags"] == ["a", "b"]

            # save with an invalid category -> normalized to 'idea'
            rs = await client.post(
                "/api/chat/v1/save-memory",
                json={
                    "content": "## WHY durable content goes here",
                    "category": "bogus",
                    "tags": ["a"],
                    "project_id": "p1",
                },
            )
            assert rs.status_code == 200
            assert rs.json()["id"] == "new-mem-id"
            assert rs.json()["category"] == "idea"
            assert memsvc.created["category"] == "idea"
            assert memsvc.created["source"] == "chat-assistant"
            assert memsvc.created["project_id"] == "p1"
