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

logger = logging.getLogger(__name__)


class CurationService:
    """Read the reconcile proposal queue and apply human decisions."""

    def __init__(self, db: Database):
        self.db = db

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
