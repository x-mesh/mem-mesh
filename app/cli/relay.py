"""Relay worker CLI helpers."""

import asyncio
import json
import logging
import random
import sys
import time
import uuid
from typing import Optional

from app.core.config import Settings
from app.core.database.base import Database
from app.core.database.connection import is_sqlite_busy_error
from app.core.embeddings.service import EmbeddingService
from app.core.services.llm_resolver import resolve_service_llm
from app.core.services.relay import RelayService
from app.core.services.relay_worker import (
    RelayWorker,
    build_http_outbox_sender,
    build_relay_enricher,
)

logger = logging.getLogger(__name__)
_DB_BUSY_BACKOFF_MAX_SECONDS = 30.0


async def _backoff_after_db_busy(
    *, exc: BaseException, consecutive_failures: int, interval: float
) -> None:
    """Pause one daemon loop after transient SQLite contention."""

    base = max(0.05, interval)
    ceiling = min(
        _DB_BUSY_BACKOFF_MAX_SECONDS, base * (2 ** min(consecutive_failures - 1, 8))
    )
    delay = ceiling * random.uniform(0.8, 1.2)
    logger.warning(
        "relay worker database busy; retrying in %.2fs (consecutive=%d): %s",
        delay,
        consecutive_failures,
        exc,
    )
    await asyncio.sleep(delay)


async def _connect_worker_database(
    db: Database, *, once: bool, interval: float
) -> None:
    """Connect a daemon without letting startup contention terminate it."""

    consecutive_db_busy = 0
    while True:
        try:
            await db.connect()
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if once or not is_sqlite_busy_error(exc):
                raise
            consecutive_db_busy += 1
            await _backoff_after_db_busy(
                exc=exc,
                consecutive_failures=consecutive_db_busy,
                interval=interval,
            )


def cmd_relay_worker(
    *,
    once: bool = False,
    json_mode: bool = False,
    tasks: Optional[str] = None,
    interval: float = 1.0,
    worker_id: Optional[str] = None,
    max_attempts: int = 8,
    backoff_max: float = 300.0,
    lease_seconds: int = 300,
    concurrency: int = 1,
    verbose: bool = False,
    debug: bool = False,
) -> int:
    """Run the relay worker from CLI."""

    # -d → DEBUG (skip reasons, probe), -v → INFO (active tasks, activity),
    # otherwise WARNING. The startup summary is printed regardless of level.
    if not json_mode:
        level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
        logging.basicConfig(
            level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )

    try:
        result = asyncio.run(
            _run_relay_worker(
                once=once,
                tasks=tasks,
                interval=interval,
                worker_id=worker_id or f"relay-worker-{uuid.uuid4()}",
                max_attempts=max_attempts,
                backoff_max=backoff_max,
                lease_seconds=lease_seconds,
                concurrency=concurrency,
                verbose=verbose,
                debug=debug,
            )
        )
        if json_mode:
            print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        elif once:
            print(f"relay worker: {result}")
        return 0
    except Exception as exc:
        if json_mode:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"relay worker failed: {exc}", file=sys.stderr)
        return 1


def cmd_relay_materialize(*, limit: int = 1000, json_mode: bool = False) -> int:
    """Backfill relay current rows into ordinary memories from CLI."""

    try:
        result = asyncio.run(_run_relay_materialize(limit=limit))
        if json_mode:
            print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        else:
            print(f"relay materialize: {result}")
        return 0
    except Exception as exc:
        if json_mode:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"relay materialize failed: {exc}", file=sys.stderr)
        return 1


async def _run_relay_materialize(*, limit: int = 1000) -> dict:
    settings = Settings()
    db = Database(
        settings.database_path,
        busy_timeout=getattr(settings, "busy_timeout", 5000),
        embedding_dim=settings.embedding_dim,
    )
    await db.connect()
    try:
        service = RelayService(db)
        await service.ensure_schema()
        result = await service.materialize_current_memories(limit=limit)
        return result.model_dump()
    finally:
        await db.close()


_KNOWN_TASKS = {"outbox", "item", "aggregate", "reconcile", "maintenance", "overview"}
_DEFAULT_TASKS = "outbox,item,aggregate"
_DEFAULT_OVERVIEW_INTERVAL_HOURS = 12


def _parse_tasks(raw: str) -> set[str]:
    """CSV → validated task set."""
    enabled = {task.strip() for task in raw.split(",") if task.strip()}
    unknown = enabled - _KNOWN_TASKS
    if unknown:
        raise ValueError(f"unknown relay worker task(s): {', '.join(sorted(unknown))}")
    if not enabled:
        raise ValueError("at least one relay worker task must be enabled")
    return enabled


async def _resolve_enabled(db, override: Optional[set[str]]) -> set[str]:
    """Effective task set: an explicit --tasks override (fixed, for debugging),
    else the ``relay.worker_tasks`` app_config setting, else the default. The
    daemon re-resolves this each cycle so dashboard changes take effect next turn.
    """
    if override:
        return override
    raw = await db.get_app_config("relay.worker_tasks") or _DEFAULT_TASKS
    return _parse_tasks(raw)


async def _run_relay_worker(
    *,
    once: bool,
    tasks: Optional[str],
    interval: float,
    worker_id: str,
    max_attempts: int = 8,
    backoff_max: float = 300.0,
    lease_seconds: int = 300,
    concurrency: int = 1,
    verbose: bool = False,
    debug: bool = False,
) -> dict:
    # Explicit --tasks fixes the set (debug); None → dynamic from settings.
    override = _parse_tasks(tasks) if tasks else None
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if backoff_max <= 0:
        raise ValueError("backoff_max must be greater than 0")
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be at least 1")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")

    if concurrency == 1:
        return await _run_relay_worker_instance(
            once=once,
            enabled_override=override,
            interval=interval,
            worker_id=worker_id,
            max_attempts=max_attempts,
            backoff_max=backoff_max,
            lease_seconds=lease_seconds,
            concurrency=concurrency,
            verbose=verbose,
            debug=debug,
        )

    enabled = override or _parse_tasks(_DEFAULT_TASKS)
    debug_before = (
        await _relay_debug_snapshot_from_settings(
            enabled=enabled,
            worker_options=_worker_options(
                worker_id=worker_id,
                max_attempts=max_attempts,
                backoff_max=backoff_max,
                lease_seconds=lease_seconds,
                concurrency=concurrency,
            ),
        )
        if verbose and once
        else None
    )
    results = await asyncio.gather(
        *[
            _run_relay_worker_instance(
                once=once,
                enabled_override=override,
                interval=interval,
                worker_id=_worker_instance_id(worker_id, index, concurrency),
                max_attempts=max_attempts,
                backoff_max=backoff_max,
                lease_seconds=lease_seconds,
                concurrency=concurrency,
                verbose=False,
                debug=debug,
            )
            for index in range(concurrency)
        ]
    )
    combined = _combine_worker_results(results)
    if verbose and once:
        combined["debug"] = {
            "before": debug_before,
            "after": await _relay_debug_snapshot_from_settings(
                enabled=enabled,
                worker_options=_worker_options(
                    worker_id=worker_id,
                    max_attempts=max_attempts,
                    backoff_max=backoff_max,
                    lease_seconds=lease_seconds,
                    concurrency=concurrency,
                ),
            ),
        }
    return combined


async def _reconcile_on(db, settings) -> bool:
    return settings.enable_conflict_detection or str(
        await db.get_app_config("reconcile.enabled") or ""
    ).strip().lower() in ("true", "1", "yes", "on")


async def _pending_item_jobs(db) -> bool:
    """Whether any relay item job is waiting. Used to decide whether an
    LLM-less worker should load the embedding model at all."""
    try:
        row = await db.fetchone("""
            SELECT 1 FROM relay_queue_item
            WHERE status IN ('pending', 'processing')
            LIMIT 1
            """)
    except Exception:  # table absent on a node that never received relay events
        return False
    return row is not None


async def _probe_active(
    *, db, settings, service, relay_config: dict, enabled: set[str]
) -> tuple[set[str], dict]:
    """Which enabled tasks have config ready. Cheap (no model load).

    Returns (active, waiting) where ``waiting`` maps each not-yet-runnable task
    to a human reason. Missing config is not an error — the daemon waits and
    picks tasks up on a later cycle once they're configured (e.g. via the
    dashboard). Reasons are logged at DEBUG for -d.
    """
    active: set[str] = set()
    waiting: dict = {}

    if enabled & {"item", "aggregate"}:
        has_llm = bool((await resolve_service_llm(db, settings, "relay"))["api_key"])
        if "aggregate" in enabled:
            if has_llm:
                active.add("aggregate")
            else:
                waiting["aggregate"] = "no LLM (set the shared Chat LLM or relay_llm_*)"
        if "item" in enabled:
            # The item job embeds first and enriches second, so it is useful
            # without an LLM: it writes the relay vector hub search needs. Skip
            # it (and the embedding model load) only when there is nothing
            # queued and no LLM — a personal node with an empty item queue.
            if has_llm or await _pending_item_jobs(db):
                active.add("item")
            else:
                waiting["item"] = "no LLM and no queued items"

    if "outbox" in enabled:
        if relay_config.get("hub_token"):
            active.add("outbox")
        else:
            waiting["outbox"] = "no hub token (set it on the Relay page)"

    if "reconcile" in enabled:
        if not await _reconcile_on(db, settings):
            waiting["reconcile"] = "reconcile disabled (enable in Worker settings)"
        elif not (await resolve_service_llm(db, settings, "reconcile"))["api_key"]:
            waiting["reconcile"] = "no LLM (set the shared Chat LLM or reconcile_llm_*)"
        else:
            active.add("reconcile")

    if "maintenance" in enabled:
        from app.core.services.chat import ChatService

        if await ChatService(db).is_configured(settings):
            active.add("maintenance")
        else:
            waiting["maintenance"] = (
                "no chat LLM (set the Chat Assistant LLM in Settings)"
            )

    if "overview" in enabled:
        from app.core.services.chat import ChatService

        if await ChatService(db).is_configured(settings):
            active.add("overview")
        else:
            waiting["overview"] = "no chat LLM (set the Chat Assistant LLM in Settings)"

    for task in sorted(waiting):
        logger.debug("relay task '%s' waiting: %s", task, waiting[task])
    return active, waiting


async def _build_relay_worker(
    *,
    db,
    settings,
    service,
    relay_config: dict,
    active: set[str],
    worker_id: str,
    max_attempts: int,
    backoff_max: float,
    lease_seconds: int,
) -> "RelayWorker":
    """Construct a RelayWorker for the ``active`` tasks (config already verified
    by _probe_active). Never raises on missing config — probe gates that."""
    text_enricher = None
    if active & {"item", "aggregate"}:
        relay_llm = await resolve_service_llm(db, settings, "relay")
        # "item" can be active with no LLM (embedding-only mode) — building an
        # enricher without an api_key would make every enrich call fail.
        if relay_llm["api_key"]:
            logger.info(
                "relay item/aggregate LLM: %s/%s (%s)",
                relay_llm["provider"],
                relay_llm["model"],
                relay_llm["source"],
            )
            text_enricher = build_relay_enricher(
                provider=relay_llm["provider"],
                api_key=relay_llm["api_key"],
                model=relay_llm["model"],
                base_url=relay_llm["base_url"],
                timeout=settings.relay_llm_timeout,
            )
        else:
            logger.info("relay item: no LLM configured — embedding-only mode")

    embedding_service = None
    if "item" in active:
        embedding_service = EmbeddingService(
            model_name=settings.embedding_model,
            preload=False,
            defer_loading=False,
        )

    outbox_sender = None
    outbox_bearer_token = None
    if "outbox" in active:
        outbox_sender = build_http_outbox_sender(timeout=settings.relay_http_timeout)
        outbox_bearer_token = relay_config["hub_token"]

    # F2 reconcile worker. No model is loaded here any more: the NLI pre-gate
    # was replaced by an age filter, which saves ~1.6GB resident per worker.
    reconcile_service = None
    conflict_detector = None
    reconcile_enricher = None
    if "reconcile" in active:
        from app.core.services.reconcile import ReconcileService

        reconcile_service = ReconcileService(
            db,
            max_attempts=max_attempts,
            backoff_max_seconds=backoff_max,
            lease_seconds=lease_seconds,
        )
        reconcile_llm = await resolve_service_llm(db, settings, "reconcile")
        logger.info(
            "reconcile LLM: %s/%s (%s)",
            reconcile_llm["provider"],
            reconcile_llm["model"],
            reconcile_llm["source"],
        )
        reconcile_enricher = build_relay_enricher(
            provider=reconcile_llm["provider"],
            api_key=reconcile_llm["api_key"],
            model=reconcile_llm["model"],
            base_url=reconcile_llm["base_url"],
            timeout=settings.relay_llm_timeout,
        )

    # Project-level batch maintenance (enrich/improve) via the chat LLM.
    maintenance_service = None
    chat_service = None
    chat_settings = None
    if "maintenance" in active:
        from app.core.services.chat import ChatService
        from app.core.services.maintenance import MaintenanceService

        maintenance_service = MaintenanceService(
            db,
            max_attempts=max_attempts,
            backoff_max_seconds=backoff_max,
            lease_seconds=lease_seconds,
        )
        chat_service = ChatService(db)
        chat_settings = settings
        logger.info("maintenance worker: enrich/improve via chat LLM")

    # Cross-process WS notifier — overview 재생성과 maintenance enrich 완료 알림이
    # 공유한다(fire-and-forget, 웹서버가 꺼져 있으면 무해). 별도 컨테이너에서 돌 때는
    # localhost가 웹서버가 아니므로 MEM_MESH_NOTIFY_BASE_URL로 서비스 주소를 지정한다
    # (docker-compose: http://mem-mesh:8000).
    import os as _os

    from app.core.notifier import HttpNotifier

    ws_notifier = HttpNotifier(
        _os.getenv("MEM_MESH_NOTIFY_BASE_URL")
        or f"http://localhost:{getattr(settings, 'server_port', 8000)}"
    )

    # Scheduled project-overview refresh via the chat LLM. Opt-in per project
    # (overview_schedule); regenerates one due project per cycle.
    overview_scheduler = None
    overview_service = None
    overview_notifier = ws_notifier
    overview_interval_hours = _DEFAULT_OVERVIEW_INTERVAL_HOURS
    if "overview" in active:
        from app.core.services.chat import ChatService
        from app.core.services.overview import (
            OverviewScheduler,
            OverviewService,
            clamp_interval_hours,
        )

        overview_scheduler = OverviewScheduler(db)
        overview_service = OverviewService(db)
        if chat_service is None:
            chat_service = ChatService(db)
            chat_settings = settings
        overview_interval_hours = clamp_interval_hours(
            await db.get_app_config("overview.refresh_interval_hours")
            or _DEFAULT_OVERVIEW_INTERVAL_HOURS
        )
        logger.info(
            "overview worker: scheduled refresh every %sh via chat LLM",
            overview_interval_hours,
        )

    # hook_events retention prune — always wired (no LLM cost, no task opt-in):
    # the worker is the only long-lived process that can archive-then-delete
    # aged hook rows. MEM_MESH_HOOK_RETENTION_DAYS<=0 disables it.
    from app.core.services.hook import HookService

    hook_service = HookService(db)
    try:
        hook_retention_days = int(_os.getenv("MEM_MESH_HOOK_RETENTION_DAYS", "14"))
    except ValueError:
        hook_retention_days = 14
    logger.info(
        "hook prune: retention %sd (0=disabled)",
        hook_retention_days,
    )

    try:
        auto_enrich_sweep_interval_hours = int(
            _os.getenv("MEM_MESH_AUTO_ENRICH_INTERVAL_HOURS", "12")
        )
    except ValueError:
        auto_enrich_sweep_interval_hours = 12
    try:
        auto_enrich_batch_cap = int(_os.getenv("MEM_MESH_AUTO_ENRICH_BATCH_CAP", "200"))
    except ValueError:
        auto_enrich_batch_cap = 200
    try:
        auto_enrich_max_projects_per_sweep = int(
            _os.getenv("MEM_MESH_AUTO_ENRICH_MAX_PROJECTS", "20")
        )
    except ValueError:
        auto_enrich_max_projects_per_sweep = 20

    enrich_backfill_enabled = _os.getenv(
        "MEM_MESH_ENRICH_BACKFILL", ""
    ).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    try:
        enrich_backfill_cap = int(_os.getenv("MEM_MESH_ENRICH_BACKFILL_CAP", "200"))
    except ValueError:
        enrich_backfill_cap = 200

    abstract_reembed_enabled = _os.getenv(
        "MEM_MESH_ABSTRACT_REEMBED", ""
    ).strip().lower() in ("1", "true", "yes", "on")
    try:
        abstract_reembed_cap = int(_os.getenv("MEM_MESH_ABSTRACT_REEMBED_CAP", "100"))
    except ValueError:
        abstract_reembed_cap = 100

    return RelayWorker(
        service=service,
        worker_id=worker_id,
        embedding_service=embedding_service,
        text_enricher=text_enricher if "item" in active else None,
        digest_generator=text_enricher if "aggregate" in active else None,
        outbox_sender=outbox_sender,
        outbox_bearer_token=outbox_bearer_token,
        prompt_version=relay_config["prompt_version"],
        lease_seconds=lease_seconds,
        reconcile_service=reconcile_service,
        reconcile_enricher=reconcile_enricher,
        conflict_detector=conflict_detector,
        maintenance_service=maintenance_service,
        chat_service=chat_service,
        chat_settings=chat_settings,
        overview_scheduler=overview_scheduler,
        overview_service=overview_service,
        overview_notifier=overview_notifier,
        overview_interval_hours=overview_interval_hours,
        hook_service=hook_service,
        hook_retention_days=hook_retention_days,
        auto_enrich_sweep_interval_hours=auto_enrich_sweep_interval_hours,
        auto_enrich_batch_cap=auto_enrich_batch_cap,
        auto_enrich_max_projects_per_sweep=auto_enrich_max_projects_per_sweep,
        enrich_backfill_enabled=enrich_backfill_enabled,
        enrich_backfill_cap=enrich_backfill_cap,
        abstract_reembed_enabled=abstract_reembed_enabled,
        abstract_reembed_cap=abstract_reembed_cap,
        # Session digest prefetch: gated + throttled by the federated settings
        # (relay_federated_session_digest_*). Uses the outbox HTTP sender to
        # reach the hub. Enabled by default; a CPU-only node still pays only a
        # ≤3s bounded call per refresh interval per subscribed project.
        session_digest_settings=settings,
        session_digest_sender=outbox_sender
        or build_http_outbox_sender(timeout=settings.relay_http_timeout),
    )


async def _refresh_worker_config(
    *, db, settings, service, worker: "RelayWorker", active: set[str]
) -> Optional[tuple]:
    """Refresh cheap, DB-backed config on an already-built worker in place.

    LLM provider/model/key/base_url, hub token, and prompt_version are plain
    attributes RelayWorker reads fresh on every run_once() call — reassigning
    them here takes effect on the very next cycle. Unlike _build_relay_worker,
    this never touches the heavy resources (EmbeddingService, the NLI
    ConflictDetectorService) so a rotated API key or hub token doesn't force a
    model reload. Called every daemon cycle regardless of whether the active
    task set changed, so dashboard edits apply without a process restart.

    Returns a signature tuple for change-only logging, or None if worker is
    None.
    """
    eff = await service.get_effective_config(settings)
    relay_config = eff["values"]
    sig: list = []

    if active & {"item", "aggregate"}:
        relay_llm = await resolve_service_llm(db, settings, "relay")
        # No key → no enricher; "item" then runs embedding-only. An LLM added
        # later lands here on the next cycle and switches enrichment back on.
        enricher = (
            build_relay_enricher(
                provider=relay_llm["provider"],
                api_key=relay_llm["api_key"],
                model=relay_llm["model"],
                base_url=relay_llm["base_url"],
                timeout=settings.relay_llm_timeout,
            )
            if relay_llm["api_key"]
            else None
        )
        worker.text_enricher = enricher if "item" in active else None
        worker.digest_generator = enricher if "aggregate" in active else None
        sig.append(
            (
                "relay_llm",
                relay_llm["provider"],
                relay_llm["model"],
                relay_llm["api_key"],
            )
        )

    if "outbox" in active:
        worker.outbox_bearer_token = relay_config["hub_token"]
        sig.append(("hub_token", relay_config["hub_token"]))

    if "reconcile" in active:
        reconcile_llm = await resolve_service_llm(db, settings, "reconcile")
        worker.reconcile_enricher = build_relay_enricher(
            provider=reconcile_llm["provider"],
            api_key=reconcile_llm["api_key"],
            model=reconcile_llm["model"],
            base_url=reconcile_llm["base_url"],
            timeout=settings.relay_llm_timeout,
        )
        sig.append(
            (
                "reconcile_llm",
                reconcile_llm["provider"],
                reconcile_llm["model"],
                reconcile_llm["api_key"],
            )
        )

    worker.prompt_version = relay_config["prompt_version"]
    sig.append(("prompt_version", relay_config["prompt_version"]))
    return tuple(sig)


def _print_worker_state(
    *,
    worker_id: str,
    enabled: set[str],
    active: set[str],
    waiting: dict,
    interval: float,
    once: bool,
) -> None:
    """Startup / active-change summary to stderr, printed regardless of -v/-d.

    A relay worker with no config runs silently idle; this makes it always
    announce which tasks it's running and, for each idle task, why it's waiting.
    """
    lines = [f"relay worker {worker_id}" + (" (once)" if once else "")]
    lines.append(f"  requested: {','.join(sorted(enabled)) or '(none)'}")
    lines.append(
        "  active:    "
        + (",".join(sorted(active)) if active else "(none — waiting for config)")
    )
    for task in sorted(waiting):
        lines.append(f"  waiting:   {task} — {waiting[task]}")
    if not once:
        lines.append(f"  interval:  {interval}s")
    print("\n".join(lines), file=sys.stderr)


async def _run_relay_worker_instance(
    *,
    once: bool,
    enabled_override: Optional[set[str]],
    interval: float,
    worker_id: str,
    max_attempts: int,
    backoff_max: float,
    lease_seconds: int,
    concurrency: int,
    verbose: bool = False,
    debug: bool = False,
) -> dict:
    settings = Settings()

    db = Database(
        settings.database_path,
        busy_timeout=getattr(settings, "busy_timeout", 5000),
        embedding_dim=settings.embedding_dim,
    )
    await _connect_worker_database(db, once=once, interval=interval)
    try:
        service = RelayService(
            db,
            max_attempts=max_attempts,
            backoff_max_seconds=backoff_max,
        )
        await service.ensure_schema()
        effective = await service.get_effective_config(settings)
        relay_config = effective["values"]
        relay_sources = effective["sources"]

        async def _probe(enabled: set[str]) -> tuple[set[str], dict]:
            eff = await service.get_effective_config(settings)
            return await _probe_active(
                db=db,
                settings=settings,
                service=service,
                relay_config=eff["values"],
                enabled=enabled,
            )

        async def _build(active: set[str]) -> "RelayWorker":
            eff = await service.get_effective_config(settings)
            return await _build_relay_worker(
                db=db,
                settings=settings,
                service=service,
                relay_config=eff["values"],
                active=active,
                worker_id=worker_id,
                max_attempts=max_attempts,
                backoff_max=backoff_max,
                lease_seconds=lease_seconds,
            )

        if once:
            enabled = await _resolve_enabled(db, enabled_override)
            active, waiting = await _probe(enabled)
            _print_worker_state(
                worker_id=worker_id,
                enabled=enabled,
                active=active,
                waiting=waiting,
                interval=interval,
                once=True,
            )
            worker = await _build(active)
            worker_options = _worker_options(
                worker_id=worker_id,
                max_attempts=max_attempts,
                backoff_max=backoff_max,
                lease_seconds=lease_seconds,
                concurrency=concurrency,
            )
            debug_before = (
                await _relay_debug_snapshot(
                    db,
                    settings=settings,
                    enabled=active,
                    relay_config=relay_config,
                    relay_sources=relay_sources,
                    worker_options=worker_options,
                )
                if verbose
                else None
            )
            result = await worker.run_once()
            if verbose:
                result["debug"] = {
                    "before": debug_before,
                    "after": await _relay_debug_snapshot(
                        db,
                        settings=settings,
                        enabled=active,
                        relay_config=relay_config,
                        relay_sources=relay_sources,
                        worker_options=worker_options,
                    ),
                }
            return result

        # Daemon: each cycle re-resolve the requested tasks and probe which have
        # config ready. The worker itself is rebuilt only when the active task
        # set changes (avoids reloading the NLI model / embedding model), but
        # cheap config — LLM keys/model, hub token, prompt_version — is
        # refreshed in place on the existing worker every cycle, so editing
        # those in the dashboard takes effect without restarting the process.
        # If nothing is ready yet, stay up and idle — the worker picks tasks up
        # as soon as they're configured (e.g. from the dashboard).
        current: Optional[set[str]] = None
        last_signature: Optional[tuple] = None
        last_config_signature: Optional[tuple] = None
        consecutive_db_busy = 0
        needs_lease_recovery = False
        worker = None
        while True:
            try:
                if needs_lease_recovery:
                    released = await service.release_worker_leases(worker_id)
                    needs_lease_recovery = False
                    if released:
                        logger.info(
                            "relay worker released %d job lease(s) after database contention",
                            released,
                        )
                enabled = await _resolve_enabled(db, enabled_override)
                active, waiting = await _probe(enabled)
                # Rebuild only when the active set changes (avoids reloading the NLI
                # model), but reprint the summary whenever active OR waiting shifts —
                # so a config change that lands but can't activate yet (e.g. adding
                # outbox with no hub token) is still visible instead of silent.
                if active != current:
                    worker = await _build(active) if active else None
                    current = active
                signature = (frozenset(active), tuple(sorted(waiting.items())))
                if signature != last_signature:
                    _print_worker_state(
                        worker_id=worker_id,
                        enabled=enabled,
                        active=active,
                        waiting=waiting,
                        interval=interval,
                        once=False,
                    )
                    logger.info(
                        "relay worker active tasks: %s",
                        ",".join(sorted(active)) or "(none — waiting for config)",
                    )
                    last_signature = signature
                if worker is None:
                    consecutive_db_busy = 0
                    await asyncio.sleep(interval)
                    continue
                config_signature = await _refresh_worker_config(
                    db=db,
                    settings=settings,
                    service=service,
                    worker=worker,
                    active=active,
                )
                if config_signature != last_config_signature:
                    logger.info(
                        "relay worker config refreshed (key/token/model change detected)"
                    )
                    last_config_signature = config_signature
                stats = await worker.run_once()
                consecutive_db_busy = 0
                if not any(stats.values()):
                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not is_sqlite_busy_error(exc):
                    raise
                consecutive_db_busy += 1
                needs_lease_recovery = True
                await _backoff_after_db_busy(
                    exc=exc,
                    consecutive_failures=consecutive_db_busy,
                    interval=interval,
                )
    finally:
        await db.close()


def _empty_worker_result() -> dict:
    return {
        "outbox_processed": 0,
        "outbox_failed": 0,
        "item_processed": 0,
        "item_failed": 0,
        "aggregate_processed": 0,
        "aggregate_failed": 0,
        "reconcile_processed": 0,
        "reconcile_failed": 0,
        "maintenance_processed": 0,
        "maintenance_failed": 0,
    }


def _combine_worker_results(results: list[dict]) -> dict:
    combined = _empty_worker_result()
    for result in results:
        for key in combined:
            combined[key] += int(result.get(key, 0) or 0)
    return combined


def _worker_instance_id(worker_id: str, index: int, concurrency: int) -> str:
    if concurrency == 1:
        return worker_id
    return f"{worker_id}-{index + 1}"


def _worker_options(
    *,
    worker_id: str,
    max_attempts: int,
    backoff_max: float,
    lease_seconds: int,
    concurrency: int,
) -> dict:
    return {
        "worker_id": worker_id,
        "max_attempts": max_attempts,
        "backoff_max": backoff_max,
        "lease_seconds": lease_seconds,
        "concurrency": concurrency,
    }


async def _relay_debug_snapshot_from_settings(
    *,
    enabled: set[str],
    worker_options: dict,
) -> dict:
    settings = Settings()
    db = Database(
        settings.database_path,
        busy_timeout=getattr(settings, "busy_timeout", 5000),
        embedding_dim=settings.embedding_dim,
    )
    await db.connect()
    try:
        service = RelayService(
            db,
            max_attempts=worker_options["max_attempts"],
            backoff_max_seconds=worker_options["backoff_max"],
        )
        await service.ensure_schema()
        effective = await service.get_effective_config(settings)
        return await _relay_debug_snapshot(
            db,
            settings=settings,
            enabled=enabled,
            relay_config=effective["values"],
            relay_sources=effective["sources"],
            worker_options=worker_options,
        )
    finally:
        await db.close()


async def _relay_debug_snapshot(
    db: Database,
    *,
    settings: Settings,
    enabled: set[str],
    relay_config: dict,
    relay_sources: dict,
    worker_options: Optional[dict] = None,
) -> dict:
    now = time.time()
    snapshot = {
        "database_path": settings.database_path,
        "enabled_tasks": sorted(enabled),
        "worker": worker_options or {},
        "settings": {
            "hub_url": relay_config.get("hub_url", ""),
            "source_node_id": relay_config.get("source_node_id", ""),
            "hub_token_configured": bool(relay_config.get("hub_token", "")),
            "llm_provider": relay_config.get("llm_provider", ""),
            "llm_api_key_configured": bool(relay_config.get("llm_api_key", "")),
            "llm_model": relay_config.get("llm_model", ""),
            "prompt_version": relay_config.get("prompt_version", ""),
            "sources": relay_sources,
        },
        "queues": {},
        "hints": [],
    }

    if "outbox" in enabled:
        snapshot["queues"]["outbox"] = await _debug_queue_table(
            db,
            table="relay_outbox",
            now=now,
            id_columns=["id", "idempotency_key", "target_hub"],
            empty_hint=(
                "relay_outbox has no rows. Queue a memory from /relay "
                "Operations -> Share Memory before running the outbox worker."
            ),
        )
    else:
        snapshot["hints"].append("outbox task is disabled")

    if "item" in enabled:
        snapshot["queues"]["item"] = await _debug_queue_table(
            db,
            table="relay_queue_item",
            now=now,
            id_columns=["id", "ref_id", "raw_event_id"],
            empty_hint=(
                "relay_queue_item has no rows. Ingest a relay event on the hub "
                "before running item processing."
            ),
        )
    else:
        snapshot["hints"].append("item task is disabled")

    if "aggregate" in enabled:
        snapshot["queues"]["aggregate"] = await _debug_queue_table(
            db,
            table="relay_queue_aggregate",
            now=now,
            id_columns=["id", "ref_id", "coalesce_key"],
            empty_hint=(
                "relay_queue_aggregate has no rows. Run item processing first "
                "so project digest work is coalesced."
            ),
        )
    else:
        snapshot["hints"].append("aggregate task is disabled")

    return snapshot


async def _debug_queue_table(
    db: Database,
    *,
    table: str,
    now: float,
    id_columns: list[str],
    empty_hint: str,
) -> dict:
    rows = await db.fetchall(f"""
        SELECT status, COUNT(*) AS count
        FROM {table}
        GROUP BY status
        ORDER BY status
        """)
    counts = {str(row["status"]): int(row["count"]) for row in rows}
    total = sum(counts.values())

    due = await _count_where(
        db,
        table,
        "status = 'pending' AND next_attempt_at <= ?",
        (now,),
    )
    future = await _count_where(
        db,
        table,
        "status = 'pending' AND next_attempt_at > ?",
        (now,),
    )
    processing = await _count_where(db, table, "status = 'processing'")
    failed = await _count_where(
        db,
        table,
        "status IN ('failed', 'dead_letter')",
    )
    next_due = await db.fetchone(f"""
        SELECT next_attempt_at
        FROM {table}
        WHERE status = 'pending'
        ORDER BY next_attempt_at
        LIMIT 1
        """)

    select_columns = ", ".join(
        [*id_columns, "status", "attempts", "next_attempt_at", "last_error"]
    )
    sample_rows = await db.fetchall(f"""
        SELECT {select_columns}
        FROM {table}
        WHERE status IN ('pending', 'processing', 'failed', 'dead_letter')
        ORDER BY created_at
        LIMIT 5
        """)

    reason = None
    if total == 0:
        reason = empty_hint
    elif due == 0 and future > 0:
        reason = "pending rows exist, but none are due yet because next_attempt_at is in the future"
    elif due == 0 and processing > 0:
        reason = "rows are currently marked processing; wait for lease expiry or inspect locked worker"
    elif due == 0 and failed > 0:
        reason = "rows are failed/dead_letter; inspect last_error before retrying"
    elif due == 0:
        reason = "no due pending rows match the worker claim query"

    return {
        "counts": counts,
        "total": total,
        "due_pending": due,
        "future_pending": future,
        "processing": processing,
        "failed_or_dead_letter": failed,
        "next_pending_attempt_at": (
            float(next_due["next_attempt_at"]) if next_due else None
        ),
        "sample": [_row_to_dict(row) for row in sample_rows],
        "no_work_reason": reason,
    }


async def _count_where(
    db: Database,
    table: str,
    where: str,
    params: tuple = (),
) -> int:
    row = await db.fetchone(
        f"SELECT COUNT(*) AS count FROM {table} WHERE {where}",
        params,
    )
    return int(row["count"] or 0) if row else 0


def _row_to_dict(row) -> dict:
    return {key: row[key] for key in row.keys()}
