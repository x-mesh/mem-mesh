"""Project overview (LLM narrative) generation + cache.

Produces a grounded summary of a project from its recent memories — one LLM
call over the batch (not a per-item loop), so it's fine to run on-demand /
synchronously. The result is cached in ``project_overview`` keyed by project,
with a ``source_hash`` of the input memories so the UI can tell when the cached
overview is stale (memories added/edited since it was generated).

Input items reuse the local enrichment layer (EnrichmentStore / memory_enrichment
title+abstract) when present — dense and cheap — falling back to a content
snippet. Category is passed through so the model can surface bug/incident/task
items as ``open_issues``.

Schema is lazy/memoized per Database instance (like EnrichmentStore) so no
migration bump is needed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import weakref
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.services.enrich_store import EnrichmentStore

logger = logging.getLogger(__name__)

_RECENT_LIMIT = 20
_SNIPPET_CHARS = 300


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_line(content: str) -> str:
    for ln in (content or "").splitlines():
        s = ln.strip(" #").strip()
        if s:
            return s
    return ""


class OverviewService:
    _schema_ready: "weakref.WeakSet" = weakref.WeakSet()

    def __init__(self, db: Any):
        self.db = db

    async def ensure_schema(self) -> None:
        if self.db in OverviewService._schema_ready:
            return
        # memory_enrichment is lazy-created by EnrichmentStore; _gather_items
        # LEFT JOINs it, so guarantee it exists here (else 'no such table' 500
        # on a DB that never ran enrichment — see curation.py's same-join guard).
        await EnrichmentStore(self.db).ensure_schema()
        async with self.db.transaction():
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS project_overview (
                    project_id TEXT PRIMARY KEY,
                    overview_json TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    model TEXT,
                    created_at TEXT NOT NULL
                )
                """)
        OverviewService._schema_ready.add(self.db)

    async def _gather_items(self, project_id: str) -> tuple[list, str]:
        """Recent memories of a project as overview input + a source hash.

        The hash covers every field fed to the LLM — id + content_hash plus
        category and the enrichment title/abstract — so the cached overview
        goes stale on any change that alters the input, including metadata-only
        edits (category) and enrichment updates that leave content_hash intact.
        """
        rows = await self.db.fetchall(
            """
            SELECT m.id AS id, m.category AS category, m.content AS content,
                   m.content_hash AS content_hash, m.created_at AS created_at,
                   e.title AS e_title, e.abstract AS e_abstract
            FROM memories m
            LEFT JOIN memory_enrichment e ON e.memory_id = m.id
            WHERE m.project_id = ?
              AND COALESCE(m.status, 'canonical') = 'canonical'
            ORDER BY m.updated_at DESC, m.created_at DESC
            LIMIT ?
            """,
            (project_id, _RECENT_LIMIT),
        )
        items: list = []
        hash_parts: list = []
        for r in rows:
            content = str(r["content"] or "")
            title = (r["e_title"] or "").strip() or _first_line(content)[:80]
            abstract = (r["e_abstract"] or "").strip() or content[:_SNIPPET_CHARS]
            items.append(
                {
                    "id": str(r["id"]),
                    "category": str(r["category"] or ""),
                    "title": title,
                    "abstract": abstract,
                    "created_at": str(r["created_at"] or ""),
                }
            )
            hash_parts.append(
                f"{r['id']}:{r['content_hash']}:{r['category'] or ''}"
                f":{r['e_title'] or ''}:{r['e_abstract'] or ''}"
            )
        source_hash = hashlib.sha256("|".join(hash_parts).encode("utf-8")).hexdigest()
        return items, source_hash

    async def get_cached(self, project_id: str) -> Optional[dict]:
        """Return the stored overview + a ``stale`` flag, or None if never
        generated. ``stale`` is True when the project's memories changed since
        the overview was made."""
        await self.ensure_schema()
        row = await self.db.fetchone(
            "SELECT overview_json, source_hash, item_count, model, created_at "
            "FROM project_overview WHERE project_id = ?",
            (project_id,),
        )
        if not row:
            return None
        try:
            overview = json.loads(row["overview_json"])
        except (json.JSONDecodeError, TypeError):
            return None
        _items, current_hash = await self._gather_items(project_id)
        return {
            "overview": overview,
            "stale": current_hash != row["source_hash"],
            "item_count": row["item_count"],
            "model": row["model"],
            "generated_at": row["created_at"],
        }

    async def generate(
        self, *, project_id: str, chat_service: Any, settings: Any
    ) -> dict:
        """Gather recent memories, ask the chat LLM for an overview, cache it."""
        await self.ensure_schema()
        items, source_hash = await self._gather_items(project_id)
        if not items:
            return {"overview": None, "stale": False, "item_count": 0, "empty": True}

        data = await chat_service.generate_project_overview(
            project_id=project_id, items=items, settings=settings
        )
        model = str(data.pop("model", "") or "")
        overview_json = json.dumps(data, ensure_ascii=False)
        now = _utc_now()
        # PRIMARY KEY(project_id) → DELETE + INSERT (no INSERT OR REPLACE churn).
        async with self.db.transaction():
            await self.db.execute(
                "DELETE FROM project_overview WHERE project_id = ?", (project_id,)
            )
            await self.db.execute(
                "INSERT INTO project_overview "
                "(project_id, overview_json, source_hash, item_count, model, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, overview_json, source_hash, len(items), model, now),
            )
        return {
            "overview": data,
            "stale": False,
            "item_count": len(items),
            "model": model,
            "generated_at": now,
        }
