"""Memory enrichment persistence (M2-E).

Stores AI-generated metadata (title / abstract / tags) for a memory in a
``memory_enrichment`` side table, keyed by memory_id. Lazy schema (memoized per
Database instance, like ChatStore) so no migration bump is needed. The memory's
own content is never changed by enrichment — only this metadata layer and an
optional tag merge.
"""

from __future__ import annotations

import json
import weakref
from datetime import datetime, timezone
from typing import Any, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EnrichmentStore:
    _schema_ready: "weakref.WeakSet" = weakref.WeakSet()

    def __init__(self, db: Any):
        self.db = db

    async def ensure_schema(self) -> None:
        if self.db in EnrichmentStore._schema_ready:
            return
        async with self.db.transaction():
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS memory_enrichment (
                    memory_id TEXT PRIMARY KEY,
                    title TEXT,
                    abstract TEXT,
                    tags TEXT,
                    display_kind TEXT,
                    model TEXT,
                    created_at TEXT NOT NULL
                )
                """)
        EnrichmentStore._schema_ready.add(self.db)

    async def upsert(
        self,
        *,
        memory_id: str,
        title: str = "",
        abstract: str = "",
        tags: Optional[List[str]] = None,
        display_kind: str = "",
        model: str = "",
    ) -> dict:
        await self.ensure_schema()
        now = _utc_now()
        async with self.db.transaction():
            await self.db.execute(
                "DELETE FROM memory_enrichment WHERE memory_id = ?", (memory_id,)
            )
            await self.db.execute(
                """
                INSERT INTO memory_enrichment
                    (memory_id, title, abstract, tags, display_kind, model, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    title,
                    abstract,
                    json.dumps(tags or [], ensure_ascii=False),
                    display_kind,
                    model,
                    now,
                ),
            )
        return await self.get(memory_id)

    async def get(self, memory_id: str) -> Optional[dict]:
        await self.ensure_schema()
        row = await self.db.fetchone(
            "SELECT * FROM memory_enrichment WHERE memory_id = ?", (memory_id,)
        )
        if not row:
            return None
        data = dict(row)
        try:
            data["tags"] = json.loads(data["tags"]) if data.get("tags") else []
        except (json.JSONDecodeError, ValueError, TypeError):
            data["tags"] = []
        return data
