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
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.services.enrich_store import EnrichmentStore

logger = logging.getLogger(__name__)

_RECENT_LIMIT = 20
_SNIPPET_CHARS = 300

# Scheduled-refresh interval bounds (hours). Default is a half-day; a project's
# overview is regenerated at most once per interval, and only when the project
# saw memory activity within that same window (idle projects are skipped so we
# never burn LLM calls re-summarizing unchanged projects).
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

    "Due" means two things at once, both keyed off the same ``interval_hours``
    window ending now:

    * not run in the last interval (``last_run_at`` older than the window), and
    * memory activity within the last interval (a canonical memory whose
      created/updated time falls inside the window).

    The activity gate is what stops idle projects from being re-summarized every
    cycle forever — once a project stops receiving memories, the next sweep finds
    no in-window activity and skips it. Regeneration itself still reuses
    ``OverviewService`` staleness: if the cached overview is somehow already
    current, ``last_run_at`` is advanced without spending an LLM call.

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
        """One enabled project that is due (stale run) AND had in-window memory
        activity. Oldest-run-first so all due projects get fair rotation."""
        row = await self.db.fetchone(
            """
            SELECT s.project_id AS project_id
            FROM overview_schedule s
            WHERE s.enabled = 1
              AND (s.last_run_at IS NULL OR s.last_run_at < ?)
              AND EXISTS (
                    SELECT 1 FROM memories m
                    WHERE m.project_id = s.project_id
                      AND COALESCE(m.status, 'canonical') = 'canonical'
                      AND COALESCE(m.updated_at, m.created_at) >= ?
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
