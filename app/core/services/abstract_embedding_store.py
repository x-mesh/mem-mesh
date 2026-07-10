"""Abstract-embedding persistence (E scaffolding).

Stores an embedding computed from a memory's enrichment *abstract*, kept
SEPARATE from the memory's content embedding (the sqlite-vec table) so the two
can be A/B compared — and rolled back — without touching the live search path.
Plain float32 BLOB store (no sqlite-vec KNN yet); the A/B search integration is
a later step. Lazy schema (memoized per Database instance), like EnrichmentStore.
"""

from __future__ import annotations

import struct
import weakref
from datetime import datetime, timezone
from typing import Any, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pack(embedding: List[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)


def _unpack(blob: bytes) -> List[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


class AbstractEmbeddingStore:
    _schema_ready: "weakref.WeakSet" = weakref.WeakSet()

    def __init__(self, db: Any):
        self.db = db

    async def ensure_schema(self) -> None:
        if self.db in AbstractEmbeddingStore._schema_ready:
            return
        async with self.db.transaction():
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS memory_abstract_embedding (
                    memory_id TEXT PRIMARY KEY,
                    embedding BLOB NOT NULL,
                    model TEXT,
                    dim INTEGER,
                    created_at TEXT NOT NULL
                )
                """)
        AbstractEmbeddingStore._schema_ready.add(self.db)

    async def upsert(
        self,
        *,
        memory_id: str,
        embedding: List[float],
        model: str = "",
        dim: Optional[int] = None,
    ) -> None:
        await self.ensure_schema()
        await self.db.execute(
            """
            INSERT INTO memory_abstract_embedding
                (memory_id, embedding, model, dim, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                embedding = excluded.embedding,
                model = excluded.model,
                dim = excluded.dim,
                created_at = excluded.created_at
            """,
            (memory_id, _pack(embedding), model, dim or len(embedding), _utc_now()),
        )

    async def get(self, memory_id: str) -> Optional[dict]:
        await self.ensure_schema()
        row = await self.db.fetchone(
            "SELECT * FROM memory_abstract_embedding WHERE memory_id = ?",
            (memory_id,),
        )
        if not row:
            return None
        data = dict(row)
        data["embedding"] = _unpack(data["embedding"])
        return data

    async def count(self) -> int:
        await self.ensure_schema()
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS n FROM memory_abstract_embedding"
        )
        return int(row["n"]) if row else 0
