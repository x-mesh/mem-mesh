"""Project overview generation and cache from active curated results."""

from __future__ import annotations

import hashlib
import json
import logging
import weakref
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from app.core.errors import ChatProviderError, ReconcilerConflictError
from app.core.services.effective_read import EffectiveReadService
from app.core.services.enrich_store import EnrichmentStore

logger = logging.getLogger(__name__)

_RECENT_LIMIT = 20
_SNIPPET_CHARS = 300

# Scheduled-refresh interval bounds (hours). Default is a half-day; a project's
# overview is regenerated at most once per interval when inputs changed after
# its last scheduled run.
_MIN_INTERVAL_HOURS = 6
_MAX_INTERVAL_HOURS = 24
_DEFAULT_INTERVAL_HOURS = 12


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_line(content: str) -> str:
    for ln in (content or "").splitlines():
        s = ln.strip(" #").strip()
        if s:
            return s
    return ""


class _OverviewClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: StrictStr = Field(min_length=1)
    memory_id: StrictStr = Field(min_length=1)


class _OverviewContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: StrictStr = Field(min_length=1)
    themes: list[StrictStr]
    recent_activity: list[StrictStr]
    open_issues: list[_OverviewClaim]
    key_decisions: list[_OverviewClaim]
    source_memory_ids: list[StrictStr] = Field(min_length=1)


class OverviewService:
    _schema_ready: "weakref.WeakSet" = weakref.WeakSet()

    def __init__(self, db: Any):
        self.db = db
        self.effective_read = EffectiveReadService(db)

    @staticmethod
    def _validated_content(data: Any, input_ids: set[str]) -> dict:
        try:
            content = _OverviewContent.model_validate(data)
        except ValidationError as exc:
            raise ChatProviderError("Invalid project overview response") from exc
        cited_ids = set(content.source_memory_ids)
        claim_ids = {
            claim.memory_id for claim in content.open_issues + content.key_decisions
        }
        if not cited_ids <= input_ids or not claim_ids <= cited_ids:
            raise ChatProviderError("Project overview references an unsupported source")
        return content.model_dump()

    async def _gather_reconciler_items(self, project_id: str) -> tuple[list, str, dict]:
        rows = await self.effective_read._active_results(project_id)
        items: list = []
        source_references: list = []
        result_parts: list[str] = []
        for result in rows:
            if result.get("action") in {
                "archive",
                "quarantine",
                "noise_suppression",
                "add_relation",
                "mark_stale",
            }:
                continue
            sources = await self.effective_read._source_rows(result["id"])
            if not sources:
                continue
            if not await self.effective_read.revalidate_result(
                str(result["id"]), bump_revision=False
            ):
                continue
            body = str(result.get("body") or "")
            items.append(
                {
                    "id": str(result["id"]),
                    "category": "curated",
                    "title": _first_line(body)[:80],
                    "abstract": body[:_SNIPPET_CHARS],
                    "content": body,
                    "created_at": str(result.get("created_at") or ""),
                    "representative_memory_id": result.get("representative_memory_id"),
                    "revision": int(result.get("revision") or 0),
                    "citations": [
                        {
                            "memory_id": str(source["memory_id"]),
                            "input_hash": str(source["input_hash"]),
                        }
                        for source in sources
                    ],
                }
            )
            source_references.extend(items[-1]["citations"])
            result_parts.append(
                f"{result['id']}:{result.get('revision', 0)}:"
                + ",".join(
                    f"{source['memory_id']}:{source['input_hash']}"
                    for source in sources
                )
            )
        coverage = {
            "canonical_total": 0,
            "covered_canonical": 0,
            "curated_results": len(items),
        }
        canonical_rows = await self.db.fetchall(
            "SELECT id, content_hash, updated_at FROM memories "
            "WHERE project_id = ? AND COALESCE(status, 'canonical') = 'canonical' "
            "ORDER BY id",
            (project_id,),
        )
        canonical_ids = {str(row["id"]) for row in canonical_rows}
        covered_ids = {str(ref["memory_id"]) for ref in source_references}
        coverage["canonical_total"] = len(canonical_ids)
        coverage["covered_canonical"] = len(canonical_ids & covered_ids)
        pending = await self.db.fetchone(
            "SELECT COUNT(DISTINCT c.group_key) AS count "
            "FROM reconciler_proposals p "
            "JOIN reconciler_runs r ON r.id = p.run_id "
            "JOIN reconciler_candidates c ON c.id = p.candidate_id "
            "WHERE p.project_id = ? AND r.dry_run = 0 "
            "AND p.status IN ('needs_approval', 'needs_review', 'approved', 'conflict', 'stale')",
            (project_id,),
        )
        coverage["unreviewed"] = int(pending["count"]) if pending else 0
        source_hash = hashlib.sha256(
            json.dumps(
                {
                    "results": result_parts,
                    "canonical": [
                        (row["id"], row["content_hash"], row["updated_at"])
                        for row in canonical_rows
                    ],
                    "unreviewed": coverage["unreviewed"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return (
            items,
            source_hash,
            {
                "coverage": coverage,
                "unreviewed_count": coverage["unreviewed"],
                "partial": bool(
                    coverage["covered_canonical"] < coverage["canonical_total"]
                    or coverage["unreviewed"]
                ),
                "source_references": source_references,
            },
        )

    async def _cached_dependencies_valid(
        self, project_id: str, row: Any, current_hash: str, item_count: int
    ) -> bool:
        dependencies = await self.db.fetchall(
            """
            SELECT s.result_id, s.result_revision, s.source_hash, cr.revision
            FROM project_overview_sources s
            JOIN curated_results cr ON cr.id = s.result_id
            WHERE s.project_id = ? AND cr.project_id = ? AND cr.status = 'active'
            """,
            (project_id, project_id),
        )
        if not dependencies or len(dependencies) != item_count:
            return False
        return current_hash == row["source_hash"] and all(
            int(item["result_revision"]) == int(item["revision"])
            and item["source_hash"] == row["source_hash"]
            for item in dependencies
        )

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
        items, current_hash, metadata = await self._gather_reconciler_items(project_id)
        row = await self.db.fetchone(
            "SELECT overview_json, source_hash, item_count, model, created_at "
            "FROM project_overview WHERE project_id = ?",
            (project_id,),
        )
        if not row:
            return {
                "overview": None,
                "stale": False,
                "item_count": 0,
                "model": None,
                "generated_at": None,
                "empty": True,
                **metadata,
                "unavailable": True,
            }
        dependencies_valid = await self._cached_dependencies_valid(
            project_id, row, current_hash, len(items)
        )
        if not dependencies_valid:
            return {
                "overview": None,
                "stale": True,
                "item_count": int(row["item_count"] or 0),
                "model": row["model"],
                "generated_at": row["created_at"],
                **metadata,
                "unavailable": True,
            }
        try:
            overview = self._validated_content(
                json.loads(row["overview_json"]),
                {item["id"] for item in items}
                | {source["memory_id"] for source in metadata["source_references"]},
            )
        except (json.JSONDecodeError, TypeError, ChatProviderError):
            return {
                "overview": None,
                "stale": True,
                "item_count": int(row["item_count"] or 0),
                "model": row["model"],
                "generated_at": row["created_at"],
                **metadata,
                "unavailable": True,
            }
        return {
            "overview": overview,
            "stale": False,
            "item_count": row["item_count"],
            "model": row["model"],
            "generated_at": row["created_at"],
            **metadata,
            "unavailable": False,
        }

    async def generate(
        self, *, project_id: str, chat_service: Any, settings: Any
    ) -> dict:
        """Gather recent memories, ask the chat LLM for an overview, cache it."""
        await self.ensure_schema()
        items, source_hash, metadata = await self._gather_reconciler_items(project_id)
        if not items:
            return {
                "overview": None,
                "stale": False,
                "item_count": 0,
                "empty": True,
                **metadata,
                "unavailable": True,
            }

        response = await chat_service.generate_project_overview(
            project_id=project_id, items=items, settings=settings
        )
        if not isinstance(response, dict):
            raise ChatProviderError("Invalid project overview response")
        model = str(response.get("model") or "")
        data = self._validated_content(
            {key: value for key, value in response.items() if key != "model"},
            {item["id"] for item in items}
            | {source["memory_id"] for source in metadata["source_references"]},
        )
        overview_json = json.dumps(data, ensure_ascii=False)
        now = _utc_now()
        # PRIMARY KEY(project_id) → DELETE + INSERT (no INSERT OR REPLACE churn).
        async with self.db.transaction():
            _, current_hash, _ = await self._gather_reconciler_items(project_id)
            if current_hash != source_hash:
                raise ReconcilerConflictError(
                    "Project overview inputs changed during generation; retry"
                )
            await self.db.execute(
                "DELETE FROM project_overview WHERE project_id = ?", (project_id,)
            )
            await self.db.execute(
                "INSERT INTO project_overview "
                "(project_id, overview_json, source_hash, item_count, model, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, overview_json, source_hash, len(items), model, now),
            )
            await self.db.execute(
                "DELETE FROM project_overview_sources WHERE project_id = ?",
                (project_id,),
            )
            for item in items:
                await self.db.execute(
                    "INSERT INTO project_overview_sources(project_id, result_id, result_revision, source_hash, generated_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        project_id,
                        item["id"],
                        item["revision"],
                        source_hash,
                        now,
                    ),
                )
        return {
            "overview": data,
            "stale": False,
            "item_count": len(items),
            "model": model,
            "generated_at": now,
            **metadata,
            "unavailable": False,
        }


def clamp_interval_hours(value: Any) -> int:
    """Coerce a user/config-provided interval into the supported 6–24h range."""
    try:
        hours = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_INTERVAL_HOURS
    return max(_MIN_INTERVAL_HOURS, min(_MAX_INTERVAL_HOURS, hours))


class OverviewScheduler:
    """Opt-in scheduled regeneration of project overviews.

    A project must be explicitly enabled (``overview_schedule.enabled``) to be
    swept — the dashboard toggles this per project. Each worker cycle picks at
    most ONE due project and regenerates it, so the relay worker's single-task
    pacing is preserved (no burst of LLM calls; see CLAUDE.md L1/L5).

    A project is due after its interval if canonical memory changed or a curated
    result became active since its last run. A project without a prior run needs
    recent canonical activity or an active curated result. The cache check skips
    an LLM call when the stored overview is current.

    Schema is lazy/memoized per Database instance (like OverviewService).
    """

    _schema_ready: "weakref.WeakSet" = weakref.WeakSet()

    def __init__(self, db: Any):
        self.db = db

    async def ensure_schema(self) -> None:
        if self.db in OverviewScheduler._schema_ready:
            return
        async with self.db.transaction():
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS overview_schedule (
                    project_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_run_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """)
        OverviewScheduler._schema_ready.add(self.db)

    async def set_enabled(self, project_id: str, enabled: bool) -> dict:
        """Enable/disable scheduled overview for a project (upsert)."""
        await self.ensure_schema()
        now = _utc_now()
        # PRIMARY KEY(project_id) → DELETE + INSERT is overkill; a plain upsert
        # via ON CONFLICT keeps last_run_at intact across toggles.
        await self.db.execute(
            """
            INSERT INTO overview_schedule (project_id, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (project_id, 1 if enabled else 0, now, now),
        )
        return {"project_id": project_id, "enabled": bool(enabled)}

    async def list_schedules(self) -> list[dict]:
        await self.ensure_schema()
        rows = await self.db.fetchall(
            "SELECT project_id, enabled, last_run_at FROM overview_schedule "
            "ORDER BY project_id"
        )
        return [
            {
                "project_id": str(r["project_id"]),
                "enabled": bool(r["enabled"]),
                "last_run_at": r["last_run_at"],
            }
            for r in rows
        ]

    async def _claim_due_project(self, cutoff_iso: str) -> Optional[str]:
        """Select one enabled project with input changes after its last run."""
        row = await self.db.fetchone(
            """
            SELECT s.project_id AS project_id
            FROM overview_schedule s
            WHERE s.enabled = 1
              AND (s.last_run_at IS NULL OR s.last_run_at < ?)
              AND (
                    EXISTS (
                        SELECT 1 FROM memories m
                        WHERE m.project_id = s.project_id
                          AND COALESCE(m.status, 'canonical') = 'canonical'
                          AND COALESCE(m.updated_at, m.created_at) > COALESCE(s.last_run_at, ?)
                    )
                    OR EXISTS (
                        SELECT 1 FROM curated_results cr
                        WHERE cr.project_id = s.project_id
                          AND cr.status = 'active'
                          AND (s.last_run_at IS NULL OR COALESCE(cr.activated_at, cr.created_at) > s.last_run_at)
                    )
              )
            ORDER BY s.last_run_at IS NOT NULL, s.last_run_at ASC
            LIMIT 1
            """,
            (cutoff_iso, cutoff_iso),
        )
        return str(row["project_id"]) if row else None

    async def _mark_run(self, project_id: str, now: str) -> None:
        await self.db.execute(
            "UPDATE overview_schedule SET last_run_at = ?, updated_at = ? "
            "WHERE project_id = ?",
            (now, now, project_id),
        )

    async def process_next(
        self,
        *,
        chat_service: Any,
        settings: Any,
        overview_service: Any,
        interval_hours: int = _DEFAULT_INTERVAL_HOURS,
        notifier: Any = None,
    ) -> dict:
        """Regenerate the overview of one due project, if any.

        Returns ``{"processed": False}`` when nothing is due (cheap: a couple of
        indexed reads). On a hit, advances ``last_run_at`` even when the cache
        was already fresh, so the project isn't re-examined until the next
        interval. Best-effort ``notifier.notify_overview_generated`` fires only
        when an LLM regeneration actually happened.
        """
        await self.ensure_schema()
        interval_hours = clamp_interval_hours(interval_hours)
        now_dt = datetime.now(timezone.utc)
        cutoff_iso = (now_dt - timedelta(hours=interval_hours)).isoformat()

        project_id = await self._claim_due_project(cutoff_iso)
        if project_id is None:
            return {"processed": False}

        now = now_dt.isoformat()
        try:
            cached = await overview_service.get_cached(project_id)
            if (
                cached
                and cached.get("overview") is not None
                and not cached.get("stale")
            ):
                # Already current — advance the clock, skip the LLM.
                await self._mark_run(project_id, now)
                return {
                    "processed": True,
                    "project_id": project_id,
                    "generated": False,
                    "skipped_fresh": True,
                }
            result = await overview_service.generate(
                project_id=project_id,
                chat_service=chat_service,
                settings=settings,
            )
            await self._mark_run(project_id, now)
        except Exception as exc:  # noqa: BLE001 - one project's failure is isolated
            logger.warning("Scheduled overview for %s failed: %s", project_id, exc)
            # Still advance the clock so a persistently failing project doesn't
            # monopolize every cycle; it retries next interval.
            await self._mark_run(project_id, now)
            return {"processed": False, "project_id": project_id, "error": str(exc)}

        if result.get("empty"):
            return {
                "processed": True,
                "project_id": project_id,
                "generated": False,
                "empty": True,
            }

        if notifier is not None:
            try:
                await notifier.notify_overview_generated(
                    {
                        "project_id": project_id,
                        "item_count": result.get("item_count", 0),
                        "generated_at": result.get("generated_at", now),
                    }
                )
            except Exception:  # pragma: no cover - notification is best-effort
                pass

        return {
            "processed": True,
            "project_id": project_id,
            "generated": True,
            "item_count": result.get("item_count", 0),
        }
