"""Chat persistence tests (M1c)."""

import os
import tempfile
from contextlib import asynccontextmanager

import pytest

from app.core.database.base import Database
from app.core.services.chat_store import ChatStore


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


@pytest.mark.asyncio
async def test_create_session_and_get():
    async with _temp_db() as db:
        store = ChatStore(db)
        sid = await store.create_session(
            project_id="p1", provider="anthropic", model="claude-sonnet-4-6"
        )
        assert sid
        session = await store.get_session(sid)
        assert session["project_id"] == "p1"
        assert session["provider"] == "anthropic"
        assert session["created_at"]


@pytest.mark.asyncio
async def test_add_messages_are_ordered_by_seq():
    async with _temp_db() as db:
        store = ChatStore(db)
        sid = await store.create_session(project_id="p1")
        await store.add_message(session_id=sid, role="user", content="hi")
        await store.add_message(
            session_id=sid,
            role="assistant",
            content="checking",
            tool_calls=[{"id": "t1", "name": "search_memories", "arguments": {}}],
        )
        await store.add_message(
            session_id=sid,
            role="tool",
            tool_results=[{"tool_call_id": "t1", "content": "{}"}],
        )
        await store.add_message(session_id=sid, role="assistant", content="done")

        msgs = await store.get_messages(sid)
        assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "assistant"]
        assert [m["seq"] for m in msgs] == [1, 2, 3, 4]
        # JSON columns round-trip back to objects
        assert msgs[1]["tool_calls"][0]["name"] == "search_memories"
        assert msgs[2]["tool_results"][0]["tool_call_id"] == "t1"


@pytest.mark.asyncio
async def test_list_sessions_filters_and_orders_by_recency():
    async with _temp_db() as db:
        store = ChatStore(db)
        a = await store.create_session(project_id="p1")
        b = await store.create_session(project_id="p2")
        # touch a after b by adding a message (updates updated_at)
        await store.add_message(session_id=a, role="user", content="later")

        all_p1 = await store.list_sessions(project_id="p1")
        assert [s["id"] for s in all_p1] == [a]
        every = await store.list_sessions()
        assert {s["id"] for s in every} == {a, b}
        # a was touched most recently -> first
        assert every[0]["id"] == a


@pytest.mark.asyncio
async def test_add_message_updates_session_timestamp():
    async with _temp_db() as db:
        store = ChatStore(db)
        sid = await store.create_session(project_id="p1")
        before = (await store.get_session(sid))["updated_at"]
        await store.add_message(session_id=sid, role="user", content="x")
        after = (await store.get_session(sid))["updated_at"]
        assert after >= before
