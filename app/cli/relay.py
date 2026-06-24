"""Relay worker CLI helpers."""

import asyncio
import json
import sys
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
) -> int:
    """Run the relay worker from CLI."""

    try:
        result = asyncio.run(
            _run_relay_worker(
                once=once,
                tasks=tasks,
                interval=interval,
                worker_id=worker_id or f"relay-worker-{uuid.uuid4()}",
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


async def _run_relay_worker(
    *,
    once: bool,
    tasks: str,
    interval: float,
    worker_id: str,
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
        needs_sonnet = bool(enabled & {"item", "aggregate"})
        text_enricher = None
        if needs_sonnet:
            if not settings.relay_sonnet_api_key:
                raise ValueError(
                    "MEM_MESH_RELAY_SONNET_API_KEY is required for item/aggregate relay tasks"
                )
            text_enricher = SonnetRelayEnricher(
                api_key=settings.relay_sonnet_api_key,
                model=settings.relay_sonnet_model,
                base_url=settings.relay_sonnet_base_url,
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
            if not settings.relay_hub_token:
                raise ValueError("MEM_MESH_RELAY_HUB_TOKEN is required for outbox relay task")
            outbox_sender = build_http_outbox_sender(timeout=settings.relay_http_timeout)
            outbox_bearer_token = settings.relay_hub_token

        worker = RelayWorker(
            service=service,
            worker_id=worker_id,
            embedding_service=embedding_service,
            text_enricher=text_enricher if "item" in enabled else None,
            digest_generator=text_enricher if "aggregate" in enabled else None,
            outbox_sender=outbox_sender,
            outbox_bearer_token=outbox_bearer_token,
            prompt_version=settings.relay_prompt_version,
        )

        if once:
            return await worker.run_once()

        while True:
            await worker.run_once()
            await asyncio.sleep(interval)
    finally:
        await db.close()
