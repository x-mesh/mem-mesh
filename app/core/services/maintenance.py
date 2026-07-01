"""Project-level batch maintenance (enrich / improve).

Bulk enrich and improve are run as *asynchronous* per-memory jobs, drained by
the relay worker's ``maintenance`` task — never a synchronous LLM loop over a
whole project (that would time out and hammer the LLM; see CLAUDE.md L1/L5).

Two operations live here:

* ``enrich``  — additive only: generate title/abstract/tags into the
  ``memory_enrichment`` side table (EnrichmentStore). Never touches
  ``memories.content``.
* ``improve`` — content-rewriting, so it is NEVER auto-applied. The worker only
  stores a *proposal* in ``refine_proposal``; a human reviews the diff and
  approves it (which then updates the memory), mirroring the reconcile →
  curation human-gate pattern.

Reconcile is intentionally NOT here — bulk reconcile reuses the existing
``reconcile_queue`` + reconcile worker directly (MemoryService.enqueue_project_
reconcile), since its job shape (memory *pairs* + NLI pre-gate) is already fully
wired there.

Schema is lazy/memoized per Database instance (like EnrichmentStore/ChatStore)
so no migration bump is needed.
"""

from __future__ import annotations

import json
import logging
import uuid
import weakref
from datetime import datetime, timezone
from typing import Any, List, Optional

from .enrich_store import EnrichmentStore

logger = logging.getLogger(__name__)

MAINTENANCE_OPERATIONS = ("enrich", "improve")
_ACTIVE_STATUSES = ("pending", "processing")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _epoch_now() -> float:
    return datetime.now(timezone.utc).timestamp()


class MaintenanceService:
    """Enqueue + drain the per-memory enrich/improve maintenance queue."""

    _schema_ready: "weakref.WeakSet" = weakref.WeakSet()

    def __init__(
        self,
        db: Any,
        *,
        max_attempts: int = 3,
        backoff_base_seconds: float = 30.0,
        backoff_max_seconds: float = 1800.0,
        lease_seconds: int = 300,
    ):
        self.db = db
        self.max_attempts = max_attempts
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self.lease_seconds = lease_seconds

    # ── schema ──────────────────────────────────────────────────────────────

    async def ensure_schema(self) -> None:
        if self.db in MaintenanceService._schema_ready:
            return
        async with self.db.transaction():
            await self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS maintenance_queue (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    project_id TEXT,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL DEFAULT 0,
                    last_error TEXT,
                    locked_by TEXT,
                    locked_at REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            # One live (pending/processing) job per (memory, operation) — a
            # re-run while a job is still queued is a no-op, not a duplicate.
            await self.db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_maintenance_queue_live
                ON maintenance_queue(memory_id, operation)
                WHERE status IN ('pending', 'processing')
                """
            )
            await self.db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_maintenance_queue_claim
                ON maintenance_queue(status, next_attempt_at, created_at)
                """
            )
            await self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS refine_proposal (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    project_id TEXT,
                    original_hash TEXT NOT NULL,
                    proposed_content TEXT NOT NULL,
                    proposed_category TEXT,
                    proposed_tags TEXT,
                    rationale TEXT,
                    model TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            # One pending proposal per memory (approving/rejecting frees the slot).
            await self.db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_refine_proposal_pending
                ON refine_proposal(memory_id)
                WHERE status = 'pending'
                """
            )
        MaintenanceService._schema_ready.add(self.db)

    # ── enqueue ─────────────────────────────────────────────────────────────

    async def enqueue_project(
        self,
        *,
        project_id: str,
        operations: List[str],
        force: bool = False,
    ) -> dict:
        """Queue enrich/improve jobs for every canonical memory in a project.

        ``force`` re-enqueues even memories that already have enrichment (enrich)
        or a pending proposal (improve). Returns per-operation queued counts and
        a ``skipped`` breakdown (already-done / already-queued).
        """
        await self.ensure_schema()
        ops = [op for op in operations if op in MAINTENANCE_OPERATIONS]
        result: dict = {"enqueued": {}, "skipped": {}, "total_memories": 0}
        if not ops:
            return result

        rows = await self.db.fetchall(
            """
            SELECT id, content_hash FROM memories
            WHERE project_id = ?
              AND COALESCE(status, 'canonical') = 'canonical'
            """,
            (project_id,),
        )
        memories = [(str(r["id"]), str(r["content_hash"])) for r in rows]
        result["total_memories"] = len(memories)
        if not memories:
            return result

        ids = [mid for mid, _ in memories]

        for op in ops:
            skip_ids: set[str] = set()
            if not force:
                skip_ids = await self._already_done_ids(op, ids)
            enqueued = 0
            skipped_done = 0
            now = _utc_now()
            for memory_id, content_hash in memories:
                if memory_id in skip_ids:
                    skipped_done += 1
                    continue
                inserted = await self._insert_job(
                    memory_id=memory_id,
                    operation=op,
                    project_id=project_id,
                    content_hash=content_hash,
                    now=now,
                )
                if inserted:
                    enqueued += 1
                else:
                    # Live job already queued (unique index) — treated as skip.
                    skipped_done += 1
            result["enqueued"][op] = enqueued
            result["skipped"][op] = skipped_done
        return result

    async def _already_done_ids(self, operation: str, ids: List[str]) -> set[str]:
        if not ids:
            return set()
        placeholders = ",".join("?" for _ in ids)
        if operation == "enrich":
            query = (
                f"SELECT memory_id FROM memory_enrichment "
                f"WHERE memory_id IN ({placeholders})"
            )
            params: tuple = tuple(ids)
        else:  # improve
            query = (
                f"SELECT memory_id FROM refine_proposal "
                f"WHERE status = 'pending' AND memory_id IN ({placeholders})"
            )
            params = tuple(ids)
        try:
            rows = await self.db.fetchall(query, params)
        except Exception:
            # Table may not exist yet (nothing enriched/proposed) — nothing done.
            return set()
        return {str(r["memory_id"]) for r in rows}

    async def _insert_job(
        self,
        *,
        memory_id: str,
        operation: str,
        project_id: Optional[str],
        content_hash: str,
        now: str,
    ) -> bool:
        """INSERT one job; returns False if a live job already exists (unique
        partial index → OR IGNORE)."""
        cur = await self.db.execute(
            """
            INSERT OR IGNORE INTO maintenance_queue (
                id, memory_id, operation, project_id, content_hash,
                status, attempts, next_attempt_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'pending', 0, 0, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                memory_id,
                operation,
                project_id,
                content_hash,
                now,
                now,
            ),
        )
        return cur.rowcount > 0

    # ── claim / process ─────────────────────────────────────────────────────

    async def _claim(self, worker_id: str, now: float) -> Optional[dict]:
        lease_cutoff = now - self.lease_seconds
        row = await self.db.fetchone(
            """
            SELECT * FROM maintenance_queue
            WHERE status = 'pending'
               OR (status = 'processing' AND COALESCE(locked_at, 0) < ?)
            ORDER BY next_attempt_at ASC, created_at ASC
            LIMIT 1
            """,
            (lease_cutoff,),
        )
        if row is None:
            return None
        item = dict(row)
        if item.get("next_attempt_at", 0) > now:
            return None
        cur = await self.db.execute(
            """
            UPDATE maintenance_queue
            SET status = 'processing', locked_by = ?, locked_at = ?, updated_at = ?
            WHERE id = ? AND status = ?
            """,
            (worker_id, now, _utc_now(), item["id"], item["status"]),
        )
        if cur.rowcount == 0:
            return None  # lost the race
        return item

    async def _finish(self, item_id: str, status: str) -> None:
        await self.db.execute(
            "UPDATE maintenance_queue SET status = ?, locked_by = NULL, "
            "locked_at = NULL, updated_at = ? WHERE id = ?",
            (status, _utc_now(), item_id),
        )

    async def _retry_or_dead(self, item: dict, error: str, now: float) -> None:
        attempts = int(item.get("attempts", 0)) + 1
        if attempts >= self.max_attempts:
            await self.db.execute(
                "UPDATE maintenance_queue SET status = 'dead_letter', attempts = ?, "
                "last_error = ?, locked_by = NULL, locked_at = NULL, updated_at = ? "
                "WHERE id = ?",
                (attempts, error[:500], _utc_now(), item["id"]),
            )
            return
        backoff = min(
            self.backoff_max_seconds, self.backoff_base_seconds * (2 ** (attempts - 1))
        )
        await self.db.execute(
            "UPDATE maintenance_queue SET status = 'pending', attempts = ?, "
            "next_attempt_at = ?, last_error = ?, locked_by = NULL, "
            "locked_at = NULL, updated_at = ? WHERE id = ?",
            (attempts, now + backoff, error[:500], _utc_now(), item["id"]),
        )

    async def process_next(
        self, *, worker_id: str, chat_service: Any, settings: Any
    ) -> dict:
        """Claim and run one enrich/improve job. Returns a small result dict."""
        await self.ensure_schema()
        now = _epoch_now()
        item = await self._claim(worker_id, now)
        if item is None:
            return {"job_id": None}

        try:
            memory = await self.db.fetchone(
                "SELECT id, content, content_hash, category, tags, project_id, status "
                "FROM memories WHERE id = ?",
                (item["memory_id"],),
            )
            # C2 staleness: memory edited/deleted/demoted since enqueue → skip.
            if (
                memory is None
                or memory["content_hash"] != item.get("content_hash")
                or str(memory["status"] or "canonical") != "canonical"
            ):
                await self._finish(item["id"], "stale")
                return {"job_id": item["id"], "processed": True, "stale": True}

            if item["operation"] == "enrich":
                await self._run_enrich(memory, chat_service, settings)
            elif item["operation"] == "improve":
                await self._run_improve(memory, chat_service, settings)
            else:
                await self._finish(item["id"], "done")
                return {"job_id": item["id"], "processed": True, "unknown_op": True}

            await self._finish(item["id"], "done")
            return {
                "job_id": item["id"],
                "processed": True,
                "operation": item["operation"],
            }
        except Exception as exc:  # noqa: BLE001 - record + retry/dead-letter
            logger.warning("Maintenance job %s failed: %s", item.get("id"), exc)
            await self._retry_or_dead(item, str(exc), now)
            return {"job_id": item["id"], "processed": False, "error": str(exc)}

    async def _run_enrich(self, memory: Any, chat_service: Any, settings: Any) -> None:
        from ..redaction import redact_secrets

        data = await chat_service.enrich_memory_content(
            content=str(memory["content"] or ""), settings=settings
        )
        await EnrichmentStore(self.db).upsert(
            memory_id=str(memory["id"]),
            title=redact_secrets(str(data.get("title", ""))),
            abstract=redact_secrets(str(data.get("abstract", ""))),
            tags=list(data.get("tags") or []),
            display_kind=str(data.get("display_kind", "")),
            model=str(data.get("model", "")),
        )

    async def _run_improve(self, memory: Any, chat_service: Any, settings: Any) -> None:
        from ..redaction import redact_secrets

        original = str(memory["content"] or "")
        try:
            current_tags = json.loads(memory["tags"]) if memory["tags"] else []
        except (json.JSONDecodeError, TypeError):
            current_tags = []
        data = await chat_service.refine_memory_content(
            content=original,
            category=memory["category"],
            tags=current_tags,
            settings=settings,
        )
        proposed = redact_secrets(str(data.get("content", "") or ""))
        # No proposal when the model returned nothing or an unchanged rewrite.
        if not proposed or proposed.strip() == original.strip():
            return
        proposed_tags = data.get("tags")
        await self.db.execute(
            "DELETE FROM refine_proposal WHERE memory_id = ? AND status = 'pending'",
            (str(memory["id"]),),
        )
        now = _utc_now()
        await self.db.execute(
            """
            INSERT INTO refine_proposal (
                id, memory_id, project_id, original_hash, proposed_content,
                proposed_category, proposed_tags, rationale, model,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                str(uuid.uuid4()),
                str(memory["id"]),
                memory["project_id"],
                str(memory["content_hash"]),
                proposed,
                (str(data.get("category")) if data.get("category") else None),
                (
                    json.dumps(list(proposed_tags), ensure_ascii=False)
                    if isinstance(proposed_tags, list)
                    else None
                ),
                str(data.get("rationale", ""))[:1000] or None,
                str(data.get("model", "")) or None,
                now,
                now,
            ),
        )

    # ── refine proposal review (improve human gate) ─────────────────────────

    async def list_refine_proposals(
        self, *, project_id: Optional[str] = None, limit: int = 50
    ) -> List[dict]:
        await self.ensure_schema()
        params: list = []
        where = "p.status = 'pending'"
        if project_id:
            where += " AND p.project_id = ?"
            params.append(project_id)
        params.append(max(1, min(limit, 200)))
        rows = await self.db.fetchall(
            f"""
            SELECT p.id, p.memory_id, p.project_id, p.original_hash,
                   p.proposed_content, p.proposed_category, p.proposed_tags,
                   p.rationale, p.model, p.created_at,
                   m.content AS original_content, m.content_hash AS current_hash,
                   m.category AS current_category
            FROM refine_proposal p
            LEFT JOIN memories m ON m.id = p.memory_id
            WHERE {where}
            ORDER BY p.created_at DESC
            LIMIT ?
            """,
            tuple(params),
        )
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["proposed_tags"] = (
                    json.loads(d["proposed_tags"]) if d.get("proposed_tags") else None
                )
            except (json.JSONDecodeError, TypeError):
                d["proposed_tags"] = None
            # Flag proposals whose base memory changed since the proposal.
            d["stale"] = (
                d.get("current_hash") is None
                or d.get("current_hash") != d.get("original_hash")
            )
            out.append(d)
        return out

    async def count_refine_proposals(self, *, project_id: Optional[str] = None) -> int:
        await self.ensure_schema()
        if project_id:
            row = await self.db.fetchone(
                "SELECT COUNT(*) AS c FROM refine_proposal "
                "WHERE status = 'pending' AND project_id = ?",
                (project_id,),
            )
        else:
            row = await self.db.fetchone(
                "SELECT COUNT(*) AS c FROM refine_proposal WHERE status = 'pending'"
            )
        return int(row["c"]) if row else 0

    async def get_refine_proposal(self, proposal_id: str) -> Optional[dict]:
        await self.ensure_schema()
        row = await self.db.fetchone(
            "SELECT * FROM refine_proposal WHERE id = ?", (proposal_id,)
        )
        return dict(row) if row else None

    async def reject_refine_proposal(self, proposal_id: str) -> bool:
        await self.ensure_schema()
        cur = await self.db.execute(
            "UPDATE refine_proposal SET status = 'rejected', updated_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (_utc_now(), proposal_id),
        )
        return cur.rowcount > 0

    async def mark_proposal_approved(self, proposal_id: str) -> None:
        await self.db.execute(
            "UPDATE refine_proposal SET status = 'approved', updated_at = ? "
            "WHERE id = ?",
            (_utc_now(), proposal_id),
        )

    async def cancel_pending(
        self, *, operation: Optional[str] = None, project_id: Optional[str] = None
    ) -> int:
        """Cancel queued jobs so the worker stops picking them up.

        Marks ``pending`` rows as ``cancelled`` (kept for the activity log rather
        than deleted). A job already ``processing`` finishes its current LLM
        call — it can't be interrupted mid-flight — but no new ones start.
        Optional ``operation`` (enrich/improve) and ``project_id`` narrow the
        scope. Returns the number cancelled.
        """
        await self.ensure_schema()
        clauses = ["status = 'pending'"]
        where_params: list = []
        if operation:
            clauses.append("operation = ?")
            where_params.append(operation)
        if project_id:
            clauses.append("project_id = ?")
            where_params.append(project_id)
        cur = await self.db.execute(
            f"UPDATE maintenance_queue SET status = 'cancelled', "
            f"locked_by = NULL, locked_at = NULL, updated_at = ? "
            f"WHERE {' AND '.join(clauses)}",
            (_utc_now(), *where_params),  # SET's updated_at first, then WHERE
        )
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    async def status_counts(self) -> dict:
        await self.ensure_schema()
        rows = await self.db.fetchall(
            "SELECT operation, status, COUNT(*) AS c FROM maintenance_queue "
            "GROUP BY operation, status"
        )
        counts: dict = {}
        for r in rows:
            counts.setdefault(str(r["operation"]), {})[str(r["status"])] = int(r["c"])
        return counts
