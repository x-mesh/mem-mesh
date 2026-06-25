"""Relay worker CLI helpers."""

import asyncio
import json
import sys
import time
import uuid
from typing import Optional

from app.core.config import Settings
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.relay import RelayService
from app.core.services.relay_worker import (
    RelayWorker,
    SonnetRelayEnricher,
    build_http_outbox_sender,
)


def cmd_relay_worker(
    *,
    once: bool = False,
    json_mode: bool = False,
    tasks: str = "outbox,item,aggregate",
    interval: float = 1.0,
    worker_id: Optional[str] = None,
    verbose: bool = False,
) -> int:
    """Run the relay worker from CLI."""

    try:
        result = asyncio.run(
            _run_relay_worker(
                once=once,
                tasks=tasks,
                interval=interval,
                worker_id=worker_id or f"relay-worker-{uuid.uuid4()}",
                verbose=verbose,
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
    db = Database(settings.database_path, embedding_dim=settings.embedding_dim)
    await db.connect()
    try:
        service = RelayService(db)
        await service.ensure_schema()
        result = await service.materialize_current_memories(limit=limit)
        return result.model_dump()
    finally:
        await db.close()


async def _run_relay_worker(
    *,
    once: bool,
    tasks: str,
    interval: float,
    worker_id: str,
    verbose: bool = False,
) -> dict:
    settings = Settings()
    enabled = {task.strip() for task in tasks.split(",") if task.strip()}
    unknown = enabled - {"outbox", "item", "aggregate"}
    if unknown:
        raise ValueError(f"unknown relay worker task(s): {', '.join(sorted(unknown))}")

    db = Database(settings.database_path, embedding_dim=settings.embedding_dim)
    await db.connect()
    try:
        service = RelayService(db)
        await service.ensure_schema()
        effective = await service.get_effective_config(settings)
        relay_config = effective["values"]
        relay_sources = effective["sources"]
        needs_sonnet = bool(enabled & {"item", "aggregate"})
        text_enricher = None
        if needs_sonnet:
            if not relay_config["sonnet_api_key"]:
                raise ValueError(
                    "Relay Sonnet API key is required for item/aggregate relay tasks"
                )
            text_enricher = SonnetRelayEnricher(
                api_key=relay_config["sonnet_api_key"],
                model=relay_config["sonnet_model"],
                base_url=relay_config["sonnet_base_url"],
                timeout=settings.relay_sonnet_timeout,
            )

        embedding_service = None
        if "item" in enabled:
            embedding_service = EmbeddingService(
                model_name=settings.embedding_model,
                preload=False,
                defer_loading=False,
            )

        outbox_sender = None
        outbox_bearer_token = None
        if "outbox" in enabled:
            if not relay_config["hub_token"]:
                raise ValueError("Relay hub token is required for outbox relay task")
            outbox_sender = build_http_outbox_sender(
                timeout=settings.relay_http_timeout
            )
            outbox_bearer_token = relay_config["hub_token"]

        worker = RelayWorker(
            service=service,
            worker_id=worker_id,
            embedding_service=embedding_service,
            text_enricher=text_enricher if "item" in enabled else None,
            digest_generator=text_enricher if "aggregate" in enabled else None,
            outbox_sender=outbox_sender,
            outbox_bearer_token=outbox_bearer_token,
            prompt_version=relay_config["prompt_version"],
        )

        if once:
            debug_before = (
                await _relay_debug_snapshot(
                    db,
                    settings=settings,
                    enabled=enabled,
                    relay_config=relay_config,
                    relay_sources=relay_sources,
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
                        enabled=enabled,
                        relay_config=relay_config,
                        relay_sources=relay_sources,
                    ),
                }
            return result

        while True:
            await worker.run_once()
            await asyncio.sleep(interval)
    finally:
        await db.close()


async def _relay_debug_snapshot(
    db: Database,
    *,
    settings: Settings,
    enabled: set[str],
    relay_config: dict,
    relay_sources: dict,
) -> dict:
    now = time.time()
    snapshot = {
        "database_path": settings.database_path,
        "enabled_tasks": sorted(enabled),
        "settings": {
            "hub_url": relay_config.get("hub_url", ""),
            "source_node_id": relay_config.get("source_node_id", ""),
            "hub_token_configured": bool(relay_config.get("hub_token", "")),
            "sonnet_api_key_configured": bool(relay_config.get("sonnet_api_key", "")),
            "sonnet_model": relay_config.get("sonnet_model", ""),
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
