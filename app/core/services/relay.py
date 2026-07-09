"""Core service for the mem-mesh relay layer.

The relay service intentionally keeps ingest deterministic: it authenticates,
validates, appends a raw event, updates the current projection, and enqueues
post-processing work. LLM and embedding calls happen only in worker methods.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import random
import secrets
import time
import uuid
import weakref
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence, Union

from ..database.base import Database
from ..database.models import Memory
from ..errors import (
    RelayDeliveryConflict,
)
from ..errors import RelayError as RelayError
from ..errors import (
    RelayIdempotencyConflict,
    RelayInviteInvalid,
    RelaySecretBlocked,
    RelayTypeGateBlocked,
    RelayUnauthorized,
)
from ..redaction import redact_secrets
from ..schemas.relay import (
    RelayAdminOverviewResponse,
    RelayAggregateJob,
    RelayAutoShareSubscription,
    RelayCategoryPolicy,
    RelayDeadLetterSummary,
    RelayDigestData,
    RelayDigestSummary,
    RelayEnrichmentData,
    RelayHubCheckResponse,
    RelayIdentitySummary,
    RelayIdentityUpdateRequest,
    RelayIngestRequest,
    RelayIngestResponse,
    RelayInviteCreateRequest,
    RelayInviteSummary,
    RelayMaterializeResponse,
    RelayMemorySummary,
    RelayOutboxJob,
    RelayOutboxSummary,
    RelayPairRequest,
    RelayPairResponse,
    RelayProcessResult,
    RelayProjectDigestResponse,
    RelayPurgeResponse,
    RelayQueueJob,
    RelayQueueSummary,
    RelayRetryResponse,
    RelaySearchRequest,
    RelaySearchResponse,
    RelaySearchResult,
    RelaySettingsResponse,
    RelaySettingsUpdateRequest,
    RelaySettingValue,
    RelayShareProjectResponse,
    RelayStatusCount,
)
from .enrich_store import EnrichmentStore

logger = logging.getLogger(__name__)


class RelayHTTPClient:
    """Small S2S HTTP sender for relay outbox delivery."""

    def __init__(self, *, http_client: Any = None, timeout: float = 10.0):
        self.http_client = http_client
        self.timeout = timeout

    async def send_ingest(
        self,
        *,
        target_hub: str,
        bearer_token: str,
        payload: RelayIngestRequest,
    ) -> RelayIngestResponse:
        client = self.http_client
        close_client = False
        if client is None:
            import httpx

            client = httpx.AsyncClient()
            close_client = True

        try:
            response = await client.post(
                self._ingest_url(target_hub),
                headers={"Authorization": f"Bearer {bearer_token}"},
                json=payload.model_dump(mode="json"),
                timeout=self.timeout,
            )
        finally:
            if close_client:
                await client.aclose()

        if response.status_code == 409:
            raise RelayDeliveryConflict(self._response_detail(response))
        if response.status_code == 401 or response.status_code == 403:
            raise RelayUnauthorized(self._response_detail(response))
        if response.status_code >= 400:
            raise RuntimeError(self._response_detail(response))
        return RelayIngestResponse(**response.json())

    async def send_search(
        self,
        *,
        target_hub: str,
        bearer_token: str,
        payload: RelaySearchRequest,
        timeout: Optional[float] = None,
    ) -> RelaySearchResponse:
        """Query the hub's relay search endpoint (federated read path)."""
        client = self.http_client
        close_client = False
        if client is None:
            import httpx

            client = httpx.AsyncClient()
            close_client = True

        try:
            response = await client.post(
                self._search_url(target_hub),
                headers={"Authorization": f"Bearer {bearer_token}"},
                json=payload.model_dump(mode="json"),
                timeout=timeout if timeout is not None else self.timeout,
            )
        finally:
            if close_client:
                await client.aclose()

        if response.status_code == 401 or response.status_code == 403:
            raise RelayUnauthorized(self._response_detail(response))
        if response.status_code >= 400:
            raise RuntimeError(self._response_detail(response))
        return RelaySearchResponse(**response.json())

    @staticmethod
    def _search_url(target_hub: str) -> str:
        base = target_hub.rstrip("/")
        if base.endswith("/api/relay/v1/search"):
            return base
        for suffix in ("/api/relay/v1/health", "/api/relay/v1/ingest", "/api/relay/v1"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        return f"{base}/api/relay/v1/search"

    @staticmethod
    def _ingest_url(target_hub: str) -> str:
        base = target_hub.rstrip("/")
        if base.endswith("/api/relay/v1/ingest"):
            return base
        return f"{base}/api/relay/v1/ingest"

    @staticmethod
    def health_url(target_hub: str) -> str:
        base = target_hub.rstrip("/")
        if base.endswith("/api/relay/v1/health"):
            return base
        if base.endswith("/api/relay/v1"):
            return f"{base}/health"
        return f"{base}/api/relay/v1/health"

    @staticmethod
    def auth_check_url(target_hub: str) -> str:
        base = target_hub.rstrip("/")
        if base.endswith("/api/relay/v1/auth/check"):
            return base
        for suffix in ("/api/relay/v1/health", "/api/relay/v1/ingest", "/api/relay/v1"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        return f"{base}/api/relay/v1/auth/check"

    @staticmethod
    def pair_url(target_hub: str) -> str:
        base = target_hub.rstrip("/")
        if base.endswith("/api/relay/v1/pair"):
            return base
        for suffix in ("/api/relay/v1/health", "/api/relay/v1/ingest", "/api/relay/v1"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        return f"{base}/api/relay/v1/pair"

    async def send_pair(
        self,
        *,
        target_hub: str,
        payload: RelayPairRequest,
        timeout: Optional[float] = None,
    ) -> RelayPairResponse:
        """Redeem a pairing invite against the hub (no bearer — the code is
        the credential)."""
        client = self.http_client
        close_client = False
        if client is None:
            import httpx

            client = httpx.AsyncClient()
            close_client = True

        try:
            response = await client.post(
                self.pair_url(target_hub),
                json=payload.model_dump(mode="json"),
                timeout=timeout if timeout is not None else self.timeout,
            )
        finally:
            if close_client:
                await client.aclose()

        if response.status_code in (404, 405):
            raise RelayInviteInvalid(
                "hub does not support invite pairing (update the hub)"
            )
        if response.status_code in (400, 401, 403, 409):
            raise RelayInviteInvalid(self._response_detail(response))
        if response.status_code >= 400:
            raise RuntimeError(self._response_detail(response))
        return RelayPairResponse(**response.json())

    @staticmethod
    def _response_detail(response: Any) -> str:
        try:
            data = response.json()
            if isinstance(data, dict) and data.get("detail"):
                return str(data["detail"])
        except Exception:
            pass
        return str(getattr(response, "text", "")) or f"HTTP {response.status_code}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _epoch_now() -> float:
    return time.time()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _embed_hub_url_in_code(base: str, hub_url: str) -> str:
    """Suffix a pairing code with its hub URL so a node can self-configure from
    the code alone.

    Format: ``<secret>.<b64url(hub_url)>``. The whole string is the opaque
    credential the hub hash-stores and compares; only the redeeming client
    decodes the suffix to auto-fill its Team Hub URL. An empty ``hub_url``
    yields a legacy bare code (older codes have no ``.`` suffix — still valid).
    """
    url = (hub_url or "").strip().rstrip("/")
    if not url:
        return base
    suffix = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{base}.{suffix}"


class RelayService:
    """SQLite-backed relay ingest and worker service."""

    CONFIG_KEYS = {
        "hub_url": "relay.hub_url",
        "source_node_id": "relay.source_node_id",
        "default_source_version": "relay.default_source_version",
        "hub_token": "relay.hub_token",
        "llm_provider": "relay.llm_provider",
        "llm_api_key": "relay.llm_api_key",
        "llm_model": "relay.llm_model",
        "llm_base_url": "relay.llm_base_url",
        "prompt_version": "relay.prompt_version",
        "blocked_categories": "relay.blocked_categories",
        "public_url": "relay.public_url",
    }
    SETTING_FIELDS = {
        "hub_url": ("relay_hub_url", "MEM_MESH_RELAY_HUB_URL"),
        # This hub's own public URL (IP or domain), embedded into pairing codes
        # so a redeeming node auto-fills its Team Hub URL. Shared global setting.
        "public_url": ("public_url", "MEM_MESH_PUBLIC_URL"),
        "source_node_id": ("relay_source_node_id", "MEM_MESH_RELAY_SOURCE_NODE_ID"),
        "hub_token": ("relay_hub_token", "MEM_MESH_RELAY_HUB_TOKEN"),
        "llm_provider": ("relay_llm_provider", "MEM_MESH_RELAY_LLM_PROVIDER"),
        "llm_api_key": ("relay_llm_api_key", "MEM_MESH_RELAY_LLM_API_KEY"),
        "llm_model": ("relay_llm_model", "MEM_MESH_RELAY_LLM_MODEL"),
        "llm_base_url": (
            "relay_llm_base_url",
            "MEM_MESH_RELAY_LLM_BASE_URL",
        ),
        "prompt_version": ("relay_prompt_version", "MEM_MESH_RELAY_PROMPT_VERSION"),
    }
    # Structurally excluded from sharing, no matter what — not a user policy
    # choice. 'task' is the default bucket for pin promotions / ad-hoc local
    # work-tracking (see CLAUDE.md M3), never team knowledge. Everything else
    # is shareable by default (fail-open) so newly introduced categories don't
    # silently become unshareable until code catches up; blocked_categories
    # (below) lets users opt individual categories back out.
    DENYLISTED_KINDS = {"task"}

    # Databases whose relay schema has already been created this process. The
    # DDL is CREATE ... IF NOT EXISTS (idempotent), so once a connection has run
    # it there is no need to re-issue ~20 statements on every request / delete.
    # Keyed weakly per Database instance so fresh connections (e.g. per-test
    # temp DBs) still run it and closed ones drop out automatically.
    _schema_ready: "weakref.WeakSet" = weakref.WeakSet()

    def __init__(
        self,
        db: Database,
        *,
        max_attempts: int = 8,
        backoff_max_seconds: float = 300.0,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if backoff_max_seconds <= 0:
            raise ValueError("backoff_max_seconds must be greater than 0")
        self.db = db
        self.max_attempts = max_attempts
        self.backoff_max_seconds = backoff_max_seconds

    def _retry_backoff_seconds(self, attempts: int) -> float:
        # Downward jitter (PRD FR-23): desynchronizes retries across queued rows
        # after a hub outage without ever exceeding the exponential base/cap.
        base = min(
            self.backoff_max_seconds,
            float(2 ** max(attempts - 1, 0)),
        )
        return base * random.uniform(0.5, 1.0)

    async def ensure_schema(self) -> None:
        """Create relay tables and indexes if they do not exist.

        Memoized per Database instance: the first call on a connection issues the
        DDL, later calls are a no-op, so per-request / per-delete relay access
        does not repeat ~20 CREATE IF NOT EXISTS statements.
        """

        if self.db in RelayService._schema_ready:
            return

        statements = [
            """
            CREATE TABLE IF NOT EXISTS relay_outbox (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                payload_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                target_hub TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL DEFAULT 0,
                locked_by TEXT,
                locked_at REAL,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS relay_identity (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                source_node_id TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                home_domain TEXT,
                scopes_json TEXT NOT NULL DEFAULT '["read","write"]',
                revoked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS relay_project (
                team_project_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                description TEXT,
                created_by_user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS relay_project_mapping (
                id TEXT PRIMARY KEY,
                source_node_id TEXT NOT NULL,
                source_project_key TEXT NOT NULL,
                team_project_id TEXT NOT NULL,
                share_policy_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(source_node_id, source_project_key)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS relay_raw_event (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                payload_hash TEXT NOT NULL,
                event_type TEXT NOT NULL,
                source_node_id TEXT NOT NULL,
                source_user_id TEXT NOT NULL,
                source_memory_id TEXT NOT NULL,
                source_version INTEGER NOT NULL,
                source_project_key TEXT NOT NULL,
                team_project_id TEXT NOT NULL,
                authoritative_kind TEXT NOT NULL,
                authoritative_status TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                server_provenance_json TEXT NOT NULL,
                applied_to_current INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS relay_memory_current (
                id TEXT PRIMARY KEY,
                source_node_id TEXT NOT NULL,
                source_memory_id TEXT NOT NULL,
                source_version INTEGER NOT NULL,
                latest_event_id TEXT NOT NULL,
                team_project_id TEXT NOT NULL,
                source_project_key TEXT NOT NULL,
                authoritative_kind TEXT NOT NULL,
                authoritative_status TEXT NOT NULL,
                content TEXT,
                content_hash TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                links_json TEXT NOT NULL DEFAULT '[]',
                visible INTEGER NOT NULL DEFAULT 1,
                tombstoned_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(source_node_id, source_memory_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS relay_queue_item (
                id TEXT PRIMARY KEY,
                ref_id TEXT NOT NULL,
                raw_event_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL DEFAULT 0,
                locked_by TEXT,
                locked_at REAL,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS relay_queue_aggregate (
                id TEXT PRIMARY KEY,
                ref_id TEXT NOT NULL,
                raw_event_id TEXT,
                coalesce_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL DEFAULT 0,
                locked_by TEXT,
                locked_at REAL,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS relay_item_enrichment (
                id TEXT PRIMARY KEY,
                current_memory_id TEXT NOT NULL,
                raw_event_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                embedding_dim INTEGER NOT NULL,
                title TEXT,
                abstract TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                display_kind TEXT,
                problem TEXT,
                resolution TEXT,
                lesson TEXT,
                model TEXT NOT NULL,
                model_version TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                generated_at TEXT NOT NULL,
                UNIQUE(
                    current_memory_id,
                    content_hash,
                    model_version,
                    prompt_version
                )
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS relay_project_digest (
                id TEXT PRIMARY KEY,
                team_project_id TEXT NOT NULL,
                rollup_json TEXT NOT NULL DEFAULT '{}',
                contributors_json TEXT NOT NULL DEFAULT '[]',
                recent_activity_json TEXT NOT NULL DEFAULT '[]',
                narrative TEXT,
                source_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                model TEXT NOT NULL,
                model_version TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                stale INTEGER NOT NULL DEFAULT 0,
                UNIQUE(team_project_id, model_version, prompt_version)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS relay_auto_share_subscription (
                project_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                include_relay_origin INTEGER NOT NULL DEFAULT 0,
                target_hub TEXT,
                source_node_id TEXT,
                last_synced_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS relay_invite (
                code_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                source_node_id TEXT,
                home_domain TEXT,
                scopes_json TEXT NOT NULL DEFAULT '["read","write"]',
                expires_at TEXT NOT NULL,
                redeemed_at TEXT,
                redeemed_source_node_id TEXT,
                revoked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_relay_outbox_claim
            ON relay_outbox(status, next_attempt_at, created_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_relay_raw_source
            ON relay_raw_event(source_node_id, source_memory_id, source_version)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_relay_current_project_visible
            ON relay_memory_current(team_project_id, visible, updated_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_relay_queue_item_claim
            ON relay_queue_item(status, next_attempt_at, created_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_relay_queue_aggregate_claim
            ON relay_queue_aggregate(status, next_attempt_at, created_at)
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_relay_aggregate_pending
            ON relay_queue_aggregate(coalesce_key)
            WHERE status = 'pending'
            """,
        ]

        async with self.db.transaction():
            for statement in statements:
                await self.db.execute(statement)
            await self._ensure_vector_schema()

        RelayService._schema_ready.add(self.db)

    async def get_admin_overview(
        self, *, limit: int = 10
    ) -> RelayAdminOverviewResponse:
        """Return relay operational status for the dashboard admin page."""

        limit = max(1, min(limit, 50))

        async def status_counts(table_name: str) -> list[RelayStatusCount]:
            rows = await self.db.fetchall(f"""
                SELECT status, COUNT(*) AS count
                FROM {table_name}
                GROUP BY status
                ORDER BY status
                """)
            return [
                RelayStatusCount(status=str(row["status"]), count=int(row["count"]))
                for row in rows
            ]

        async def scalar_count(query: str) -> int:
            row = await self.db.fetchone(query)
            return int(row["count"] or 0) if row else 0

        outbox_rows = await self.db.fetchall(
            """
            SELECT
                id, idempotency_key, target_hub, status, attempts,
                next_attempt_at, last_error, created_at, updated_at
            FROM relay_outbox
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        item_rows = await self.db.fetchall(
            """
            SELECT
                'item' AS queue, id, ref_id, raw_event_id, status, attempts,
                next_attempt_at, last_error, created_at, updated_at
            FROM relay_queue_item
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        aggregate_rows = await self.db.fetchall(
            """
            SELECT
                'aggregate' AS queue, id, ref_id, raw_event_id, status, attempts,
                next_attempt_at, last_error, created_at, updated_at
            FROM relay_queue_aggregate
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        dead_outbox_rows = await self.db.fetchall(
            """
            SELECT
                'outbox' AS queue, id, NULL AS ref_id, NULL AS raw_event_id,
                idempotency_key, target_hub, attempts, next_attempt_at,
                last_error, created_at, updated_at
            FROM relay_outbox
            WHERE status = 'dead_letter'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        dead_item_rows = await self.db.fetchall(
            """
            SELECT
                'item' AS queue, id, ref_id, raw_event_id,
                NULL AS idempotency_key, NULL AS target_hub,
                attempts, next_attempt_at, last_error, created_at, updated_at
            FROM relay_queue_item
            WHERE status = 'dead_letter'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        dead_aggregate_rows = await self.db.fetchall(
            """
            SELECT
                'aggregate' AS queue, id, ref_id, raw_event_id,
                NULL AS idempotency_key, NULL AS target_hub,
                attempts, next_attempt_at, last_error, created_at, updated_at
            FROM relay_queue_aggregate
            WHERE status = 'dead_letter'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        digest_rows = await self.db.fetchall(
            """
            SELECT
                team_project_id, narrative, source_memory_ids_json,
                model_version, prompt_version, generated_at, stale
            FROM relay_project_digest
            ORDER BY generated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        memory_rows = await self.db.fetchall(
            """
            SELECT
                c.id,
                c.source_node_id,
                c.source_memory_id,
                c.source_project_key,
                c.team_project_id,
                c.source_version,
                c.authoritative_kind,
                c.authoritative_status,
                c.content,
                c.tags_json,
                c.visible,
                c.updated_at,
                e.title,
                e.abstract
            FROM relay_memory_current c
            LEFT JOIN relay_item_enrichment e
              ON e.current_memory_id = c.id
             AND e.content_hash = c.content_hash
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )

        queue_rows = sorted(
            [*item_rows, *aggregate_rows],
            key=lambda row: str(row["created_at"]),
            reverse=True,
        )[:limit]
        dead_letter_rows = sorted(
            [*dead_outbox_rows, *dead_item_rows, *dead_aggregate_rows],
            key=lambda row: str(row["updated_at"]),
            reverse=True,
        )[:limit]

        return RelayAdminOverviewResponse(
            generated_at=_utc_now(),
            outbox_counts=await status_counts("relay_outbox"),
            item_queue_counts=await status_counts("relay_queue_item"),
            aggregate_queue_counts=await status_counts("relay_queue_aggregate"),
            raw_events=await scalar_count(
                "SELECT COUNT(*) AS count FROM relay_raw_event"
            ),
            visible_memories=await scalar_count(
                "SELECT COUNT(*) AS count FROM relay_memory_current WHERE visible = 1"
            ),
            enriched_items=await scalar_count(
                "SELECT COUNT(*) AS count FROM relay_item_enrichment"
            ),
            projects=await scalar_count("SELECT COUNT(*) AS count FROM relay_project"),
            recent_outbox=[
                RelayOutboxSummary(
                    id=str(row["id"]),
                    idempotency_key=str(row["idempotency_key"]),
                    target_hub=str(row["target_hub"]),
                    status=str(row["status"]),
                    attempts=int(row["attempts"]),
                    next_attempt_at=float(row["next_attempt_at"] or 0),
                    last_error=row["last_error"],
                    created_at=str(row["created_at"]),
                    updated_at=str(row["updated_at"]),
                )
                for row in outbox_rows
            ],
            recent_queue=[
                RelayQueueSummary(
                    id=str(row["id"]),
                    queue=row["queue"],
                    ref_id=str(row["ref_id"]),
                    raw_event_id=row["raw_event_id"],
                    status=str(row["status"]),
                    attempts=int(row["attempts"]),
                    next_attempt_at=float(row["next_attempt_at"] or 0),
                    last_error=row["last_error"],
                    created_at=str(row["created_at"]),
                    updated_at=str(row["updated_at"]),
                )
                for row in queue_rows
            ],
            dead_letters=[
                RelayDeadLetterSummary(
                    id=str(row["id"]),
                    queue=row["queue"],
                    ref_id=row["ref_id"],
                    raw_event_id=row["raw_event_id"],
                    idempotency_key=row["idempotency_key"],
                    target_hub=row["target_hub"],
                    attempts=int(row["attempts"]),
                    next_attempt_at=float(row["next_attempt_at"] or 0),
                    last_error=row["last_error"],
                    created_at=str(row["created_at"]),
                    updated_at=str(row["updated_at"]),
                )
                for row in dead_letter_rows
            ],
            recent_digests=[
                RelayDigestSummary(
                    team_project_id=str(row["team_project_id"]),
                    narrative=str(row["narrative"] or ""),
                    source_memory_count=len(
                        _json_loads(row["source_memory_ids_json"], [])
                    ),
                    model_version=str(row["model_version"]),
                    prompt_version=str(row["prompt_version"]),
                    generated_at=str(row["generated_at"]),
                    stale=bool(row["stale"]),
                )
                for row in digest_rows
            ],
            recent_memories=[
                RelayMemorySummary(
                    id=str(row["id"]),
                    source_node_id=str(row["source_node_id"]),
                    source_memory_id=str(row["source_memory_id"]),
                    source_project_key=str(row["source_project_key"]),
                    team_project_id=str(row["team_project_id"]),
                    source_version=int(row["source_version"]),
                    kind=str(row["authoritative_kind"]),
                    status=str(row["authoritative_status"]),
                    visible=bool(row["visible"]),
                    content_preview=str(row["content"] or "")[:240],
                    title=row["title"],
                    abstract=row["abstract"],
                    tags=_json_loads(row["tags_json"], []),
                    updated_at=str(row["updated_at"]),
                    enriched=bool(row["title"] or row["abstract"]),
                )
                for row in memory_rows
            ],
        )

    async def get_relay_notification_snapshot(
        self, current_memory_id: str
    ) -> Dict[str, Any]:
        """Return relay/current + materialized memory data for realtime events."""

        relay_row = await self.db.fetchone(
            """
            SELECT
                id, source_node_id, source_memory_id, source_project_key,
                team_project_id, source_version, authoritative_kind,
                authoritative_status, content, tags_json, visible, updated_at
            FROM relay_memory_current
            WHERE id = ?
            """,
            (current_memory_id,),
        )
        memory_id = self._materialized_memory_id(current_memory_id)
        memory_row = await self.db.fetchone(
            """
            SELECT
                id, content, project_id, category, tags, source, client,
                created_at, updated_at
            FROM memories
            WHERE id = ?
            """,
            (memory_id,),
        )

        relay_memory = None
        if relay_row:
            relay_memory = {
                "id": str(relay_row["id"]),
                "source_node_id": str(relay_row["source_node_id"]),
                "source_memory_id": str(relay_row["source_memory_id"]),
                "source_project_key": str(relay_row["source_project_key"]),
                "team_project_id": str(relay_row["team_project_id"]),
                "source_version": int(relay_row["source_version"]),
                "kind": str(relay_row["authoritative_kind"]),
                "status": str(relay_row["authoritative_status"]),
                "visible": bool(relay_row["visible"]),
                "content_preview": str(relay_row["content"] or "")[:240],
                "tags": _json_loads(relay_row["tags_json"], []),
                "updated_at": str(relay_row["updated_at"]),
            }

        memory = None
        if memory_row:
            memory = {
                "id": str(memory_row["id"]),
                "content": str(memory_row["content"] or ""),
                "project_id": str(memory_row["project_id"] or ""),
                "category": str(memory_row["category"] or ""),
                "tags": _json_loads(memory_row["tags"], []),
                "source": str(memory_row["source"] or ""),
                "client": memory_row["client"],
                "created_at": str(memory_row["created_at"]),
                "updated_at": str(memory_row["updated_at"]),
            }

        return {
            "current_memory_id": current_memory_id,
            "materialized_memory_id": memory_id,
            "relay_memory": relay_memory,
            "memory": memory,
        }

    async def materialize_current_memories(
        self, *, limit: int = 1000
    ) -> RelayMaterializeResponse:
        """Backfill relay current projection into ordinary memories."""

        limit = max(1, min(limit, 10000))
        materialized = 0
        deleted = 0
        skipped = 0
        now = _utc_now()

        async with self.db.transaction():
            rows = await self.db.fetchall(
                """
                SELECT
                    id, source_node_id, source_project_key, authoritative_kind,
                    content_hash, content, tags_json, visible
                FROM relay_memory_current
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )

            for row in rows:
                current_memory_id = str(row["id"])
                visible = bool(row["visible"])
                content = row["content"]
                if visible and content:
                    await self._sync_materialized_memory_locked(
                        current_memory_id=current_memory_id,
                        source_node_id=str(row["source_node_id"]),
                        kind=str(row["authoritative_kind"]),
                        tags=_json_loads(row["tags_json"], []),
                        source_project_key=str(row["source_project_key"]),
                        content_hash=str(row["content_hash"]),
                        content=str(content),
                        visible=True,
                        now=now,
                    )
                    materialized += 1
                else:
                    await self._delete_materialized_memory_locked(
                        self._materialized_memory_id(current_memory_id)
                    )
                    deleted += 1

        return RelayMaterializeResponse(
            scanned=len(rows),
            materialized=materialized,
            deleted=deleted,
            skipped=skipped,
        )

    async def delete_materialized_memory(self, materialized_memory_id: str) -> bool:
        """Hide relay current and delete the ordinary memory projection.

        A relay materialized memory is derived from ``relay_memory_current``.
        Deleting only ``memories`` lets the next materialize/replay pass recreate
        it, so UI deletion must tombstone the current projection as well.
        """

        if not materialized_memory_id.startswith("relay:"):
            return False

        current_memory_id = materialized_memory_id.removeprefix("relay:")
        if not current_memory_id:
            return False

        now = _utc_now()
        async with self.db.transaction():
            current = await self.db.fetchone(
                "SELECT id FROM relay_memory_current WHERE id = ?",
                (current_memory_id,),
            )
            if not current:
                return False

            await self.db.execute(
                """
                UPDATE relay_memory_current
                SET visible = 0,
                    authoritative_status = 'deleted',
                    tombstoned_at = COALESCE(tombstoned_at, ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (now, now, current_memory_id),
            )
            await self._delete_materialized_memory_locked(materialized_memory_id)
            await self.db.execute(
                """
                UPDATE relay_queue_item
                SET status = 'done',
                    locked_by = NULL,
                    locked_at = NULL,
                    last_error = NULL,
                    updated_at = ?
                WHERE ref_id = ?
                  AND status IN ('pending', 'processing')
                """,
                (now, current_memory_id),
            )

        return True

    async def purge_current_memories(self, *, limit: int = 10000) -> RelayPurgeResponse:
        """Hide visible relay current rows and remove materialized projections.

        This is an operator reset for the team hub after ordinary memories were
        manually deleted. Raw relay events stay append-only; the visible current
        projection is tombstoned so future materialize runs do not recreate rows.
        """

        limit = max(1, min(limit, 100000))
        now = _utc_now()
        materialized_deleted = 0

        async with self.db.transaction():
            rows = await self.db.fetchall(
                """
                SELECT id
                FROM relay_memory_current
                WHERE visible = 1
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            current_ids = [str(row["id"]) for row in rows]
            if not current_ids:
                return RelayPurgeResponse()

            placeholders = ",".join("?" for _ in current_ids)
            memory_ids = [self._materialized_memory_id(id_) for id_ in current_ids]
            memory_placeholders = ",".join("?" for _ in memory_ids)
            existing_materialized = await self.db.fetchone(
                f"""
                SELECT COUNT(*) AS count
                FROM memories
                WHERE id IN ({memory_placeholders})
                """,
                tuple(memory_ids),
            )
            materialized_deleted = (
                int(existing_materialized["count"]) if existing_materialized else 0
            )

            await self.db.execute(
                f"""
                UPDATE relay_memory_current
                SET visible = 0,
                    authoritative_status = 'deleted',
                    tombstoned_at = COALESCE(tombstoned_at, ?),
                    updated_at = ?
                WHERE id IN ({placeholders})
                """,
                tuple([now, now, *current_ids]),
            )
            # Resolve the vector write tables once: within this transaction the
            # schema is constant, so calling _memory_vector_write_tables_locked()
            # per row only repeats the sqlite_master / migration metadata queries.
            # Vec rows are removed per id (sqlite-vec), then the materialized
            # memories are deleted in a single batched IN (same id list used for
            # the COUNT above).
            vector_tables = await self._memory_vector_write_tables_locked()
            for memory_id in memory_ids:
                for table in vector_tables:
                    await self.db.execute(
                        f"DELETE FROM {table} WHERE memory_id = ?",
                        (memory_id,),
                    )
            await self.db.execute(
                f"DELETE FROM memories WHERE id IN ({memory_placeholders})",
                tuple(memory_ids),
            )
            await self.db.execute(
                f"""
                UPDATE relay_queue_item
                SET status = 'done',
                    locked_by = NULL,
                    locked_at = NULL,
                    last_error = NULL,
                    updated_at = ?
                WHERE ref_id IN ({placeholders})
                  AND status IN ('pending', 'processing')
                """,
                tuple([now, *current_ids]),
            )

        return RelayPurgeResponse(
            scanned=len(current_ids),
            purged=len(current_ids),
            materialized_deleted=materialized_deleted,
        )

    async def retry_dead_letters(
        self,
        *,
        queue: str = "all",
        job_id: Optional[str] = None,
        limit: int = 1000,
    ) -> RelayRetryResponse:
        """Move dead-lettered relay jobs back to pending for another attempt."""

        queue = queue or "all"
        if queue not in {"all", "outbox", "item", "aggregate"}:
            raise ValueError("queue must be one of all, outbox, item, aggregate")
        limit = max(1, min(limit, 100000))
        now_iso = _utc_now()
        now_epoch = _epoch_now()

        async def retry_table(table_name: str) -> int:
            params: list[Any] = []
            where = "status = 'dead_letter'"
            if job_id:
                where += " AND id = ?"
                params.append(job_id)
            rows = await self.db.fetchall(
                f"""
                SELECT id
                FROM {table_name}
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple([*params, limit]),
            )
            ids = [str(row["id"]) for row in rows]
            if not ids:
                return 0
            placeholders = ",".join("?" for _ in ids)
            await self.db.execute(
                f"""
                UPDATE {table_name}
                SET status = 'pending',
                    attempts = 0,
                    next_attempt_at = ?,
                    locked_by = NULL,
                    locked_at = NULL,
                    last_error = NULL,
                    updated_at = ?
                WHERE id IN ({placeholders})
                """,
                tuple([now_epoch, now_iso, *ids]),
            )
            return len(ids)

        counts = {"outbox": 0, "item": 0, "aggregate": 0}
        async with self.db.transaction():
            if queue in {"all", "outbox"}:
                counts["outbox"] = await retry_table("relay_outbox")
            if queue in {"all", "item"}:
                counts["item"] = await retry_table("relay_queue_item")
            if queue in {"all", "aggregate"}:
                counts["aggregate"] = await retry_table("relay_queue_aggregate")

        return RelayRetryResponse(
            retried=sum(counts.values()),
            outbox=counts["outbox"],
            item=counts["item"],
            aggregate=counts["aggregate"],
        )

    async def _get_blocked_categories(self) -> set[str]:
        raw = await self.db.get_app_config(self.CONFIG_KEYS["blocked_categories"]) or ""
        return {c.strip() for c in raw.split(",") if c.strip()}

    async def list_category_policies(self) -> list[RelayCategoryPolicy]:
        """Sharing policy per category actually present in this node's memories.

        The list is derived from live data, not a hardcoded enum, so a newly
        introduced category shows up here automatically (default: shared)
        instead of needing a code change to become toggleable.
        """
        rows = await self.db.fetchall(
            "SELECT DISTINCT category FROM memories "
            "WHERE category IS NOT NULL AND category != ''"
        )
        blocked = await self._get_blocked_categories()
        categories = sorted(
            {str(row["category"]) for row in rows} - self.DENYLISTED_KINDS
        )
        return [
            RelayCategoryPolicy(category=c, shared=c not in blocked) for c in categories
        ]

    async def get_admin_settings(self, settings: Any) -> RelaySettingsResponse:
        """Return relay settings and identity registry state for the dashboard."""

        default_source_version = await self.get_default_source_version()

        return RelaySettingsResponse(
            generated_at=_utc_now(),
            hub_url=await self._db_backed_setting(
                key="hub_url",
                label="Team hub URL",
                settings=settings,
            ),
            source_node_id=await self._db_backed_setting(
                key="source_node_id",
                label="Source node ID",
                settings=settings,
            ),
            default_source_version=default_source_version,
            hub_token=await self._db_backed_setting(
                key="hub_token",
                label="Hub bearer token",
                settings=settings,
                secret=True,
            ),
            llm_provider=await self._db_backed_setting(
                key="llm_provider",
                label="LLM provider",
                settings=settings,
            ),
            llm_api_key=await self._db_backed_setting(
                key="llm_api_key",
                label="LLM API key",
                settings=settings,
                secret=True,
            ),
            llm_model=await self._db_backed_setting(
                key="llm_model",
                label="LLM model",
                settings=settings,
            ),
            llm_base_url=await self._db_backed_setting(
                key="llm_base_url",
                label="LLM endpoint",
                settings=settings,
            ),
            prompt_version=await self._db_backed_setting(
                key="prompt_version",
                label="Prompt version",
                settings=settings,
            ),
            public_url=await self._db_backed_setting(
                key="public_url",
                label="Hub public URL",
                settings=settings,
            ),
            identities=await self.list_identities(),
            category_policies=await self.list_category_policies(),
        )

    async def update_admin_settings(
        self, request: RelaySettingsUpdateRequest
    ) -> RelaySettingsResponse:
        """Persist dashboard-managed relay defaults."""

        for key in (
            "hub_url",
            "source_node_id",
            "hub_token",
            "llm_provider",
            "llm_api_key",
            "llm_model",
            "llm_base_url",
            "prompt_version",
            "public_url",
        ):
            value = getattr(request, key)
            if value is None:
                continue
            cleaned = str(value).strip()
            if cleaned:
                await self.db.set_app_config(self.CONFIG_KEYS[key], cleaned)
            else:
                await self.db.delete_app_config(self.CONFIG_KEYS[key])

        if request.default_source_version is not None:
            await self.db.set_app_config(
                self.CONFIG_KEYS["default_source_version"],
                str(request.default_source_version),
            )

        if request.blocked_categories is not None:
            cleaned_categories = sorted(
                {c.strip() for c in request.blocked_categories if c.strip()}
                - self.DENYLISTED_KINDS  # denylist isn't a policy toggle; ignore
            )
            if cleaned_categories:
                await self.db.set_app_config(
                    self.CONFIG_KEYS["blocked_categories"], ",".join(cleaned_categories)
                )
            else:
                await self.db.delete_app_config(self.CONFIG_KEYS["blocked_categories"])

        from ..config import get_settings

        return await self.get_admin_settings(get_settings())

    async def get_default_source_version(self) -> int:
        version_value = await self.db.get_app_config(
            self.CONFIG_KEYS["default_source_version"]
        )
        try:
            return int(version_value) if version_value else 1
        except ValueError:
            return 1

    async def get_effective_config(self, settings: Any) -> dict[str, Any]:
        values = {}
        sources = {}
        for key in self.SETTING_FIELDS:
            value, source = await self._effective_setting_value(key, settings)
            values[key] = value
            sources[key] = source
        values["default_source_version"] = await self.get_default_source_version()
        sources["default_source_version"] = (
            "db"
            if await self.db.get_app_config(self.CONFIG_KEYS["default_source_version"])
            is not None
            else "default"
        )
        return {"values": values, "sources": sources}

    async def check_hub(
        self,
        hub_url: str,
        *,
        token: Optional[str] = None,
        timeout: float = 5.0,
        http_client: Any = None,
    ) -> RelayHubCheckResponse:
        cleaned = str(hub_url or "").strip()
        health_url = RelayHTTPClient.health_url(cleaned)
        tok = str(token or "").strip()
        client = http_client
        close_client = False
        if client is None:
            import httpx

            client = httpx.AsyncClient()
            close_client = True

        try:
            response = await client.get(health_url, timeout=timeout)
            status_code = int(getattr(response, "status_code", 0) or 0)
            data = {}
            try:
                data = response.json()
            except Exception:
                data = {}
            ok = status_code < 400 and bool(data.get("ok", True))
            relay = data.get("relay") if isinstance(data, dict) else None
            message = (
                "hub reachable" if ok else RelayHTTPClient._response_detail(response)
            )
            auth = await self._probe_hub_token(client, cleaned, tok, timeout=timeout)
            return RelayHubCheckResponse(
                ok=ok,
                hub_url=cleaned,
                health_url=health_url,
                status_code=status_code,
                relay=relay,
                message=message,
                **auth,
            )
        except Exception as exc:
            return RelayHubCheckResponse(
                ok=False,
                hub_url=cleaned,
                health_url=health_url,
                status_code=None,
                relay=None,
                message=str(exc),
            )
        finally:
            if close_client:
                await client.aclose()

    @staticmethod
    async def _probe_hub_token(
        client: Any, hub_url: str, token: str, *, timeout: float
    ) -> Dict[str, Any]:
        """Verify a relay token against the hub's /auth/check endpoint.

        Returns the token-related fields for RelayHubCheckResponse. Degrades
        gracefully: an older hub without /auth/check (404/405) reports
        token_ok=None rather than a false failure.
        """
        result: Dict[str, Any] = {
            "token_checked": False,
            "token_ok": None,
            "token_message": "",
            "node_id": None,
            "scopes": [],
        }
        if not token:
            result["token_message"] = "no token provided"
            return result

        result["token_checked"] = True
        auth_url = RelayHTTPClient.auth_check_url(hub_url)
        try:
            resp = await client.get(
                auth_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
            )
        except Exception as exc:
            result["token_ok"] = None
            result["token_message"] = f"token check error: {exc}"
            return result

        code = int(getattr(resp, "status_code", 0) or 0)
        if code == 200:
            body = {}
            try:
                body = resp.json()
            except Exception:
                body = {}
            result["token_ok"] = True
            result["token_message"] = "token valid"
            result["node_id"] = body.get("node_id")
            result["scopes"] = list(body.get("scopes") or [])
        elif code == 401:
            result["token_ok"] = False
            result["token_message"] = RelayService._auth_error_detail(resp)
        elif code in (404, 405):
            result["token_ok"] = None
            result["token_message"] = (
                "hub does not expose token check (update the hub to verify tokens)"
            )
        else:
            result["token_ok"] = False
            result["token_message"] = RelayService._auth_error_detail(resp)
        return result

    @staticmethod
    def _auth_error_detail(response: Any) -> str:
        """Human message from a relay error body ({error,message,details}) or
        FastAPI's {detail}, falling back to raw text / status code."""
        try:
            data = response.json()
            if isinstance(data, dict):
                for key in ("message", "detail"):
                    if data.get(key):
                        return str(data[key])
        except Exception:
            pass
        text = str(getattr(response, "text", "") or "")
        return text or f"HTTP {getattr(response, 'status_code', '')}".strip()

    async def list_identities(self) -> list[RelayIdentitySummary]:
        rows = await self.db.fetchall("""
            SELECT
                token_hash, user_id, source_node_id, display_name,
                home_domain, scopes_json, revoked, created_at, updated_at
            FROM relay_identity
            ORDER BY updated_at DESC
            """)
        return [self._identity_from_row(row) for row in rows]

    async def get_identity(self, token_hash: str) -> Optional[RelayIdentitySummary]:
        row = await self.db.fetchone(
            """
            SELECT
                token_hash, user_id, source_node_id, display_name,
                home_domain, scopes_json, revoked, created_at, updated_at
            FROM relay_identity
            WHERE token_hash = ?
            """,
            (token_hash,),
        )
        return self._identity_from_row(row) if row else None

    async def update_identity(
        self,
        token_hash_prefix: str,
        request: RelayIdentityUpdateRequest,
    ) -> Optional[RelayIdentitySummary]:
        row = await self._identity_row_by_prefix(token_hash_prefix)
        if not row:
            return None

        user_id = request.user_id or str(row["user_id"])
        source_node_id = request.source_node_id or str(row["source_node_id"])
        display_name = request.display_name or str(row["display_name"])
        home_domain = (
            request.home_domain
            if request.home_domain is not None
            else row["home_domain"]
        )
        scopes = (
            request.scopes
            if request.scopes is not None
            else _json_loads(row["scopes_json"], [])
        )
        revoked = bool(row["revoked"]) if request.revoked is None else request.revoked

        await self.db.execute(
            """
            UPDATE relay_identity
            SET user_id = ?,
                source_node_id = ?,
                display_name = ?,
                home_domain = ?,
                scopes_json = ?,
                revoked = ?,
                updated_at = ?
            WHERE token_hash = ?
            """,
            (
                user_id,
                source_node_id,
                display_name,
                home_domain,
                _json_dumps(scopes),
                1 if revoked else 0,
                _utc_now(),
                row["token_hash"],
            ),
        )
        return await self.get_identity(row["token_hash"])

    async def rotate_identity(
        self, token_hash_prefix: str, *, new_token: Optional[str] = None
    ) -> Optional[tuple[RelayIdentitySummary, str, bool]]:
        """Replace an identity's token in place, keeping its metadata.

        Generates a new token (or uses ``new_token``), then atomically drops the
        old ``token_hash`` and re-registers the same user/node/display/scopes
        under the new token. The old token stops authenticating immediately.
        Returns (summary, token, generated) or None if the prefix is unknown.
        Raises ValueError if the prefix is ambiguous.
        """
        row = await self._identity_row_by_prefix(token_hash_prefix)
        if not row:
            return None
        generated = new_token is None
        token = new_token or secrets.token_urlsafe(32)
        scopes = _json_loads(row["scopes_json"], [])
        async with self.db.transaction():
            await self.db.execute(
                "DELETE FROM relay_identity WHERE token_hash = ?",
                (row["token_hash"],),
            )
            new_hash = await self.register_identity(
                token=token,
                user_id=str(row["user_id"]),
                source_node_id=str(row["source_node_id"]),
                display_name=str(row["display_name"]),
                home_domain=row["home_domain"],
                scopes=scopes,
            )
        summary = await self.get_identity(new_hash)
        if summary is None:
            return None
        return summary, token, generated

    async def delete_identity(self, token_hash_prefix: str) -> bool:
        """Permanently remove a hub identity by its visible token hash prefix.

        Returns True if a row was removed. Unlike ``revoked`` (a reversible soft
        disable via update_identity), this drops the credential from the
        registry entirely. Raises ValueError if the prefix is ambiguous.
        """
        row = await self._identity_row_by_prefix(token_hash_prefix)
        if not row:
            return False
        await self.db.execute(
            "DELETE FROM relay_identity WHERE token_hash = ?",
            (row["token_hash"],),
        )
        return True

    async def register_identity(
        self,
        *,
        token: str,
        user_id: str,
        source_node_id: str,
        display_name: str,
        home_domain: Optional[str] = None,
        scopes: Optional[Sequence[str]] = None,
    ) -> str:
        """Register or update one relay bearer token."""

        token_hash = self._hash_token(token)
        now = _utc_now()
        scopes_json = _json_dumps(list(scopes or ["read", "write"]))

        async with self.db.transaction():
            existing = await self.db.fetchone(
                "SELECT token_hash FROM relay_identity WHERE token_hash = ?",
                (token_hash,),
            )
            if existing:
                await self.db.execute(
                    """
                    UPDATE relay_identity
                    SET user_id = ?,
                        source_node_id = ?,
                        display_name = ?,
                        home_domain = ?,
                        scopes_json = ?,
                        revoked = 0,
                        updated_at = ?
                    WHERE token_hash = ?
                    """,
                    (
                        user_id,
                        source_node_id,
                        display_name,
                        home_domain,
                        scopes_json,
                        now,
                        token_hash,
                    ),
                )
            else:
                await self.db.execute(
                    """
                    INSERT INTO relay_identity (
                        token_hash, user_id, source_node_id, display_name,
                        home_domain, scopes_json, revoked, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        token_hash,
                        user_id,
                        source_node_id,
                        display_name,
                        home_domain,
                        scopes_json,
                        now,
                        now,
                    ),
                )
        return token_hash

    # ------------------------------------------------------------------
    # Pairing invites — one-time codes a hub admin issues so a new node can
    # self-configure (redeem code → identity registered → token returned)
    # instead of copying a manually registered token out-of-band.
    # ------------------------------------------------------------------

    async def create_invite(
        self, request: RelayInviteCreateRequest, hub_url: str = ""
    ) -> tuple[RelayInviteSummary, str]:
        """Issue a one-time pairing invite. Returns (summary, code).

        Only the code hash is stored; the code itself is shown once. When
        ``hub_url`` is given it is embedded into the shown code so the redeeming
        node can auto-fill its Team Hub URL from the code alone (the hub still
        hash-stores and compares the whole opaque code).
        """
        code = _embed_hub_url_in_code(secrets.token_urlsafe(24), hub_url)
        code_hash = self._hash_token(code)
        now = _utc_now()
        expires_at = datetime.fromtimestamp(
            _epoch_now() + request.expires_in_seconds, tz=timezone.utc
        ).isoformat()
        await self.db.execute(
            """
            INSERT INTO relay_invite (
                code_hash, user_id, display_name, source_node_id, home_domain,
                scopes_json, expires_at, revoked, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                code_hash,
                request.user_id,
                request.display_name,
                request.source_node_id,
                request.home_domain,
                _json_dumps(list(request.scopes)),
                expires_at,
                now,
                now,
            ),
        )
        summary = await self._invite_by_hash(code_hash)
        if summary is None:
            raise RuntimeError("created relay invite could not be loaded")
        return summary, code

    async def list_invites(self) -> list[RelayInviteSummary]:
        rows = await self.db.fetchall(
            "SELECT * FROM relay_invite ORDER BY created_at DESC"
        )
        return [self._invite_from_row(row) for row in rows]

    async def delete_invite(self, code_prefix: str) -> bool:
        """Remove an invite by its visible code hash prefix (revoke = delete;
        a pending invite has no dependent state). Raises ValueError when the
        prefix is ambiguous."""
        prefix = str(code_prefix or "").strip()
        if not prefix:
            return False
        rows = await self.db.fetchall(
            "SELECT code_hash FROM relay_invite WHERE code_hash LIKE ? LIMIT 2",
            (f"{prefix}%",),
        )
        if len(rows) > 1:
            raise ValueError("relay invite code prefix is ambiguous")
        if not rows:
            return False
        await self.db.execute(
            "DELETE FROM relay_invite WHERE code_hash = ?",
            (rows[0]["code_hash"],),
        )
        return True

    async def redeem_invite(self, request: RelayPairRequest) -> RelayPairResponse:
        """Exchange a one-time invite code for a registered identity + token.

        The code is the credential: unknown, expired, revoked, or already
        redeemed codes all fail with RelayInviteInvalid (uniform message so the
        endpoint doesn't leak which invites exist).
        """
        code_hash = self._hash_token(request.code)
        now = _utc_now()

        async with self.db.transaction():
            row = await self.db.fetchone(
                "SELECT * FROM relay_invite WHERE code_hash = ?", (code_hash,)
            )
            if (
                row is None
                or bool(row["revoked"])
                or row["redeemed_at"] is not None
                or str(row["expires_at"]) <= now
            ):
                raise RelayInviteInvalid(
                    "invite code is invalid, expired, or already used"
                )

            source_node_id = str(
                row["source_node_id"] or request.source_node_id or ""
            ).strip()
            if not source_node_id:
                raise RelayInviteInvalid(
                    "invite has no pinned source node id — provide source_node_id"
                )
            taken = await self.db.fetchone(
                "SELECT token_hash FROM relay_identity WHERE source_node_id = ?",
                (source_node_id,),
            )
            if taken:
                raise RelayInviteInvalid(
                    f"source node id '{source_node_id}' is already registered"
                )

            display_name = str(request.display_name or "").strip() or str(
                row["display_name"]
            )
            scopes = _json_loads(row["scopes_json"], ["read", "write"])
            token = secrets.token_urlsafe(32)
            await self.register_identity(
                token=token,
                user_id=str(row["user_id"]),
                source_node_id=source_node_id,
                display_name=display_name,
                home_domain=row["home_domain"],
                scopes=scopes,
            )
            await self.db.execute(
                """
                UPDATE relay_invite
                SET redeemed_at = ?, redeemed_source_node_id = ?, updated_at = ?
                WHERE code_hash = ?
                """,
                (now, source_node_id, now, code_hash),
            )

        return RelayPairResponse(
            ok=True,
            token=token,
            user_id=str(row["user_id"]),
            source_node_id=source_node_id,
            display_name=display_name,
            scopes=list(scopes),
        )

    async def _invite_by_hash(self, code_hash: str) -> Optional[RelayInviteSummary]:
        row = await self.db.fetchone(
            "SELECT * FROM relay_invite WHERE code_hash = ?", (code_hash,)
        )
        return self._invite_from_row(row) if row else None

    @staticmethod
    def _invite_from_row(row: Any) -> RelayInviteSummary:
        return RelayInviteSummary(
            code_prefix=str(row["code_hash"])[:12],
            user_id=str(row["user_id"]),
            display_name=str(row["display_name"]),
            source_node_id=row["source_node_id"],
            home_domain=row["home_domain"],
            scopes=_json_loads(row["scopes_json"], []),
            expires_at=str(row["expires_at"]),
            redeemed_at=row["redeemed_at"],
            redeemed_source_node_id=row["redeemed_source_node_id"],
            revoked=bool(row["revoked"]),
            created_at=str(row["created_at"]),
        )

    async def enqueue_memory_share(
        self,
        memory: Any,
        *,
        source_node_id: str,
        source_version: Optional[int] = None,
        target_hub: str,
        event_type: str = "update",
        status: str = "active",
        allowed_kinds: Optional[Sequence[str]] = None,
        force: bool = False,
    ) -> str:
        """Build and enqueue a relay outbox event from an existing memory.

        ``source_version`` defaults to the memory's own updated_at-derived
        version (same as auto-share) when not given explicitly, so a manual
        re-share after a content edit gets a fresh idempotency_key instead of
        reusing a stale one and colliding on the hub (RelayIdempotencyConflict:
        "different payload hash"). Pass an explicit value only to pin a
        specific version.

        If the memory has local enrichment (the dashboard "Enrich" button,
        stored separately in EnrichmentStore/memory_enrichment — never part of
        Memory.content), its title/abstract/display_kind ride along in the
        payload so the hub shows them without running its own LLM enrichment.
        Enriching without touching content doesn't bump Memory.updated_at, so
        the auto-derived version also considers the enrichment's own
        timestamp — otherwise a content-unchanged re-share after enriching
        would reuse the same idempotency_key with a now-different payload hash
        and hit the exact conflict this auto-versioning was built to avoid.
        """
        source_memory_id = str(getattr(memory, "id"))
        enrichment = await EnrichmentStore(self.db).get(source_memory_id)

        if source_version is None:
            source_version = self._auto_share_version(memory)
            if enrichment and enrichment.get("created_at"):
                source_version = max(
                    source_version,
                    self._version_from_timestamp(enrichment["created_at"]),
                )

        kind = str(getattr(memory, "category", "") or "")
        if kind in self.DENYLISTED_KINDS:
            raise RelayTypeGateBlocked(
                f"'{kind}' memories are never team-shareable (local work-tracking "
                "only). If this was miscategorized, edit its category first."
            )
        if allowed_kinds is not None:
            if kind not in set(allowed_kinds):
                raise RelayTypeGateBlocked(f"memory kind is not team-shareable: {kind}")
        else:
            blocked = await self._get_blocked_categories()
            if kind in blocked:
                raise RelayTypeGateBlocked(
                    f"'{kind}' sharing is disabled — enable it in "
                    "Personal Node > Sharing Policy."
                )

        content = str(getattr(memory, "content", "") or "")
        if redact_secrets(content) != content:
            raise RelaySecretBlocked("relay payload contains a high-confidence secret")

        title = str(enrichment.get("title") or "") if enrichment else ""
        abstract = str(enrichment.get("abstract") or "") if enrichment else ""
        display_kind = str(enrichment.get("display_kind") or "") if enrichment else ""
        if title and redact_secrets(title) != title:
            raise RelaySecretBlocked("relay payload contains a high-confidence secret")
        if abstract and redact_secrets(abstract) != abstract:
            raise RelaySecretBlocked("relay payload contains a high-confidence secret")

        project_key = str(getattr(memory, "project_id", "") or "default")
        tags = self._memory_tags(memory)
        payload_hash = self._hash_payload(
            {
                "event_type": event_type,
                "source_memory_id": source_memory_id,
                "source_version": source_version,
                "source_project_key": project_key,
                "kind": kind,
                "status": status,
                "content": content,
                "tags": tags,
                "title": title,
                "abstract": abstract,
                "display_kind": display_kind,
            }
        )
        request = RelayIngestRequest(
            idempotency_key=(
                f"{source_node_id}:{source_memory_id}:v{source_version}:{event_type}"
            ),
            payload_hash=payload_hash,
            event_type=event_type,  # type: ignore[arg-type]
            source_memory_id=source_memory_id,
            source_version=source_version,
            source_project_key=project_key,
            kind=kind,  # type: ignore[arg-type]
            status=status,
            content=None if event_type == "retract" else content,
            tags=tags,
            links=[],
            title=None if event_type == "retract" else (title or None),
            abstract=None if event_type == "retract" else (abstract or None),
            display_kind=None if event_type == "retract" else (display_kind or None),
            created_at=getattr(memory, "created_at", None),
            updated_at=getattr(memory, "updated_at", None),
        )
        return await self.enqueue_outbox(
            payload=request,
            target_hub=target_hub,
            force=force,
        )

    async def enqueue_memory_share_by_id(
        self,
        memory_id: str,
        *,
        source_node_id: str,
        source_version: Optional[int] = None,
        target_hub: str,
        event_type: str = "update",
        status: str = "active",
        force: bool = False,
    ) -> str:
        row = await self.db.fetchone(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        )
        if not row:
            raise KeyError(f"memory not found: {memory_id}")
        return await self.enqueue_memory_share(
            Memory(**dict(row)),
            source_node_id=source_node_id,
            source_version=source_version,
            target_hub=target_hub,
            event_type=event_type,
            status=status,
            force=force,
        )

    # ── Auto-share (continuous project sharing) ─────────────────────────────

    @staticmethod
    def _is_relay_origin(memory: Any) -> bool:
        """Whether a memory was received via relay (must not be re-shared by
        default). Mirrors the dashboard isRelayMemory() id/source/client checks;
        tags are intentionally excluded (a user-applied 'relay' tag is not proof
        of relay origin)."""
        memory_id = str(getattr(memory, "id", "") or "")
        source = str(getattr(memory, "source", "") or "")
        client = str(getattr(memory, "client", "") or "")
        return (
            memory_id.startswith("relay:")
            or source == "relay"
            or client.startswith("relay:")
        )

    @staticmethod
    def _version_from_timestamp(stamp: str) -> int:
        """ISO timestamp -> epoch seconds, for deriving a monotonic
        source_version from whichever thing changed (content or enrichment)."""
        try:
            normalized = str(stamp or "").replace("Z", "+00:00")
            return int(datetime.fromisoformat(normalized).timestamp())
        except ValueError:
            return int(_epoch_now())

    @staticmethod
    def _auto_share_version(memory: Any) -> int:
        """Monotonic source_version for an auto-shared event. Derived from the
        memory's updated_at epoch so each create/update produces a distinct
        idempotency_key (``…:v{version}:{event}``) instead of deduping."""
        return RelayService._version_from_timestamp(getattr(memory, "updated_at", ""))

    async def _auto_share_row(self, project_id: str) -> Optional[dict]:
        """Fetch the auto-share subscription row, tolerant of a relay schema
        that was never created (relay unused → no table → treat as no sub)."""
        try:
            row = await self.db.fetchone(
                "SELECT * FROM relay_auto_share_subscription WHERE project_id = ?",
                (project_id,),
            )
        except Exception:
            return None
        return dict(row) if row else None

    def _auto_share_from_row(self, row: dict) -> RelayAutoShareSubscription:
        return RelayAutoShareSubscription(
            project_id=str(row["project_id"]),
            enabled=bool(row["enabled"]),
            include_relay_origin=bool(row["include_relay_origin"]),
            target_hub=row.get("target_hub"),
            source_node_id=row.get("source_node_id"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            last_synced_at=row.get("last_synced_at"),
            last_error=row.get("last_error"),
        )

    async def get_project_auto_share(
        self, project_id: str
    ) -> Optional[RelayAutoShareSubscription]:
        row = await self._auto_share_row(project_id)
        return self._auto_share_from_row(row) if row else None

    async def list_auto_share_subscriptions(
        self,
    ) -> list[RelayAutoShareSubscription]:
        try:
            rows = await self.db.fetchall(
                "SELECT * FROM relay_auto_share_subscription ORDER BY project_id"
            )
        except Exception:
            return []
        return [self._auto_share_from_row(dict(row)) for row in rows]

    async def set_project_auto_share(
        self,
        project_id: str,
        *,
        enabled: bool,
        include_relay_origin: bool,
        settings: Any,
    ) -> RelayAutoShareSubscription:
        """Enable or disable continuous relay sharing for a project.

        Snapshots the effective hub/node into the subscription each time it is
        (re)enabled, so the auto-share target is pinned at toggle time rather
        than read live on every memory write. Re-toggling refreshes the
        snapshot to the current effective config."""

        await self.ensure_schema()
        effective = await self.get_effective_config(settings)
        values = effective.get("values", {})
        now = _utc_now()
        existing = await self._auto_share_row(project_id)
        created_at = existing["created_at"] if existing else now
        # Refresh the hub/node snapshot whenever (re)enabling.
        target_hub = values.get("hub_url")
        source_node_id = values.get("source_node_id")
        await self.db.execute(
            """
            INSERT INTO relay_auto_share_subscription (
                project_id, enabled, include_relay_origin, target_hub,
                source_node_id, last_synced_at, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                enabled = excluded.enabled,
                include_relay_origin = excluded.include_relay_origin,
                target_hub = excluded.target_hub,
                source_node_id = excluded.source_node_id,
                updated_at = excluded.updated_at
            """,
            (
                project_id,
                1 if enabled else 0,
                1 if include_relay_origin else 0,
                target_hub,
                source_node_id,
                created_at,
                now,
            ),
        )
        logger.info(
            "Relay auto-share %s for project=%s",
            "enabled" if enabled else "disabled",
            project_id,
        )
        row = await self._auto_share_row(project_id)
        return (
            self._auto_share_from_row(row)
            if row
            else RelayAutoShareSubscription(project_id=project_id, enabled=enabled)
        )

    async def auto_share_on_write(
        self, memory: Any, *, event_type: str
    ) -> Optional[str]:
        """Best-effort hook: if the memory's project has an active auto-share
        subscription, queue the write for relay delivery. Never raises — a relay
        problem must not break the memory write that triggered it."""
        try:
            project_id = str(getattr(memory, "project_id", "") or "")
            if not project_id:
                return None
            row = await self._auto_share_row(project_id)
            if not row or not bool(row["enabled"]):
                return None
            if not bool(row["include_relay_origin"]) and self._is_relay_origin(memory):
                return None
            target_hub = row.get("target_hub")
            source_node_id = row.get("source_node_id")
            if not target_hub or not source_node_id:
                await self._record_auto_share_error(
                    project_id, "relay hub or source node is not configured"
                )
                return None
            outbox_id = await self.enqueue_memory_share(
                memory,
                source_node_id=source_node_id,
                source_version=self._auto_share_version(memory),
                target_hub=target_hub,
                event_type=event_type,
            )
            await self._mark_auto_share_synced(project_id)
            return outbox_id
        except (RelayTypeGateBlocked, RelaySecretBlocked):
            # Memory is not team-shareable (wrong kind or contains a secret) —
            # silently skip, exactly like enqueue_project_share does per item.
            return None
        except RelayIdempotencyConflict:
            return None
        except Exception as exc:  # never propagate to the memory write
            logger.warning("Relay auto-share failed for memory write: %s", exc)
            try:
                await self._record_auto_share_error(
                    str(getattr(memory, "project_id", "") or ""), str(exc)
                )
            except Exception:
                pass
            return None

    async def _mark_auto_share_synced(self, project_id: str) -> None:
        await self.db.execute(
            "UPDATE relay_auto_share_subscription "
            "SET last_synced_at = ?, last_error = NULL WHERE project_id = ?",
            (_utc_now(), project_id),
        )

    async def _record_auto_share_error(self, project_id: str, message: str) -> None:
        if not project_id:
            return
        await self.db.execute(
            "UPDATE relay_auto_share_subscription "
            "SET last_error = ? WHERE project_id = ?",
            (message[:500], project_id),
        )

    async def enqueue_project_share(
        self,
        project_id: str,
        *,
        source_node_id: str,
        source_version: Optional[int] = None,
        target_hub: str,
        event_type: str = "update",
        status: str = "active",
        force: bool = False,
    ) -> RelayShareProjectResponse:
        """Queue every shareable memory in a project.

        ``source_version`` left unset (the default) means each memory gets its
        own updated_at-derived version, matching auto-share — a project-wide
        re-share after some memories were edited won't collide on the ones
        that didn't change, or falsely reuse one memory's version for another.
        Pass an explicit value only to pin every memory to the same version.
        """
        rows = await self.db.fetchall(
            """
            SELECT *
            FROM memories
            WHERE project_id = ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (project_id,),
        )
        if not rows:
            raise KeyError(f"project has no memories: {project_id}")

        outbox_ids = []
        skipped = []
        for row in rows:
            memory = Memory(**dict(row))
            try:
                outbox_ids.append(
                    await self.enqueue_memory_share(
                        memory,
                        source_node_id=source_node_id,
                        source_version=source_version,
                        target_hub=target_hub,
                        event_type=event_type,
                        status=status,
                        force=force,
                    )
                )
            except (RelayTypeGateBlocked, RelaySecretBlocked) as exc:
                skipped.append({"memory_id": str(memory.id), "reason": str(exc)})

        return RelayShareProjectResponse(
            project_id=project_id,
            outbox_ids=outbox_ids,
            queued_count=len(outbox_ids),
            skipped=skipped,
            target_hub=target_hub,
            source_node_id=source_node_id,
        )

    async def enqueue_outbox(
        self,
        *,
        payload: Union[RelayIngestRequest, Dict[str, Any]],
        target_hub: str,
        force: bool = False,
    ) -> str:
        """Queue a relay event on a personal node before S2S push."""

        request = (
            payload
            if isinstance(payload, RelayIngestRequest)
            else RelayIngestRequest(**payload)
        )
        if request.content and redact_secrets(request.content) != request.content:
            raise RelaySecretBlocked("relay payload contains a high-confidence secret")

        now = _utc_now()
        payload_json = _json_dumps(request.model_dump(mode="json"))
        async with self.db.transaction():
            existing = await self.db.fetchone(
                """
                SELECT id, payload_hash, status
                FROM relay_outbox
                WHERE idempotency_key = ?
                """,
                (request.idempotency_key,),
            )
            if existing:
                if existing["payload_hash"] != request.payload_hash:
                    raise RelayIdempotencyConflict(
                        "outbox idempotency key reused with a different payload hash"
                    )
                if force and existing["status"] not in {"pending", "processing"}:
                    await self.db.execute(
                        """
                        UPDATE relay_outbox
                        SET payload_json = ?,
                            target_hub = ?,
                            status = 'pending',
                            attempts = 0,
                            next_attempt_at = ?,
                            locked_by = NULL,
                            locked_at = NULL,
                            last_error = NULL,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            payload_json,
                            target_hub,
                            _epoch_now(),
                            now,
                            existing["id"],
                        ),
                    )
                return existing["id"]

            outbox_id = str(uuid.uuid4())
            await self.db.execute(
                """
                INSERT INTO relay_outbox (
                    id, idempotency_key, payload_hash, payload_json,
                    target_hub, status, attempts, next_attempt_at,
                    locked_by, locked_at, last_error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, NULL, NULL, NULL, ?, ?)
                """,
                (
                    outbox_id,
                    request.idempotency_key,
                    request.payload_hash,
                    payload_json,
                    target_hub,
                    _epoch_now(),
                    now,
                    now,
                ),
            )
            return outbox_id

    async def claim_outbox(
        self, worker_id: str, *, lease_seconds: int = 300
    ) -> Optional[RelayOutboxJob]:
        """Claim one due personal-node outbox event for S2S delivery."""

        now = _epoch_now()
        expired_before = now - lease_seconds
        async with self.db.transaction():
            await self.db.execute(
                """
                UPDATE relay_outbox
                SET status = 'pending',
                    locked_by = NULL,
                    locked_at = NULL,
                    updated_at = ?
                WHERE status = 'processing'
                  AND locked_at IS NOT NULL
                  AND locked_at < ?
                """,
                (_utc_now(), expired_before),
            )
            row = await self.db.fetchone(
                """
                SELECT *
                FROM relay_outbox
                WHERE status = 'pending'
                  AND next_attempt_at <= ?
                ORDER BY created_at
                LIMIT 1
                """,
                (now,),
            )
            if not row:
                return None
            await self.db.execute(
                """
                UPDATE relay_outbox
                SET status = 'processing',
                    attempts = attempts + 1,
                    locked_by = ?,
                    locked_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (worker_id, now, _utc_now(), row["id"]),
            )
            claimed = await self.db.fetchone(
                "SELECT * FROM relay_outbox WHERE id = ?", (row["id"],)
            )

        return self._outbox_job_from_row(claimed) if claimed else None

    async def mark_outbox_sent(self, outbox_id: str) -> None:
        await self.db.execute(
            """
            UPDATE relay_outbox
            SET status = 'sent',
                locked_by = NULL,
                locked_at = NULL,
                last_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (_utc_now(), outbox_id),
        )

    async def mark_outbox_failed(self, outbox_id: str, error: str) -> None:
        row = await self.db.fetchone(
            "SELECT attempts FROM relay_outbox WHERE id = ?", (outbox_id,)
        )
        attempts = row["attempts"] if row else self.max_attempts
        status = "dead_letter" if attempts >= self.max_attempts else "pending"
        backoff = self._retry_backoff_seconds(attempts)
        await self.db.execute(
            """
            UPDATE relay_outbox
            SET status = ?,
                next_attempt_at = ?,
                locked_by = NULL,
                locked_at = NULL,
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, _epoch_now() + backoff, error[:1000], _utc_now(), outbox_id),
        )

    async def drain_next_outbox(
        self,
        *,
        worker_id: str,
        sender: Any,
        bearer_token: str,
        lease_seconds: int = 300,
    ) -> RelayProcessResult:
        """Deliver one claimed personal-node outbox event to a hub.

        ``sender`` is intentionally injected so tests can reproduce network and
        hub failures without external services. Production can pass
        :class:`RelayHTTPClient`.
        """

        job = await self.claim_outbox(worker_id, lease_seconds=lease_seconds)
        if not job:
            return RelayProcessResult(processed=False)

        try:
            await sender.send_ingest(
                target_hub=job.target_hub,
                bearer_token=bearer_token,
                payload=job.payload,
            )
            await self.mark_outbox_sent(job.id)
            return RelayProcessResult(processed=True, job_id=job.id)
        except RelayDeliveryConflict as exc:
            await self._mark_outbox_dead_letter(job.id, str(exc))
            return RelayProcessResult(
                processed=False,
                job_id=job.id,
                error=str(exc),
            )
        except Exception as exc:
            error = self._delivery_error_summary(exc)
            logger.warning(
                "Relay outbox delivery failed for job %s; will retry: %s",
                job.id,
                error,
            )
            await self.mark_outbox_failed(job.id, error)
            return RelayProcessResult(
                processed=False,
                job_id=job.id,
                error=error,
            )

    @staticmethod
    def _delivery_error_summary(exc: Exception) -> str:
        message = str(exc).strip()
        if message:
            return f"{exc.__class__.__name__}: {message}"
        return exc.__class__.__name__

    async def ingest(
        self, bearer_token: str, request: Union[RelayIngestRequest, Dict[str, Any]]
    ) -> RelayIngestResponse:
        """Accept one relay event from a personal node."""

        payload = (
            request
            if isinstance(request, RelayIngestRequest)
            else RelayIngestRequest(**request)
        )
        identity = await self._authenticate(bearer_token, require_scope="write")

        if payload.content and redact_secrets(payload.content) != payload.content:
            raise RelaySecretBlocked("relay payload contains a high-confidence secret")

        payload_json = _json_dumps(payload.model_dump(mode="json"))
        content_hash = self._hash_content(payload.content or "")
        source_node_id = identity["source_node_id"]
        source_user_id = identity["user_id"]
        now = _utc_now()
        event_id = str(uuid.uuid4())
        queued_item = False
        applied_to_current = False
        current_created = False

        async with self.db.transaction():
            existing = await self.db.fetchone(
                """
                SELECT *
                FROM relay_raw_event
                WHERE idempotency_key = ?
                """,
                (payload.idempotency_key,),
            )
            if existing:
                if existing["payload_hash"] != payload.payload_hash:
                    raise RelayIdempotencyConflict(
                        "idempotency key reused with a different payload hash"
                    )
                current = await self._get_current_locked(
                    source_node_id, payload.source_memory_id
                )
                if current:
                    await self._sync_materialized_from_current_locked(
                        current,
                        now=now,
                    )
                return RelayIngestResponse(
                    accepted=True,
                    event_id=existing["id"],
                    current_memory_id=current["id"] if current else None,
                    current_created=False,
                    replayed=True,
                    applied_to_current=bool(existing["applied_to_current"]),
                    queued_item=False,
                )

            team_project_id = await self._ensure_project_mapping_locked(
                source_node_id=source_node_id,
                source_user_id=source_user_id,
                source_project_key=payload.source_project_key,
                now=now,
            )

            current = await self._get_current_locked(
                source_node_id, payload.source_memory_id
            )
            applied_to_current = (
                current is None or payload.source_version > current["source_version"]
            )

            await self.db.execute(
                """
                INSERT INTO relay_raw_event (
                    id, idempotency_key, payload_hash, event_type,
                    source_node_id, source_user_id, source_memory_id,
                    source_version, source_project_key, team_project_id,
                    authoritative_kind, authoritative_status, content_hash,
                    payload_json, server_provenance_json, applied_to_current,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    payload.idempotency_key,
                    payload.payload_hash,
                    payload.event_type,
                    source_node_id,
                    source_user_id,
                    payload.source_memory_id,
                    payload.source_version,
                    payload.source_project_key,
                    team_project_id,
                    payload.kind,
                    payload.status,
                    content_hash,
                    payload_json,
                    _json_dumps(
                        {
                            "source": "relay",
                            "source_node_id": source_node_id,
                            "source_user_id": source_user_id,
                            "stamped_at": now,
                        }
                    ),
                    1 if applied_to_current else 0,
                    now,
                ),
            )

            current_memory_id: Optional[str]
            if applied_to_current:
                current_created = current is None
                current_memory_id = await self._upsert_current_locked(
                    existing_current=current,
                    event_id=event_id,
                    source_node_id=source_node_id,
                    payload=payload,
                    team_project_id=team_project_id,
                    content_hash=content_hash,
                    now=now,
                )
                if payload.event_type != "retract":
                    await self._enqueue_item_locked(
                        current_memory_id=current_memory_id,
                        raw_event_id=event_id,
                        now=now,
                    )
                    queued_item = True
            else:
                current_memory_id = current["id"] if current else None

        return RelayIngestResponse(
            accepted=True,
            event_id=event_id,
            current_memory_id=current_memory_id,
            current_created=current_created,
            replayed=False,
            applied_to_current=applied_to_current,
            queued_item=queued_item,
        )

    async def claim_queue_item(
        self, worker_id: str, *, lease_seconds: int = 300
    ) -> Optional[RelayQueueJob]:
        """Claim one pending per-item job, reclaiming expired processing jobs."""

        now = _epoch_now()
        expired_before = now - lease_seconds
        async with self.db.transaction():
            await self.db.execute(
                """
                UPDATE relay_queue_item
                SET status = 'pending',
                    locked_by = NULL,
                    locked_at = NULL,
                    updated_at = ?
                WHERE status = 'processing'
                  AND locked_at IS NOT NULL
                  AND locked_at < ?
                """,
                (_utc_now(), expired_before),
            )
            row = await self.db.fetchone(
                """
                SELECT *
                FROM relay_queue_item
                WHERE status = 'pending'
                  AND next_attempt_at <= ?
                ORDER BY created_at
                LIMIT 1
                """,
                (now,),
            )
            if not row:
                return None

            await self.db.execute(
                """
                UPDATE relay_queue_item
                SET status = 'processing',
                    attempts = attempts + 1,
                    locked_by = ?,
                    locked_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (worker_id, now, _utc_now(), row["id"]),
            )
            claimed = await self.db.fetchone(
                "SELECT * FROM relay_queue_item WHERE id = ?", (row["id"],)
            )

        return self._queue_job_from_row(claimed) if claimed else None

    async def process_next_item(
        self,
        *,
        worker_id: str,
        embedding_service: Any,
        text_enricher: Any,
        prompt_version: str,
        lease_seconds: int = 300,
    ) -> RelayProcessResult:
        """Process one per-item enrichment job.

        The slow embedding/LLM section intentionally runs outside any DB
        transaction. Only claim and final writes are transactional.
        """

        job = await self.claim_queue_item(worker_id, lease_seconds=lease_seconds)
        if not job:
            return RelayProcessResult(processed=False)

        try:
            current = await self.db.fetchone(
                "SELECT * FROM relay_memory_current WHERE id = ?", (job.ref_id,)
            )
            if not current or not current["visible"]:
                await self._mark_item_done(job.id)
                return RelayProcessResult(
                    processed=True,
                    job_id=job.id,
                    current_memory_id=job.ref_id,
                )

            content = current["content"] or ""
            embedding = await embedding_service.aembed(content)
            embedding_values = [float(value) for value in embedding]
            # Sender-provided enrichment: the personal node already ran its own
            # LLM enrich and shipped title/abstract in the share payload (ingest
            # stored it in EnrichmentStore as model='relay:sender-provided').
            # Re-enriching the same content on the hub is a duplicate LLM spend —
            # copy the sender's result into relay_item_enrichment instead. The
            # embedding above still runs (it never ships in the payload), and a
            # hub-side force enrich / content change re-enriches as before.
            sender = await EnrichmentStore(self.db).get(
                self._materialized_memory_id(job.ref_id)
            )
            if (
                sender
                and str(sender.get("model") or "") == "relay:sender-provided"
                and (sender.get("title") or sender.get("abstract"))
            ):
                enrichment = RelayEnrichmentData(
                    title=str(sender.get("title") or ""),
                    abstract=str(sender.get("abstract") or ""),
                    tags=list(sender.get("tags") or []),
                    display_kind=str(sender.get("display_kind") or ""),
                )
                model = "relay:sender-provided"
                model_version = "relay:sender-provided"
            else:
                enrichment = RelayEnrichmentData.from_result(
                    await text_enricher.enrich(content)
                )
                model = getattr(text_enricher, "model", "unknown")
                model_version = getattr(text_enricher, "model_version", model)
            now = _utc_now()
            embedding_model = getattr(embedding_service, "model_name", "unknown")
            embedding_dim = int(
                getattr(embedding_service, "dimension", len(embedding_values))
            )

            async with self.db.transaction():
                await self.db.execute(
                    """
                    INSERT INTO relay_item_enrichment (
                        id, current_memory_id, raw_event_id, content_hash,
                        embedding_json, embedding_model, embedding_dim,
                        title, abstract, tags_json, display_kind,
                        problem, resolution, lesson,
                        model, model_version, prompt_version,
                        confidence, generated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(
                        current_memory_id,
                        content_hash,
                        model_version,
                        prompt_version
                    )
                    DO UPDATE SET
                        raw_event_id = excluded.raw_event_id,
                        embedding_json = excluded.embedding_json,
                        embedding_model = excluded.embedding_model,
                        embedding_dim = excluded.embedding_dim,
                        title = excluded.title,
                        abstract = excluded.abstract,
                        tags_json = excluded.tags_json,
                        display_kind = excluded.display_kind,
                        problem = excluded.problem,
                        resolution = excluded.resolution,
                        lesson = excluded.lesson,
                        model = excluded.model,
                        confidence = excluded.confidence,
                        generated_at = excluded.generated_at
                    """,
                    (
                        str(uuid.uuid4()),
                        job.ref_id,
                        job.raw_event_id,
                        current["content_hash"],
                        _json_dumps(embedding_values),
                        embedding_model,
                        embedding_dim,
                        enrichment.title,
                        enrichment.abstract,
                        _json_dumps(enrichment.tags),
                        enrichment.display_kind,
                        enrichment.problem,
                        enrichment.resolution,
                        enrichment.lesson,
                        model,
                        model_version,
                        prompt_version,
                        enrichment.confidence,
                        now,
                    ),
                )
                await self._write_relay_vector_locked(
                    current_memory_id=job.ref_id,
                    embedding_values=embedding_values,
                )
                await self._write_materialized_memory_vector_locked(
                    current_memory_id=job.ref_id,
                    embedding_values=embedding_values,
                    now=now,
                )
                await self.db.execute(
                    """
                    UPDATE relay_queue_item
                    SET status = 'done',
                        locked_by = NULL,
                        locked_at = NULL,
                        last_error = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, job.id),
                )
                await self._enqueue_aggregate_locked(
                    team_project_id=current["team_project_id"],
                    raw_event_id=job.raw_event_id,
                    now=now,
                )

            return RelayProcessResult(
                processed=True,
                job_id=job.id,
                current_memory_id=job.ref_id,
            )
        except Exception as exc:
            logger.exception("Relay item worker failed for job %s", job.id)
            await self._mark_item_failed(job.id, str(exc))
            return RelayProcessResult(
                processed=False,
                job_id=job.id,
                current_memory_id=job.ref_id,
                error=str(exc),
            )

    async def claim_aggregate(
        self, worker_id: str, *, lease_seconds: int = 300
    ) -> Optional[RelayAggregateJob]:
        """Claim one pending aggregate digest job."""

        now = _epoch_now()
        expired_before = now - lease_seconds
        async with self.db.transaction():
            await self.db.execute(
                """
                UPDATE relay_queue_aggregate
                SET status = 'pending',
                    locked_by = NULL,
                    locked_at = NULL,
                    updated_at = ?
                WHERE status = 'processing'
                  AND locked_at IS NOT NULL
                  AND locked_at < ?
                """,
                (_utc_now(), expired_before),
            )
            row = await self.db.fetchone(
                """
                SELECT *
                FROM relay_queue_aggregate
                WHERE status = 'pending'
                  AND next_attempt_at <= ?
                ORDER BY created_at
                LIMIT 1
                """,
                (now,),
            )
            if not row:
                return None
            await self.db.execute(
                """
                UPDATE relay_queue_aggregate
                SET status = 'processing',
                    attempts = attempts + 1,
                    locked_by = ?,
                    locked_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (worker_id, now, _utc_now(), row["id"]),
            )
            claimed = await self.db.fetchone(
                "SELECT * FROM relay_queue_aggregate WHERE id = ?", (row["id"],)
            )
        return self._aggregate_job_from_row(claimed) if claimed else None

    async def process_next_aggregate(
        self,
        *,
        worker_id: str,
        digest_generator: Any,
        prompt_version: str,
        lease_seconds: int = 300,
    ) -> RelayProcessResult:
        """Generate one project digest from completed per-item enrichments."""

        job = await self.claim_aggregate(worker_id, lease_seconds=lease_seconds)
        if not job:
            return RelayProcessResult(processed=False)

        try:
            rows = await self.db.fetchall(
                """
                SELECT c.id AS current_memory_id,
                       c.team_project_id,
                       c.source_node_id,
                       c.source_memory_id,
                       c.source_version,
                       c.authoritative_kind,
                       c.authoritative_status,
                       c.content,
                       c.tags_json AS source_tags_json,
                       e.title,
                       e.abstract,
                       e.tags_json AS enrichment_tags_json,
                       e.display_kind,
                       e.problem,
                       e.resolution,
                       e.lesson,
                       e.generated_at
                FROM relay_memory_current c
                JOIN relay_item_enrichment e
                  ON e.current_memory_id = c.id
                 AND e.content_hash = c.content_hash
                WHERE c.team_project_id = ?
                  AND c.visible = 1
                ORDER BY c.updated_at DESC
                LIMIT 200
                """,
                (job.ref_id,),
            )
            items = [self._digest_item_from_row(row) for row in rows]
            digest = RelayDigestData.from_result(
                await digest_generator.generate(
                    team_project_id=job.ref_id,
                    items=items,
                )
            )

            now = _utc_now()
            model = getattr(digest_generator, "model", "unknown")
            model_version = getattr(digest_generator, "model_version", model)
            async with self.db.transaction():
                await self.db.execute(
                    """
                    INSERT INTO relay_project_digest (
                        id, team_project_id, rollup_json, contributors_json,
                        recent_activity_json, narrative, source_memory_ids_json,
                        model, model_version, prompt_version, generated_at, stale
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(team_project_id, model_version, prompt_version)
                    DO UPDATE SET
                        rollup_json = excluded.rollup_json,
                        contributors_json = excluded.contributors_json,
                        recent_activity_json = excluded.recent_activity_json,
                        narrative = excluded.narrative,
                        source_memory_ids_json = excluded.source_memory_ids_json,
                        model = excluded.model,
                        generated_at = excluded.generated_at,
                        stale = 0
                    """,
                    (
                        str(uuid.uuid4()),
                        job.ref_id,
                        _json_dumps(digest.rollup),
                        _json_dumps(digest.contributors),
                        _json_dumps(digest.recent_activity),
                        digest.narrative,
                        _json_dumps(digest.source_memory_ids),
                        model,
                        model_version,
                        prompt_version,
                        now,
                    ),
                )
                await self.db.execute(
                    """
                    UPDATE relay_queue_aggregate
                    SET status = 'done',
                        locked_by = NULL,
                        locked_at = NULL,
                        last_error = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, job.id),
                )

            return RelayProcessResult(
                processed=True,
                job_id=job.id,
                current_memory_id=job.ref_id,
            )
        except Exception as exc:
            logger.exception("Relay aggregate worker failed for job %s", job.id)
            await self._mark_aggregate_failed(job.id, str(exc))
            return RelayProcessResult(
                processed=False,
                job_id=job.id,
                current_memory_id=job.ref_id,
                error=str(exc),
            )

    async def search(
        self,
        *,
        query: str,
        team_project_ids: Optional[Sequence[str]] = None,
        limit: int = 10,
        embedding_service: Any = None,
        exclude_source_node: Optional[str] = None,
        kinds: Optional[Sequence[str]] = None,
    ) -> RelaySearchResponse:
        """Simple visible-current search for the relay MVP.

        This is a safe fallback until relay sqlite-vec indexing is added. It
        keeps the read surface testable without pretending cross-corpus vector
        fusion is complete.

        ``exclude_source_node`` omits memories a federated caller pushed itself
        (those already rank in its local results). ``kinds`` filters by
        authoritative kind hub-side so a category-scoped federated search does
        not waste its top-k budget on kinds the caller will drop.
        """

        limit = max(1, min(limit, 50))
        kinds = [k for k in (kinds or []) if k]
        if query and embedding_service is not None:
            vector_response = await self._search_vector(
                query=query,
                embedding_service=embedding_service,
                team_project_ids=team_project_ids,
                limit=limit,
                exclude_source_node=exclude_source_node,
                kinds=kinds,
            )
            if vector_response is not None:
                return vector_response

        params: list[Any] = []
        where = ["c.visible = 1"]
        if query:
            where.append("(c.content LIKE ? OR e.title LIKE ? OR e.abstract LIKE ?)")
            pattern = f"%{query}%"
            params.extend([pattern, pattern, pattern])
        if team_project_ids:
            placeholders = ",".join("?" for _ in team_project_ids)
            where.append(f"c.team_project_id IN ({placeholders})")
            params.extend(team_project_ids)
        if exclude_source_node:
            where.append("c.source_node_id != ?")
            params.append(exclude_source_node)
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            where.append(f"c.authoritative_kind IN ({placeholders})")
            params.extend(kinds)
        params.append(limit)

        rows = await self.db.fetchall(
            f"""
            SELECT c.*,
                   e.title,
                   e.abstract,
                   e.tags_json AS enrichment_tags
            FROM relay_memory_current c
            LEFT JOIN relay_item_enrichment e
              ON e.current_memory_id = c.id
            WHERE {' AND '.join(where)}
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        )

        results = [
            self._search_result_from_row(row, rank=idx, score=1.0 / idx)
            for idx, row in enumerate(rows, start=1)
        ]
        return RelaySearchResponse(
            results=results,
            total=len(results),
            metadata={"search_mode": "text"},
        )

    async def get_project_digest(
        self, team_project_id: str
    ) -> Optional[RelayProjectDigestResponse]:
        row = await self.db.fetchone(
            """
            SELECT *
            FROM relay_project_digest
            WHERE team_project_id = ?
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (team_project_id,),
        )
        if not row:
            return None
        return RelayProjectDigestResponse(
            team_project_id=row["team_project_id"],
            rollup=_json_loads(row["rollup_json"], {}),
            contributors=_json_loads(row["contributors_json"], []),
            recent_activity=_json_loads(row["recent_activity_json"], []),
            narrative=row["narrative"] or "",
            source_memory_ids=_json_loads(row["source_memory_ids_json"], []),
            model=row["model"],
            model_version=row["model_version"],
            prompt_version=row["prompt_version"],
            generated_at=row["generated_at"],
            stale=bool(row["stale"]),
        )

    async def authorize(self, token: str, *, require_scope: str) -> Dict[str, Any]:
        """Validate a relay token for read/write routes."""

        return await self._authenticate(token, require_scope=require_scope)

    async def _authenticate(self, token: str, *, require_scope: str) -> Dict[str, Any]:
        token_hash = self._hash_token(token)
        row = await self.db.fetchone(
            "SELECT * FROM relay_identity WHERE token_hash = ?", (token_hash,)
        )
        if not row or row["revoked"]:
            raise RelayUnauthorized("invalid or revoked relay token")
        scopes = set(_json_loads(row["scopes_json"], []))
        if require_scope not in scopes:
            raise RelayUnauthorized("relay token does not include required scope")
        return dict(row)

    async def _ensure_project_mapping_locked(
        self,
        *,
        source_node_id: str,
        source_user_id: str,
        source_project_key: str,
        now: str,
    ) -> str:
        mapping = await self.db.fetchone(
            """
            SELECT team_project_id
            FROM relay_project_mapping
            WHERE source_node_id = ?
              AND source_project_key = ?
            """,
            (source_node_id, source_project_key),
        )
        if mapping:
            return mapping["team_project_id"]

        team_project_id = f"{source_node_id}:{source_project_key}"
        project = await self.db.fetchone(
            "SELECT team_project_id FROM relay_project WHERE team_project_id = ?",
            (team_project_id,),
        )
        if not project:
            await self.db.execute(
                """
                INSERT INTO relay_project (
                    team_project_id, display_name, description,
                    created_by_user_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    team_project_id,
                    source_project_key,
                    None,
                    source_user_id,
                    now,
                    now,
                ),
            )
        await self.db.execute(
            """
            INSERT INTO relay_project_mapping (
                id, source_node_id, source_project_key, team_project_id,
                share_policy_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, '{}', ?, ?)
            """,
            (
                str(uuid.uuid4()),
                source_node_id,
                source_project_key,
                team_project_id,
                now,
                now,
            ),
        )
        return team_project_id

    @staticmethod
    def _materialized_memory_id(current_memory_id: str) -> str:
        return f"relay:{current_memory_id}"

    async def _get_current_locked(
        self, source_node_id: str, source_memory_id: str
    ) -> Optional[Any]:
        return await self.db.fetchone(
            """
            SELECT *
            FROM relay_memory_current
            WHERE source_node_id = ?
              AND source_memory_id = ?
            """,
            (source_node_id, source_memory_id),
        )

    async def _upsert_current_locked(
        self,
        *,
        existing_current: Optional[Any],
        event_id: str,
        source_node_id: str,
        payload: RelayIngestRequest,
        team_project_id: str,
        content_hash: str,
        now: str,
    ) -> str:
        visible = 0 if payload.event_type == "retract" else 1
        tombstoned_at = now if payload.event_type == "retract" else None
        current_memory_id = (
            existing_current["id"] if existing_current else str(uuid.uuid4())
        )
        content = payload.content
        if payload.event_type == "retract" and existing_current:
            content = existing_current["content"]

        if existing_current:
            await self.db.execute(
                """
                UPDATE relay_memory_current
                SET source_version = ?,
                    latest_event_id = ?,
                    team_project_id = ?,
                    source_project_key = ?,
                    authoritative_kind = ?,
                    authoritative_status = ?,
                    content = ?,
                    content_hash = ?,
                    tags_json = ?,
                    links_json = ?,
                    visible = ?,
                    tombstoned_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.source_version,
                    event_id,
                    team_project_id,
                    payload.source_project_key,
                    payload.kind,
                    payload.status,
                    content,
                    content_hash,
                    _json_dumps(payload.tags),
                    _json_dumps(payload.links),
                    visible,
                    tombstoned_at,
                    now,
                    current_memory_id,
                ),
            )
        else:
            await self.db.execute(
                """
                INSERT INTO relay_memory_current (
                    id, source_node_id, source_memory_id, source_version,
                    latest_event_id, team_project_id, source_project_key,
                    authoritative_kind, authoritative_status, content,
                    content_hash, tags_json, links_json, visible,
                    tombstoned_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    current_memory_id,
                    source_node_id,
                    payload.source_memory_id,
                    payload.source_version,
                    event_id,
                    team_project_id,
                    payload.source_project_key,
                    payload.kind,
                    payload.status,
                    content,
                    content_hash,
                    _json_dumps(payload.tags),
                    _json_dumps(payload.links),
                    visible,
                    tombstoned_at,
                    now,
                ),
            )
        await self._sync_materialized_memory_locked(
            current_memory_id=current_memory_id,
            source_node_id=source_node_id,
            kind=payload.kind,
            tags=payload.tags,
            source_project_key=payload.source_project_key,
            content_hash=content_hash,
            content=content,
            visible=bool(visible),
            now=now,
        )
        # A personal node's local "Enrich" (EnrichmentStore, separate from
        # Memory.content) rides along in the payload when present — store it
        # against the MATERIALIZED memory id so the hub's existing "AI
        # enrichment" UI (which reads EnrichmentStore, not relay_item_enrichment)
        # picks it up without the hub running its own LLM enrichment pass.
        if visible and (payload.title or payload.abstract):
            await EnrichmentStore(self.db).upsert(
                memory_id=self._materialized_memory_id(current_memory_id),
                title=payload.title or "",
                abstract=payload.abstract or "",
                tags=payload.tags,
                display_kind=payload.display_kind or "",
                model="relay:sender-provided",
            )
        return current_memory_id

    async def _sync_materialized_memory_locked(
        self,
        *,
        current_memory_id: str,
        source_node_id: str,
        kind: str,
        tags: Sequence[str],
        source_project_key: str,
        content_hash: str,
        content: Optional[str],
        visible: bool,
        now: str,
    ) -> None:
        # The materialized memory keeps the ORIGINAL project name (e.g. "mem-mesh")
        # so it groups and searches with the team's project, not a node-prefixed
        # team_project_id. The source node stays distinguishable via client
        # (``relay:<source_node_id>``) below.
        memory_id = self._materialized_memory_id(current_memory_id)
        if not visible or not content:
            await self._delete_materialized_memory_locked(memory_id)
            return

        existing = await self.db.fetchone(
            "SELECT content_hash, embedding, created_at FROM memories WHERE id = ?",
            (memory_id,),
        )
        content_changed = (
            existing is not None and existing["content_hash"] != content_hash
        )
        embedding = (
            existing["embedding"]
            if existing is not None and not content_changed
            else self._zero_embedding_bytes()
        )
        tags_json = self._materialized_tags(tags)
        client = f"relay:{source_node_id}"

        if existing:
            await self.db.execute(
                """
                UPDATE memories
                SET content = ?,
                    content_hash = ?,
                    project_id = ?,
                    category = ?,
                    source = 'relay',
                    client = ?,
                    embedding = ?,
                    tags = ?,
                    updated_at = ?,
                    content_bytes = ?
                WHERE id = ?
                """,
                (
                    content,
                    content_hash,
                    source_project_key,
                    kind,
                    client,
                    embedding,
                    tags_json,
                    now,
                    len(content),
                    memory_id,
                ),
            )
            if content_changed:
                await self._delete_memory_vector_locked(memory_id)
        else:
            await self.db.execute(
                """
                INSERT INTO memories (
                    id, content, content_hash, project_id, category, source,
                    client, embedding, tags, created_at, updated_at, content_bytes
                )
                VALUES (?, ?, ?, ?, ?, 'relay', ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    content,
                    content_hash,
                    source_project_key,
                    kind,
                    client,
                    embedding,
                    tags_json,
                    now,
                    now,
                    len(content),
                ),
            )

    async def _sync_materialized_from_current_locked(
        self, current: Any, *, now: str
    ) -> None:
        await self._sync_materialized_memory_locked(
            current_memory_id=str(current["id"]),
            source_node_id=str(current["source_node_id"]),
            kind=str(current["authoritative_kind"]),
            tags=_json_loads(current["tags_json"], []),
            source_project_key=str(current["source_project_key"]),
            content_hash=str(current["content_hash"]),
            content=current["content"],
            visible=bool(current["visible"]),
            now=now,
        )

    async def _delete_materialized_memory_locked(self, memory_id: str) -> None:
        await self._delete_memory_vector_locked(memory_id)
        await self.db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

    @staticmethod
    def _materialized_tags(tags: Sequence[str]) -> str:
        merged: list[str] = []
        for tag in [*tags, "relay", "shared"]:
            if tag and tag not in merged:
                merged.append(tag)
        return _json_dumps(merged)

    def _zero_embedding_bytes(self) -> bytes:
        import numpy as np

        return np.zeros(self.db.embedding_dim, dtype=np.float32).tobytes()

    @staticmethod
    def _embedding_values_to_bytes(embedding_values: Sequence[float]) -> bytes:
        import numpy as np

        return np.asarray(list(embedding_values), dtype=np.float32).tobytes()

    async def _enqueue_item_locked(
        self, *, current_memory_id: str, raw_event_id: str, now: str
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO relay_queue_item (
                id, ref_id, raw_event_id, status, attempts, next_attempt_at,
                locked_by, locked_at, last_error, created_at, updated_at
            )
            VALUES (?, ?, ?, 'pending', 0, ?, NULL, NULL, NULL, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                current_memory_id,
                raw_event_id,
                _epoch_now(),
                now,
                now,
            ),
        )

    async def _enqueue_aggregate_locked(
        self, *, team_project_id: str, raw_event_id: str, now: str
    ) -> None:
        existing = await self.db.fetchone(
            """
            SELECT id
            FROM relay_queue_aggregate
            WHERE coalesce_key = ?
              AND status = 'pending'
            """,
            (team_project_id,),
        )
        if existing:
            await self.db.execute(
                """
                UPDATE relay_queue_aggregate
                SET raw_event_id = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (raw_event_id, now, existing["id"]),
            )
            return

        await self.db.execute(
            """
            INSERT INTO relay_queue_aggregate (
                id, ref_id, raw_event_id, coalesce_key, status,
                attempts, next_attempt_at, locked_by, locked_at,
                last_error, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'pending', 0, ?, NULL, NULL, NULL, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                team_project_id,
                raw_event_id,
                team_project_id,
                _epoch_now(),
                now,
                now,
            ),
        )

    async def _mark_item_done(self, job_id: str) -> None:
        await self.db.execute(
            """
            UPDATE relay_queue_item
            SET status = 'done',
                locked_by = NULL,
                locked_at = NULL,
                last_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (_utc_now(), job_id),
        )

    async def _mark_item_failed(self, job_id: str, error: str) -> None:
        row = await self.db.fetchone(
            "SELECT attempts FROM relay_queue_item WHERE id = ?", (job_id,)
        )
        attempts = row["attempts"] if row else self.max_attempts
        status = "dead_letter" if attempts >= self.max_attempts else "pending"
        backoff = self._retry_backoff_seconds(attempts)
        await self.db.execute(
            """
            UPDATE relay_queue_item
            SET status = ?,
                next_attempt_at = ?,
                locked_by = NULL,
                locked_at = NULL,
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, _epoch_now() + backoff, error[:1000], _utc_now(), job_id),
        )

    async def _mark_aggregate_failed(self, job_id: str, error: str) -> None:
        row = await self.db.fetchone(
            "SELECT attempts FROM relay_queue_aggregate WHERE id = ?", (job_id,)
        )
        attempts = row["attempts"] if row else self.max_attempts
        status = "dead_letter" if attempts >= self.max_attempts else "pending"
        backoff = self._retry_backoff_seconds(attempts)
        await self.db.execute(
            """
            UPDATE relay_queue_aggregate
            SET status = ?,
                next_attempt_at = ?,
                locked_by = NULL,
                locked_at = NULL,
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, _epoch_now() + backoff, error[:1000], _utc_now(), job_id),
        )

    async def _mark_outbox_dead_letter(self, outbox_id: str, error: str) -> None:
        await self.db.execute(
            """
            UPDATE relay_outbox
            SET status = 'dead_letter',
                locked_by = NULL,
                locked_at = NULL,
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (error[:1000], _utc_now(), outbox_id),
        )

    async def _ensure_vector_schema(self) -> None:
        if not self.db.connection or not self.db._connection.is_vec_available:
            return
        try:
            await self.db.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS relay_memory_vec USING vec0(
                    current_memory_id TEXT PRIMARY KEY,
                    embedding FLOAT[{self.db.embedding_dim}]
                )
            """)
        except Exception as exc:
            logger.warning("Relay sqlite-vec table setup skipped: %s", exc)

    async def _write_relay_vector_locked(
        self, *, current_memory_id: str, embedding_values: Sequence[float]
    ) -> None:
        if len(embedding_values) != self.db.embedding_dim:
            logger.warning(
                "Skipping relay vector write for %s: dim %s != db dim %s",
                current_memory_id,
                len(embedding_values),
                self.db.embedding_dim,
            )
            return
        table = await self.db.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='relay_memory_vec'"
        )
        if not table:
            return
        embedding_json = _json_dumps([float(value) for value in embedding_values])
        await self.db.execute(
            "DELETE FROM relay_memory_vec WHERE current_memory_id = ?",
            (current_memory_id,),
        )
        await self.db.execute(
            """
            INSERT INTO relay_memory_vec (current_memory_id, embedding)
            VALUES (?, ?)
            """,
            (current_memory_id, embedding_json),
        )

    async def _write_materialized_memory_vector_locked(
        self,
        *,
        current_memory_id: str,
        embedding_values: Sequence[float],
        now: str,
    ) -> None:
        if len(embedding_values) != self.db.embedding_dim:
            logger.warning(
                "Skipping materialized relay memory vector for %s: dim %s != db dim %s",
                current_memory_id,
                len(embedding_values),
                self.db.embedding_dim,
            )
            return

        memory_id = self._materialized_memory_id(current_memory_id)
        existing = await self.db.fetchone(
            "SELECT id FROM memories WHERE id = ?", (memory_id,)
        )
        if not existing:
            return

        embedding_bytes = self._embedding_values_to_bytes(embedding_values)
        await self.db.execute(
            "UPDATE memories SET embedding = ?, updated_at = ? WHERE id = ?",
            (embedding_bytes, now, memory_id),
        )

        tables = await self._memory_vector_write_tables_locked()
        if tables == ["memories_vec_fallback"]:
            await self.db.execute(
                "DELETE FROM memories_vec_fallback WHERE memory_id = ?",
                (memory_id,),
            )
            await self.db.execute(
                "INSERT INTO memories_vec_fallback (memory_id, embedding) VALUES (?, ?)",
                (memory_id, embedding_bytes),
            )
            return

        embedding_json = _json_dumps([float(value) for value in embedding_values])
        for table in tables:
            await self.db.execute(
                f"DELETE FROM {table} WHERE memory_id = ?",
                (memory_id,),
            )
            await self.db.execute(
                f"INSERT INTO {table} (memory_id, embedding) VALUES (?, ?)",
                (memory_id, embedding_json),
            )

    async def _delete_memory_vector_locked(self, memory_id: str) -> None:
        for table in await self._memory_vector_write_tables_locked():
            await self.db.execute(
                f"DELETE FROM {table} WHERE memory_id = ?",
                (memory_id,),
            )

    async def _memory_vector_write_tables_locked(self) -> list[str]:
        active = await self.db.active_embedding_table()
        row = await self.db.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (active,),
        )
        if not row:
            return ["memories_vec_fallback"]

        tables = [active]
        if await self.db.migration_in_progress():
            inactive = await self.db.inactive_embedding_table()
            inactive_row = await self.db.fetchone(
                "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                (inactive,),
            )
            if inactive_row:
                tables.append(inactive)
        return tables

    async def _search_vector(
        self,
        *,
        query: str,
        embedding_service: Any,
        team_project_ids: Optional[Sequence[str]],
        limit: int,
        exclude_source_node: Optional[str] = None,
        kinds: Optional[Sequence[str]] = None,
    ) -> Optional[RelaySearchResponse]:
        table = await self.db.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='relay_memory_vec'"
        )
        if not table:
            return None

        try:
            query_embedding = [
                float(value) for value in await embedding_service.aembed(query)
            ]
            if len(query_embedding) != self.db.embedding_dim:
                return None
            # Over-fetch more vec candidates when a kind filter applies, since
            # the filter runs on the outer join and discards candidates.
            overfetch = limit * (6 if kinds else 3)
            params: list[Any] = [_json_dumps(query_embedding), overfetch]
            where = ["c.visible = 1"]
            if team_project_ids:
                placeholders = ",".join("?" for _ in team_project_ids)
                where.append(f"c.team_project_id IN ({placeholders})")
                params.extend(team_project_ids)
            if exclude_source_node:
                where.append("c.source_node_id != ?")
                params.append(exclude_source_node)
            if kinds:
                placeholders = ",".join("?" for _ in kinds)
                where.append(f"c.authoritative_kind IN ({placeholders})")
                params.extend(kinds)
            params.append(limit)

            rows = await self.db.fetchall(
                f"""
                SELECT c.*,
                       e.title,
                       e.abstract,
                       e.tags_json AS enrichment_tags,
                       ve.distance
                FROM (
                    SELECT current_memory_id, distance
                    FROM relay_memory_vec
                    WHERE embedding MATCH ?
                    ORDER BY distance
                    LIMIT ?
                ) ve
                JOIN relay_memory_current c
                  ON c.id = ve.current_memory_id
                LEFT JOIN relay_item_enrichment e
                  ON e.current_memory_id = c.id
                 AND e.content_hash = c.content_hash
                WHERE {' AND '.join(where)}
                ORDER BY ve.distance
                LIMIT ?
                """,
                tuple(params),
            )
        except Exception as exc:
            logger.warning("Relay vector search failed, falling back: %s", exc)
            return None

        if not rows:
            # An empty vec index (fresh hub, enrichment not yet run) yields zero
            # candidates even though relay_memory_current has content — fall back
            # to the text path instead of returning an empty vector response.
            return None

        results = []
        for idx, row in enumerate(rows, start=1):
            distance = float(row["distance"])
            score = 1.0 / (1.0 + max(distance, 0.0))
            results.append(self._search_result_from_row(row, rank=idx, score=score))
        return RelaySearchResponse(
            results=results,
            total=len(results),
            metadata={"search_mode": "vector"},
        )

    @staticmethod
    def _search_result_from_row(
        row: Any, *, rank: int, score: float
    ) -> RelaySearchResult:
        tags = _json_loads(row["enrichment_tags"], None)
        if tags is None:
            tags = _json_loads(row["tags_json"], [])
        return RelaySearchResult(
            id=row["id"],
            content=row["content"] or "",
            team_project_id=row["team_project_id"],
            source_node_id=row["source_node_id"],
            source_memory_id=row["source_memory_id"],
            source_version=row["source_version"],
            kind=row["authoritative_kind"],
            status=row["authoritative_status"],
            tags=tags,
            title=row["title"],
            abstract=row["abstract"],
            rank=rank,
            score=score,
            updated_at=row["updated_at"] if "updated_at" in row.keys() else None,
        )

    async def _db_backed_setting(
        self,
        *,
        key: str,
        label: str,
        settings: Any,
        secret: bool = False,
    ) -> RelaySettingValue:
        value, source = await self._effective_setting_value(key, settings)
        _field, env_var = self.SETTING_FIELDS[key]
        return RelaySettingValue(
            key=key,
            label=label,
            value=None if secret else value,
            configured=bool(value),
            source=source,
            env_var=env_var,
            env_pinned=os.environ.get(env_var) is not None,
            secret=secret,
        )

    async def _effective_setting_value(
        self, key: str, settings: Any
    ) -> tuple[str, str]:
        db_value = await self.db.get_app_config(self.CONFIG_KEYS[key])
        if db_value is not None:
            return str(db_value), "db"

        field, env_var = self.SETTING_FIELDS[key]
        value = str(getattr(settings, field, "") or "")
        source = "env" if os.environ.get(env_var) is not None else "default"
        return value, source

    async def _identity_row_by_prefix(self, token_hash_prefix: str) -> Optional[Any]:
        prefix = str(token_hash_prefix or "").strip()
        if not prefix:
            return None
        rows = await self.db.fetchall(
            """
            SELECT
                token_hash, user_id, source_node_id, display_name,
                home_domain, scopes_json, revoked, created_at, updated_at
            FROM relay_identity
            WHERE token_hash LIKE ?
            ORDER BY updated_at DESC
            LIMIT 2
            """,
            (f"{prefix}%",),
        )
        if len(rows) > 1:
            raise ValueError("relay identity token hash prefix is ambiguous")
        return rows[0] if rows else None

    @staticmethod
    def _identity_from_row(row: Any) -> RelayIdentitySummary:
        return RelayIdentitySummary(
            token_hash_prefix=str(row["token_hash"])[:12],
            user_id=str(row["user_id"]),
            source_node_id=str(row["source_node_id"]),
            display_name=str(row["display_name"]),
            home_domain=row["home_domain"],
            scopes=_json_loads(row["scopes_json"], []),
            revoked=bool(row["revoked"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _digest_item_from_row(row: Any) -> Dict[str, Any]:
        enrichment_tags = _json_loads(row["enrichment_tags_json"], None)
        source_tags = _json_loads(row["source_tags_json"], [])
        return {
            "current_memory_id": row["current_memory_id"],
            "team_project_id": row["team_project_id"],
            "source_node_id": row["source_node_id"],
            "source_memory_id": row["source_memory_id"],
            "source_version": row["source_version"],
            "kind": row["authoritative_kind"],
            "status": row["authoritative_status"],
            "content": row["content"],
            "title": row["title"],
            "abstract": row["abstract"],
            "tags": enrichment_tags if enrichment_tags is not None else source_tags,
            "display_kind": row["display_kind"],
            "problem": row["problem"],
            "resolution": row["resolution"],
            "lesson": row["lesson"],
            "generated_at": row["generated_at"],
        }

    @staticmethod
    def _queue_job_from_row(row: Any) -> RelayQueueJob:
        return RelayQueueJob(
            id=row["id"],
            ref_id=row["ref_id"],
            raw_event_id=row["raw_event_id"],
            status=row["status"],
            attempts=row["attempts"],
            locked_by=row["locked_by"],
            locked_at=row["locked_at"],
        )

    @staticmethod
    def _aggregate_job_from_row(row: Any) -> RelayAggregateJob:
        return RelayAggregateJob(
            id=row["id"],
            ref_id=row["ref_id"],
            raw_event_id=row["raw_event_id"],
            coalesce_key=row["coalesce_key"],
            status=row["status"],
            attempts=row["attempts"],
            locked_by=row["locked_by"],
            locked_at=row["locked_at"],
        )

    @staticmethod
    def _outbox_job_from_row(row: Any) -> RelayOutboxJob:
        return RelayOutboxJob(
            id=row["id"],
            idempotency_key=row["idempotency_key"],
            payload_hash=row["payload_hash"],
            payload=RelayIngestRequest(**_json_loads(row["payload_json"], {})),
            target_hub=row["target_hub"],
            status=row["status"],
            attempts=row["attempts"],
            locked_by=row["locked_by"],
            locked_at=row["locked_at"],
        )

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_content(content: str) -> str:
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_payload(payload: Dict[str, Any]) -> str:
        return (
            "sha256:" + hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()
        )

    @staticmethod
    def _memory_tags(memory: Any) -> list[str]:
        if hasattr(memory, "get_tags"):
            tags = memory.get_tags()
            return tags or []
        tags_value = getattr(memory, "tags", None)
        if not tags_value:
            return []
        if isinstance(tags_value, list):
            return [str(tag) for tag in tags_value if tag]
        return _json_loads(str(tags_value), [])
