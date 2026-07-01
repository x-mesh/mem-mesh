"""Human curation gate for write-time reconcile (SSOT #3, F4).

The async worker (F2) records reconcile verdicts as PROPOSED relations
(``memory_relations.metadata.state='proposed'``). Nothing is demoted until a
human approves here. Each mutating action runs in a single transaction so a
status flip and its relation update commit together.

Invariant held by this gate: a new memory stays ``canonical`` until a human
explicitly approves a supersede against it (or rejects it via ``reject_new``);
only a superseded loser is set to ``deprecated``.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from ..database.base import Database
from ..schemas.relations import RelationCreate, RelationType
from .relation import RelationService

logger = logging.getLogger(__name__)


class CurationService:
    """Read the reconcile proposal queue and apply human decisions."""

    def __init__(self, db: Database, memory_service: Any = None):
        self.db = db
        self.memory_service = memory_service
        self.relation_service = RelationService(db)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    async def list_queue(
        self, project_id: Optional[str] = None, limit: int = 50
    ) -> list[dict]:
        """Return PROPOSED supersede/conflict relations awaiting a decision."""
        sql = """
            SELECT r.id, r.source_id, r.target_id, r.relation_type, r.strength,
                   r.metadata, r.created_at,
                   substr(sm.content, 1, 200) AS source_preview,
                   substr(tm.content, 1, 200) AS target_preview
            FROM memory_relations r
            JOIN memories sm ON sm.id = r.source_id
            JOIN memories tm ON tm.id = r.target_id
            WHERE json_extract(r.metadata, '$.state') = 'proposed'
        """
        params: list[Any] = []
        if project_id:
            sql += " AND (sm.project_id = ? OR tm.project_id = ?)"
            params += [project_id, project_id]
        sql += " ORDER BY r.created_at DESC LIMIT ?"
        params.append(limit)

        rows = await self.db.fetchall(sql, tuple(params))
        items = []
        for row in rows:
            d = dict(row)
            try:
                d["metadata"] = json.loads(d.get("metadata") or "{}")
            except (TypeError, json.JSONDecodeError):
                d["metadata"] = {}
            items.append(d)
        return items

    # LLM worker queue tables (outbox excluded). Order is contract-defined:
    # item → aggregate → reconcile. Table names are a fixed literal allowlist,
    # never user input — safe to interpolate.
    _ACTIVITY_WORKERS = (
        ("item", "Enrichment", "relay_queue_item"),
        ("aggregate", "Digest", "relay_queue_aggregate"),
        ("reconcile", "Reconcile", "reconcile_queue"),
    )

    async def list_activity(self) -> dict:
        """Per-worker queue activity: status counts + 10 most-recent rows.

        Each worker maps to one queue table. A missing table (schema not yet
        created) degrades to empty counts/recent for that worker instead of
        failing the whole response.
        """
        workers = []
        for key, label, table in self._ACTIVITY_WORKERS:
            counts: dict = {}
            recent: list[dict] = []
            try:
                count_rows = await self.db.fetchall(
                    f"SELECT status, COUNT(*) AS n FROM {table} GROUP BY status"
                )
                counts = {row["status"]: row["n"] for row in count_rows}
                recent_rows = await self.db.fetchall(
                    f"SELECT id, status, updated_at, last_error FROM {table} "
                    "ORDER BY updated_at DESC LIMIT 10"
                )
                recent = [
                    {
                        "id": row["id"],
                        "status": row["status"],
                        "updated_at": row["updated_at"],
                        "last_error": row["last_error"],
                    }
                    for row in recent_rows
                ]
            except Exception as e:
                logger.debug("Activity worker %s unavailable: %s", key, e)
                counts, recent = {}, []
            workers.append(
                {"key": key, "label": label, "counts": counts, "recent": recent}
            )
        return {"workers": workers}

    async def _relation(self, relation_id: str) -> dict:
        row = await self.db.fetchone(
            "SELECT * FROM memory_relations WHERE id = ?", (relation_id,)
        )
        if row is None:
            raise ValueError(f"Relation not found: {relation_id}")
        rel = dict(row)
        try:
            rel["_meta"] = json.loads(rel.get("metadata") or "{}")
        except (TypeError, json.JSONDecodeError):
            rel["_meta"] = {}
        return rel

    async def _would_cycle(self, winner_id: str, loser_id: str) -> bool:
        """True if making winner supersede loser would close a supersede loop.

        Walks the APPROVED supersede chain starting at loser; if it reaches
        winner, demoting loser under winner would create a cycle.
        """
        row = await self.db.fetchone(
            """
            WITH RECURSIVE chain(id) AS (
                SELECT target_id FROM memory_relations
                WHERE source_id = ? AND relation_type = 'supersedes'
                  AND json_extract(metadata, '$.state') = 'approved'
                UNION
                SELECT r.target_id FROM memory_relations r
                JOIN chain c ON r.source_id = c.id
                WHERE r.relation_type = 'supersedes'
                  AND json_extract(r.metadata, '$.state') = 'approved'
            )
            SELECT 1 FROM chain WHERE id = ? LIMIT 1
            """,
            (loser_id, winner_id),
        )
        return row is not None

    async def approve_supersede(self, relation_id: str) -> dict:
        """Approve a supersede: deprecate the loser, mark the relation approved."""
        rel = await self._relation(relation_id)
        if rel["relation_type"] != "supersedes":
            raise ValueError("Relation is not a supersede proposal")
        if rel["_meta"].get("state") != "proposed":
            raise ValueError("Relation is not pending (already resolved)")

        winner, loser = rel["source_id"], rel["target_id"]
        if await self._would_cycle(winner, loser):
            raise ValueError("Reconcile cycle: approving would create a supersede loop")

        now = self._now()
        async with self.db.transaction():
            await self.db.execute(
                "UPDATE memories SET status = 'deprecated', updated_at = ? "
                "WHERE id = ?",
                (now, loser),
            )
            await self.db.execute(
                "UPDATE memory_relations "
                "SET metadata = json_set(COALESCE(metadata, '{}'), '$.state', "
                "'approved'), updated_at = ? WHERE id = ?",
                (now, relation_id),
            )
        return {"relation_id": relation_id, "deprecated": loser, "kept": winner}

    async def reject_new(self, memory_id: str) -> dict:
        """C3: human judged the NEW memory wrong → deprecate it directly.

        Covers the case the auto-pipeline cannot: new is the incorrect one and
        the old memory is correct, with no supersede proposal to approve.
        """
        now = self._now()
        async with self.db.transaction():
            cur = await self.db.execute(
                "UPDATE memories SET status = 'deprecated', updated_at = ? "
                "WHERE id = ? AND COALESCE(status, 'canonical') = 'canonical'",
                (now, memory_id),
            )
        if cur.rowcount == 0:
            raise ValueError(f"Canonical memory not found: {memory_id}")
        return {"deprecated": memory_id}

    async def approve_merge(
        self, relation_id: str, merged_text: Optional[str] = None
    ) -> dict:
        """Approve a merge: create a new canonical from merged_text, deprecate both.

        ``merged_text`` overrides the LLM's proposal when the human edited it in
        the UI; otherwise the stored ``metadata.merged_text`` is used. Order
        matters: the two originals are deprecated FIRST so the new memory's F1
        gate (canonical-only candidates) does not re-detect them and re-enqueue.
        """
        if self.memory_service is None:
            raise ValueError("memory_service is required for merge approval")
        rel = await self._relation(relation_id)
        if rel["_meta"].get("state") != "proposed":
            raise ValueError("Relation is not pending (already resolved)")
        if rel["_meta"].get("verdict") != "merge":
            raise ValueError("Relation is not a merge proposal")

        text = (merged_text or rel["_meta"].get("merged_text") or "").strip()
        if len(text) < 10:
            raise ValueError("merged_text is required (min 10 chars)")

        source_id, target_id = rel["source_id"], rel["target_id"]
        srow = await self.db.fetchone(
            "SELECT project_id, category FROM memories WHERE id = ?", (source_id,)
        )
        project_id = srow["project_id"] if srow else None
        category = srow["category"] if srow else "task"

        # 1. Deprecate both originals + approve the relation (single transaction),
        # BEFORE creating the merged memory so it isn't re-detected against them.
        now = self._now()
        async with self.db.transaction():
            await self.db.execute(
                "UPDATE memories SET status = 'deprecated', updated_at = ? "
                "WHERE id IN (?, ?)",
                (now, source_id, target_id),
            )
            await self.db.execute(
                "UPDATE memory_relations "
                "SET metadata = json_set(COALESCE(metadata, '{}'), '$.state', "
                "'approved'), updated_at = ? WHERE id = ?",
                (now, relation_id),
            )

        # 2. Create the merged canonical (its own transaction + embedding).
        res = await self.memory_service.create(
            content=text,
            project_id=project_id,
            category=category,
            source="reconcile-merge",
            skip_quality_gate=True,
        )
        merged_id = res.id

        # 3. Link merged → each original (approved SUPERSEDES).
        for old in (source_id, target_id):
            await self.relation_service.create_relation(
                RelationCreate(
                    source_id=merged_id,
                    target_id=old,
                    relation_type=RelationType.SUPERSEDES,
                    metadata={"state": "approved", "via": "merge"},
                )
            )

        return {"merged_id": merged_id, "deprecated": [source_id, target_id]}

    async def dismiss(self, relation_id: str) -> dict:
        """Dismiss a proposal (keep both, no status change)."""
        await self._relation(relation_id)
        now = self._now()
        await self.db.execute(
            "UPDATE memory_relations "
            "SET metadata = json_set(COALESCE(metadata, '{}'), '$.state', "
            "'dismissed'), updated_at = ? WHERE id = ?",
            (now, relation_id),
        )
        return {"relation_id": relation_id, "dismissed": True}
