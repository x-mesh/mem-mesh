"""Chat SSE streaming route test (M1c)."""

import json
import os
import tempfile
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database.base import Database
from app.core.services.chat_store import ChatStore
from app.web.common.dependencies import get_database
from app.web.dashboard.route_modules import chat as chat_route


@pytest.fixture(autouse=True)
def _reset_sse_appstatus():
    # sse_starlette caches a module-global asyncio.Event bound to the first
    # event loop it sees; pytest-asyncio gives each test a fresh loop, so reset
    # it or the 2nd SSE test fails with "bound to a different event loop".
    from sse_starlette.sse import AppStatus

    AppStatus.should_exit_event = None
    yield
    AppStatus.should_exit_event = None


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


class _FakeService:
    async def is_configured(self, settings):
        return True

    async def get_effective_config(self, settings):
        return {
            "values": {
                "llm_provider": "anthropic",
                "llm_model": "claude-sonnet-4-6",
                "llm_api_key": "k",
                "llm_base_url": "",
            }
        }

    async def agent_events(self, messages, settings, handlers, *, max_steps=5):
        yield {
            "type": "tool_call",
            "name": "search_memories",
            "arguments": {"query": "x"},
        }
        yield {"type": "tool_result", "name": "search_memories", "ok": True}
        yield {"type": "message", "text": "final answer"}
        yield {
            "type": "done",
            "steps": 2,
            "truncated": False,
            "finish_reason": "end_turn",
            "tool_calls": [
                {
                    "name": "search_memories",
                    "arguments": {"query": "x"},
                    "result": {"ok": True},
                }
            ],
        }


def _app(db, monkeypatch):
    app = FastAPI()
    app.include_router(chat_route.router, prefix="/api")
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[chat_route.get_chat_service] = lambda: _FakeService()
    monkeypatch.setattr(chat_route.mcp_sse, "get_tool_handlers", lambda: object())
    return app


async def _collect_sse(resp):
    events = []
    current = None
    async for line in resp.aiter_lines():
        if line.startswith("event:"):
            current = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            payload = line.split(":", 1)[1].strip()
            try:
                events.append((current, json.loads(payload)))
            except json.JSONDecodeError:
                pass
    return events


@pytest.mark.asyncio
async def test_chat_stream_emits_events_and_persists(monkeypatch):
    async with _temp_db() as db:
        app = _app(db, monkeypatch)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            async with client.stream(
                "POST",
                "/api/chat/v1/stream",
                json={
                    "messages": [{"role": "user", "content": "what's up"}],
                    "project_id": "p1",
                },
            ) as resp:
                assert resp.status_code == 200
                events = await _collect_sse(resp)

        types = [e[0] for e in events]
        assert "session" in types
        assert "tool_call" in types
        assert "tool_result" in types
        assert "message" in types
        assert "done" in types

        session_evt = next(e for e in events if e[0] == "session")
        session_id = session_evt[1]["session_id"]

        store = ChatStore(db)
        session = await store.get_session(session_id)
        assert session["project_id"] == "p1"
        assert session["provider"] == "anthropic"

        msgs = await store.get_messages(session_id)
        roles = [m["role"] for m in msgs]
        assert roles == ["user", "assistant"]
        assert msgs[0]["content"] == "what's up"
        assert msgs[1]["content"] == "final answer"
        assert msgs[1]["tool_calls"][0]["name"] == "search_memories"


@pytest.mark.asyncio
async def test_chat_stream_resumes_session_history(monkeypatch):
    async with _temp_db() as db:
        # seed a prior session with history
        store = ChatStore(db)
        sid = await store.create_session(project_id="p1", provider="anthropic")
        await store.add_message(session_id=sid, role="user", content="earlier q")
        await store.add_message(session_id=sid, role="assistant", content="earlier a")

        captured = {}

        class _CapturingService(_FakeService):
            async def agent_events(self, messages, settings, handlers, *, max_steps=5):
                captured["messages"] = messages
                yield {"type": "message", "text": "second answer"}
                yield {
                    "type": "done",
                    "steps": 1,
                    "truncated": False,
                    "finish_reason": "end_turn",
                    "tool_calls": [],
                }

        app = FastAPI()
        app.include_router(chat_route.router, prefix="/api")
        app.dependency_overrides[get_database] = lambda: db
        app.dependency_overrides[chat_route.get_chat_service] = (
            lambda: _CapturingService()
        )
        monkeypatch.setattr(chat_route.mcp_sse, "get_tool_handlers", lambda: object())

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            async with client.stream(
                "POST",
                "/api/chat/v1/stream",
                json={
                    "messages": [{"role": "user", "content": "follow up"}],
                    "session_id": sid,
                },
            ) as resp:
                assert resp.status_code == 200
                await _collect_sse(resp)

        # the agent saw system + prior history + the new user turn
        roles_contents = [(m["role"], m.get("content")) for m in captured["messages"]]
        assert ("user", "earlier q") in roles_contents
        assert ("assistant", "earlier a") in roles_contents
        assert ("user", "follow up") in roles_contents
        # appended to the same session
        msgs = await store.get_messages(sid)
        assert [m["content"] for m in msgs[-2:]] == ["follow up", "second answer"]
