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

    async def summarize_for_memory(self, *, text, settings, language=None):
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


class _FakeEnrichChatService:
    async def is_configured(self, s):
        return True

    async def is_enabled(self, s):
        return True

    async def enrich_memory_content(self, *, content, settings):
        return {
            "title": "Better title",
            "abstract": "An abstract",
            "tags": ["new1", "new2"],
            "display_kind": "note",
            "model": "m",
        }


@pytest.mark.asyncio
async def test_chat_enrich_stores_and_merges_tags():
    from app.web.common.dependencies import get_memory_service
    from app.web.dashboard.route_modules import chat as chat_route

    async with _temp_db() as db:
        memsvc = _FakeMemoryService()  # get('m1') -> _FakeMem(tags '["x"]')
        app = FastAPI()
        app.include_router(chat_route.router, prefix="/api")
        app.dependency_overrides[get_database] = lambda: db
        app.dependency_overrides[chat_route.get_chat_service] = (
            lambda: _FakeEnrichChatService()
        )
        app.dependency_overrides[get_memory_service] = lambda: memsvc
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/api/chat/v1/enrich", json={"memory_id": "m1"})
            assert r.status_code == 200
            body = r.json()
            assert body["title"] == "Better title"
            assert body["tags"] == ["new1", "new2"]
            assert set(body["merged_tags"]) == {"x", "new1", "new2"}
            assert set(memsvc.updated["tags"]) == {"x", "new1", "new2"}

            # stored -> GET returns it
            g = await client.get("/api/chat/v1/enrich/m1")
            assert g.status_code == 200
            assert g.json()["title"] == "Better title"

            # unknown -> 404
            assert (await client.get("/api/chat/v1/enrich/nope")).status_code == 404

            # unknown memory on POST -> 404
            r404 = await client.post("/api/chat/v1/enrich", json={"memory_id": "nope"})
            assert r404.status_code == 404


class _DedupMem:
    def __init__(self, mid, content, category="task", tags='["x"]'):
        self.id = mid
        self.content = content
        self.category = category
        self.tags = tags


class _DedupMemoryService:
    def __init__(self, mems):
        self.mems = dict(mems)
        self.updated = None
        self.deleted = []

    async def get(self, mid):
        return self.mems.get(mid)

    async def update(self, mid, content=None, category=None, tags=None):
        self.updated = {
            "id": mid,
            "content": content,
            "category": category,
            "tags": tags,
        }

    async def delete(self, mid):
        self.deleted.append(mid)
        self.mems.pop(mid, None)


class _DedupHandlers:
    def __init__(self):
        self.links = []

    async def link(self, source_id, target_id, relation_type="related"):
        self.links.append((source_id, target_id, relation_type))
        return {"ok": True}


class _SR:
    def __init__(self, id, content, category=None, similarity_score=None):
        self.id = id
        self.content = content
        self.category = category
        self.similarity_score = similarity_score


class _DedupSearchService:
    def __init__(self, results):
        class _Resp:
            pass

        self._resp = _Resp()
        self._resp.results = results

    async def search(self, **kwargs):
        return self._resp


class _DedupChatService:
    async def is_configured(self, s):
        return True

    async def is_enabled(self, s):
        return True

    async def merge_memories_content(self, *, memories, settings):
        return {
            "content": "## merged\nconsolidated content",
            "category": "decision",
            "tags": ["a", "b"],
            "summary": "s",
        }


@pytest.mark.asyncio
async def test_chat_dedup_scan_excludes_self():
    from app.web.common.dependencies import get_memory_service, get_search_service
    from app.web.dashboard.route_modules import chat as chat_route

    src = "The quick brown fox jumps over the lazy dog every single morning."
    async with _temp_db() as db:
        memsvc = _DedupMemoryService({"m1": _DedupMem("m1", src)})
        search_svc = _DedupSearchService(
            [
                _SR("m1", src, similarity_score=1.0),  # self -> excluded
                _SR(
                    "m2", src + " ", category="task", similarity_score=0.99
                ),  # near-dup
                _SR(
                    "m3",
                    "Completely unrelated note about database indexing and caching.",
                    similarity_score=0.98,  # high cosine but different text -> filtered
                ),
            ]
        )
        app = FastAPI()
        app.include_router(chat_route.router, prefix="/api")
        app.dependency_overrides[get_database] = lambda: db
        app.dependency_overrides[get_memory_service] = lambda: memsvc
        app.dependency_overrides[get_search_service] = lambda: search_svc
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post(
                "/api/chat/v1/dedup/scan", json={"memory_id": "m1", "limit": 5}
            )
            assert r.status_code == 200
            cands = r.json()["candidates"]
            # only the near-exact duplicate survives the text-overlap filter
            assert [c["id"] for c in cands] == ["m2"]
            assert cands[0]["score"] >= 0.9


@pytest.mark.asyncio
async def test_chat_dedup_merge_preview_and_apply(monkeypatch):
    from app.web.common.dependencies import get_memory_service
    from app.web.dashboard.route_modules import chat as chat_route

    async with _temp_db() as db:
        memsvc = _DedupMemoryService(
            {
                "m1": _DedupMem("m1", "primary content"),
                "m2": _DedupMem("m2", "dup two"),
                "m3": _DedupMem("m3", "dup three"),
            }
        )
        handlers = _DedupHandlers()
        app = FastAPI()
        app.include_router(chat_route.router, prefix="/api")
        app.dependency_overrides[get_database] = lambda: db
        app.dependency_overrides[chat_route.get_chat_service] = (
            lambda: _DedupChatService()
        )
        app.dependency_overrides[get_memory_service] = lambda: memsvc
        monkeypatch.setattr(chat_route.mcp_sse, "get_tool_handlers", lambda: handlers)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            # preview
            pv = await client.post(
                "/api/chat/v1/dedup/merge-preview",
                json={"memory_ids": ["m1", "m2", "m3"]},
            )
            assert pv.status_code == 200
            assert pv.json()["proposed"]["category"] == "decision"
            assert "merged" in pv.json()["proposed"]["content"]

            # primary cannot be a duplicate
            bad = await client.post(
                "/api/chat/v1/dedup/merge-apply",
                json={
                    "primary_id": "m1",
                    "duplicate_ids": ["m1"],
                    "content": "merged content here",
                },
            )
            assert bad.status_code == 400

            # apply
            ap = await client.post(
                "/api/chat/v1/dedup/merge-apply",
                json={
                    "primary_id": "m1",
                    "duplicate_ids": ["m2", "m3"],
                    "content": "merged consolidated content",
                    "category": "decision",
                    "tags": ["a"],
                },
            )
            assert ap.status_code == 200
            body = ap.json()
            assert set(body["deleted"]) == {"m2", "m3"}
            assert set(body["superseded"]) == {"m2", "m3"}
            assert memsvc.updated["id"] == "m1"
            assert memsvc.updated["content"] == "merged consolidated content"
            assert set(memsvc.deleted) == {"m2", "m3"}
            assert ("m1", "m2", "supersedes") in handlers.links
