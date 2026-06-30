"""Chat session/message persistence (M1c).

Lazily creates ``chat_sessions`` and ``chat_messages`` on first use (memoized
per Database instance, mirroring RelayService.ensure_schema) so no migration
bump is needed. Plain append-only rows — no sqlite-vec involved.
"""

from __future__ import annotations

import json
import uuid
import weakref
from datetime import datetime, timezone
from typing import Any, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


class ChatStore:
    """SQLite-backed store for dashboard chat threads."""

    _schema_ready: "weakref.WeakSet" = weakref.WeakSet()

    def __init__(self, db: Any):
        self.db = db

    async def ensure_schema(self) -> None:
        if self.db in ChatStore._schema_ready:
            return
        statements = [
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                title TEXT,
                provider TEXT,
                model TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                tool_calls TEXT,
                tool_results TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session
            ON chat_messages(session_id, seq)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_project
            ON chat_sessions(project_id, updated_at)
            """,
        ]
        async with self.db.transaction():
            for statement in statements:
                await self.db.execute(statement)
        ChatStore._schema_ready.add(self.db)

    async def create_session(
        self,
        *,
        project_id: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        title: Optional[str] = None,
    ) -> str:
        await self.ensure_schema()
        session_id = _new_id()
        now = _utc_now()
        await self.db.execute(
            """
            INSERT INTO chat_sessions
                (id, project_id, title, provider, model, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, project_id, title, provider, model, now, now),
        )
        return session_id

    async def get_session(self, session_id: str) -> Optional[dict]:
        await self.ensure_schema()
        row = await self.db.fetchone(
            "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
        )
        return dict(row) if row else None

    async def list_sessions(
        self, *, project_id: Optional[str] = None, limit: int = 20
    ) -> List[dict]:
        await self.ensure_schema()
        if project_id is not None:
            rows = await self.db.fetchall(
                """
                SELECT * FROM chat_sessions WHERE project_id = ?
                ORDER BY updated_at DESC LIMIT ?
                """,
                (project_id, limit),
            )
        else:
            rows = await self.db.fetchall(
                "SELECT * FROM chat_sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in rows]

    async def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: Optional[str] = None,
        tool_calls: Optional[Any] = None,
        tool_results: Optional[Any] = None,
    ) -> str:
        await self.ensure_schema()
        message_id = _new_id()
        now = _utc_now()
        seq_row = await self.db.fetchone(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM chat_messages WHERE session_id = ?",
            (session_id,),
        )
        seq = seq_row["n"] if seq_row else 1
        await self.db.execute(
            """
            INSERT INTO chat_messages
                (id, session_id, seq, role, content, tool_calls, tool_results, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                session_id,
                seq,
                role,
                content,
                json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                json.dumps(tool_results, ensure_ascii=False) if tool_results else None,
                now,
            ),
        )
        await self.db.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (now, session_id)
        )
        return message_id

    async def get_messages(self, session_id: str) -> List[dict]:
        await self.ensure_schema()
        rows = await self.db.fetchall(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY seq ASC",
            (session_id,),
        )
        out: List[dict] = []
        for r in rows:
            d = dict(r)
            if d.get("tool_calls"):
                d["tool_calls"] = json.loads(d["tool_calls"])
            if d.get("tool_results"):
                d["tool_results"] = json.loads(d["tool_results"])
            out.append(d)
        return out
