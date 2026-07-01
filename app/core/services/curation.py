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
    # key, label, table, subject_columns, relay_prefixed, extra_columns, split.
    # subject_columns → the memory id(s) each job acted on; relay_prefixed marks
    # relay-materialized memories (browsable id is ``relay:<value>``); split
    # (column, values) fans one queue table into one card per value (e.g. the
    # maintenance queue → Enrich / Improve). This lets the Activity log show
    # *which memory* + a per-card progress read, not an opaque queue-row id.
    _ACTIVITY_WORKERS = (
        ("item", "Enrichment (relay)", "relay_queue_item", ("ref_id",), True, (), None),
        (
            "aggregate",
            "Digest (relay)",
            "relay_queue_aggregate",
            ("ref_id",),
            True,
            (),
            None,
        ),
        (
            "reconcile",
            "Reconcile",
            "reconcile_queue",
            ("new_memory_id", "old_memory_id"),
            False,
            (),
            None,
        ),
        (
            "maintenance",
            "Maintenance",
            "maintenance_queue",
            ("memory_id",),
            False,
            # attempts lets the UI show errors only on rows still failing
            # (dead_letter / pending retry), not on eventually-successful ones.
            ("operation", "attempts"),
            ("operation", ("enrich", "improve")),
        ),
    )

    async def list_activity(self) -> dict:
        """Per-worker queue activity: status counts + 10 most-recent jobs, each
        annotated with the memory it acted on (id + title + link).

        Each worker maps to one queue table (optionally split by a column into
        multiple cards). A missing table (schema not yet created) degrades to
        empty counts/recent for that worker instead of failing the response.
        """
        # Expand split workers into per-value specs (key, label, table, ...,
        # where=(column, value)|None).
        specs = []
        for (
            key,
            label,
            table,
            subj_cols,
            relay_prefixed,
            extra,
            split,
        ) in self._ACTIVITY_WORKERS:
            if split:
                col, values = split
                for val in values:
                    specs.append(
                        (
                            f"{key}:{val}",
                            f"{label} · {val}",
                            table,
                            subj_cols,
                            relay_prefixed,
                            extra,
                            (col, val),
                        )
                    )
            else:
                specs.append(
                    (key, label, table, subj_cols, relay_prefixed, extra, None)
                )

        workers = []
        subject_ids: set[str] = set()
        for key, label, table, subj_cols, relay_prefixed, extra, where in specs:
            counts: dict = {}
            recent: list[dict] = []
            where_sql = f" WHERE {where[0]} = ?" if where else ""
            where_params = (where[1],) if where else ()
            try:
                count_rows = await self.db.fetchall(
                    f"SELECT status, COUNT(*) AS n FROM {table}{where_sql} "
                    "GROUP BY status",
                    where_params,
                )
                counts = {row["status"]: row["n"] for row in count_rows}
                cols = ["id", "status", "updated_at", "last_error"]
                cols.extend(subj_cols)
                cols.extend(extra)
                recent_rows = await self.db.fetchall(
                    f"SELECT {', '.join(cols)} FROM {table}{where_sql} "
                    "ORDER BY updated_at DESC LIMIT 10",
                    where_params,
                )
                for row in recent_rows:
                    subjects = []
                    for col in subj_cols:
                        raw = row[col] if col in row.keys() else None
                        if not raw:
                            continue
                        mem_id = f"relay:{raw}" if relay_prefixed else str(raw)
                        subjects.append(mem_id)
                        subject_ids.add(mem_id)
                    entry = {
                        "id": row["id"],
                        "status": row["status"],
                        "updated_at": row["updated_at"],
                        "last_error": row["last_error"],
                        "subjects": subjects,
                    }
                    for col in extra:
                        entry[col] = row[col] if col in row.keys() else None
                    recent.append(entry)
            except Exception as e:
                logger.debug("Activity worker %s unavailable: %s", key, e)
                counts, recent = {}, []
            workers.append(
                {"key": key, "label": label, "counts": counts, "recent": recent}
            )

        titles = await self._subject_titles(subject_ids)
        for worker in workers:
            for entry in worker["recent"]:
                entry["subjects"] = [
                    {
                        "memory_id": mid,
                        "title": titles.get(mid, {}).get("title", ""),
                        "exists": mid in titles,
                    }
                    for mid in entry["subjects"]
                ]
        return {"workers": workers}

    async def _subject_titles(self, memory_ids: set[str]) -> dict:
        """Map memory_id → {title} for the activity log. Title = the memory's
        enrichment title if present, else the first non-empty content line
        (truncated). One batched query; missing ids are simply absent."""
        if not memory_ids:
            return {}
        ids = list(memory_ids)
        placeholders = ",".join("?" for _ in ids)
        try:
            rows = await self.db.fetchall(
                f"""
                SELECT m.id AS id, m.content AS content, e.title AS enrich_title
                FROM memories m
                LEFT JOIN memory_enrichment e ON e.memory_id = m.id
                WHERE m.id IN ({placeholders})
                """,
                tuple(ids),
            )
        except Exception:
            # memory_enrichment may not exist yet — fall back to content only.
            try:
                rows = await self.db.fetchall(
                    f"SELECT id, content, '' AS enrich_title FROM memories "
                    f"WHERE id IN ({placeholders})",
                    tuple(ids),
                )
            except Exception:
                return {}
        out: dict = {}
        for row in rows:
            title = (row["enrich_title"] or "").strip()
            if not title:
                content = str(row["content"] or "")
                first = next(
                    (
                        ln.strip(" #").strip()
                        for ln in content.splitlines()
                        if ln.strip()
                    ),
                    "",
                )
                title = first[:80] + ("…" if len(first) > 80 else "")
            out[str(row["id"])] = {"title": title}
        return out

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
