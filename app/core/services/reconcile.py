"""Async reconcile worker (SSOT #3, F2).

Drains the ``reconcile_queue`` populated by the write-time F1 sync gate
(``MemoryService._enqueue_reconcile``). For each ``(new, old)`` candidate pair:

1. **Claim** a pending row with a lease (mirrors the relay_queue_item pattern).
2. **Revalidate** (C2 TOCTOU): if either memory was edited (content_hash drift)
   or deleted since enqueue, the job is stale — finish it without acting.
3. **NLI pre-gate**: cheap contradiction check (reuses ConflictDetectorService).
   No contradiction ⇒ likely a benign near-duplicate; finish without a relation.
4. **LLM judgment**: ``RelayEnricher.reconcile`` proposes supersede/merge/keep/
   conflict + rationale + merged_text.
5. **Record a PROPOSED relation** in ``memory_relations`` (SUPERSEDES/CONFLICTS,
   ``metadata.state='proposed'``). Memory status is never flipped here — the
   human curation gate (F4) does that. (Invariant: new stays canonical; only a
   superseded old is demoted, and only after approval.)

The LLM call is async/off the write path, so the per-add cross-encoder L1 risk
never touches request latency.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from ..database.base import Database
from ..schemas.relations import RelationCreate, RelationType
from .relation import RelationService

logger = logging.getLogger(__name__)

# Map the LLM verdict to a (relation_type, source, target) proposal. source is
# the memory that would win; target is the one that would be demoted on approval.
# 'keep_both' produces no relation; 'merge'/'conflict' record a CONFLICTS pair
# for the human to resolve.
_TERMINAL_STATUSES = ("done", "stale", "dead_letter")


class ReconcileService:
    """Processes one reconcile_queue item per ``process_next`` call."""

    def __init__(
        self,
        db: Database,
        *,
        max_attempts: int = 5,
        backoff_base_seconds: float = 30.0,
        backoff_max_seconds: float = 3600.0,
        lease_seconds: int = 120,
    ):
        self.db = db
        self.relation_service = RelationService(db)
        self.max_attempts = max_attempts
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self.lease_seconds = lease_seconds

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _now_epoch() -> float:
        return datetime.now(timezone.utc).timestamp()

    async def _claim(self, worker_id: str, now: float) -> Optional[dict]:
        """Atomically claim one pending (or lease-expired) row."""
        lease_cutoff = now - self.lease_seconds
        row = await self.db.fetchone(
            """
            SELECT * FROM reconcile_queue
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
            UPDATE reconcile_queue
            SET status = 'processing', locked_by = ?, locked_at = ?, updated_at = ?
            WHERE id = ? AND status = ?
            """,
            (worker_id, now, self._now_iso(), item["id"], item["status"]),
        )
        if cur.rowcount == 0:
            # Another worker grabbed it first.
            return None
        return item

    async def _finish(self, item_id: str, status: str) -> None:
        await self.db.execute(
            "UPDATE reconcile_queue SET status = ?, locked_by = NULL, "
            "locked_at = NULL, updated_at = ? WHERE id = ?",
            (status, self._now_iso(), item_id),
        )

    async def _retry_or_dead(self, item: dict, error: str, now: float) -> None:
        attempts = int(item.get("attempts", 0)) + 1
        if attempts >= self.max_attempts:
            await self.db.execute(
                "UPDATE reconcile_queue SET status = 'dead_letter', attempts = ?, "
                "last_error = ?, locked_by = NULL, locked_at = NULL, updated_at = ? "
                "WHERE id = ?",
                (attempts, error[:500], self._now_iso(), item["id"]),
            )
            return
        backoff = min(
            self.backoff_max_seconds, self.backoff_base_seconds * (2 ** (attempts - 1))
        )
        await self.db.execute(
            "UPDATE reconcile_queue SET status = 'pending', attempts = ?, "
            "next_attempt_at = ?, last_error = ?, locked_by = NULL, "
            "locked_at = NULL, updated_at = ? WHERE id = ?",
            (attempts, now + backoff, error[:500], self._now_iso(), item["id"]),
        )

    async def _get_memory(self, memory_id: str) -> Optional[dict]:
        row = await self.db.fetchone(
            "SELECT id, content, content_hash, status FROM memories WHERE id = ?",
            (memory_id,),
        )
        return dict(row) if row else None

    @staticmethod
    def _proposal(verdict: str, new_id: str, old_id: str):
        """Return (relation_type, source_id, target_id) or None for keep_both."""
        if verdict == "supersede_old":
            return (RelationType.SUPERSEDES, new_id, old_id)
        if verdict == "supersede_new":
            # old is correct; old supersedes new (new gets demoted on approval, C3).
            return (RelationType.SUPERSEDES, old_id, new_id)
        if verdict in ("merge", "conflict"):
            return (RelationType.CONFLICTS, new_id, old_id)
        return None  # keep_both

    async def process_next(
        self, *, worker_id: str, enricher: Any, conflict_detector: Any
    ) -> dict:
        """Claim and process a single reconcile job.

        Returns {"job_id": <id|None>, "processed": bool, ...}.
        """
        now = self._now_epoch()
        item = await self._claim(worker_id, now)
        if item is None:
            return {"job_id": None}

        try:
            new = await self._get_memory(item["new_memory_id"])
            old = await self._get_memory(item["old_memory_id"])

            # C2 revalidation: skip stale jobs (memory edited/deleted since enqueue).
            if (
                new is None
                or old is None
                or new["content_hash"] != item.get("new_content_hash")
                or old["content_hash"] != item.get("old_content_hash")
                or new["status"] != "canonical"
                or old["status"] != "canonical"
            ):
                await self._finish(item["id"], "stale")
                return {"job_id": item["id"], "processed": True, "stale": True}

            # NLI pre-gate (cheap contradiction filter). Blocking → thread.
            candidates = [
                {
                    "id": old["id"],
                    "content": old["content"],
                    "similarity_score": item.get("similarity") or 1.0,
                }
            ]
            conflicts = await asyncio.to_thread(
                conflict_detector.detect_conflicts, new["content"], candidates
            )
            if not conflicts:
                # No contradiction → benign near-duplicate; nothing to reconcile.
                await self._finish(item["id"], "done")
                return {"job_id": item["id"], "processed": True, "no_conflict": True}

            # LLM judgment (off the write path).
            payload = await enricher.reconcile(new["content"], old["content"])
            verdict = str(payload.get("verdict", "conflict")).strip().lower()
            proposal = self._proposal(verdict, new["id"], old["id"])

            if proposal is not None:
                rel_type, source_id, target_id = proposal
                await self.relation_service.create_relation(
                    RelationCreate(
                        source_id=source_id,
                        target_id=target_id,
                        relation_type=rel_type,
                        strength=float(item.get("similarity") or 1.0),
                        metadata={
                            "state": "proposed",
                            "verdict": verdict,
                            "rationale": str(payload.get("rationale", ""))[:500],
                            "merged_text": payload.get("merged_text"),
                            "contradiction_score": getattr(
                                conflicts[0], "contradiction_score", None
                            ),
                        },
                    )
                )

            await self._finish(item["id"], "done")
            return {"job_id": item["id"], "processed": True, "verdict": verdict}

        except Exception as exc:  # noqa: BLE001 - record and retry/dead-letter
            logger.warning("Reconcile job %s failed: %s", item.get("id"), exc)
            await self._retry_or_dead(item, str(exc), now)
            return {"job_id": item["id"], "processed": False, "error": str(exc)}
