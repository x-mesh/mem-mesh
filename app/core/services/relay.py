"""Core service for the mem-mesh relay layer.

The relay service intentionally keeps ingest deterministic: it authenticates,
validates, appends a raw event, updates the current projection, and enqueues
post-processing work. LLM and embedding calls happen only in worker methods.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence, Union

from ..database.base import Database
from ..database.models import Memory
from ..errors import (
    RelayDeliveryConflict,
    RelayError as RelayError,
    RelayIdempotencyConflict,
    RelaySecretBlocked,
    RelayTypeGateBlocked,
    RelayUnauthorized,
)
from ..redaction import redact_secrets
from ..schemas.relay import (
    RelayAdminOverviewResponse,
    RelayAggregateJob,
    RelayDigestSummary,
    RelayDigestData,
    RelayEnrichmentData,
    RelayHubCheckResponse,
    RelayIdentitySummary,
    RelayIdentityUpdateRequest,
    RelayIngestRequest,
    RelayIngestResponse,
    RelayOutboxJob,
    RelayOutboxSummary,
    RelayProjectDigestResponse,
    RelayProcessResult,
    RelayQueueJob,
    RelayQueueSummary,
    RelaySearchResponse,
    RelaySearchResult,
    RelaySettingValue,
    RelayShareProjectResponse,
    RelaySettingsResponse,
    RelaySettingsUpdateRequest,
    RelayStatusCount,
)

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


class RelayService:
    """SQLite-backed relay ingest and worker service."""

    CONFIG_KEYS = {
        "hub_url": "relay.hub_url",
        "source_node_id": "relay.source_node_id",
        "default_source_version": "relay.default_source_version",
        "hub_token": "relay.hub_token",
        "sonnet_api_key": "relay.sonnet_api_key",
        "sonnet_model": "relay.sonnet_model",
        "sonnet_base_url": "relay.sonnet_base_url",
        "prompt_version": "relay.prompt_version",
    }
    SETTING_FIELDS = {
        "hub_url": ("relay_hub_url", "MEM_MESH_RELAY_HUB_URL"),
        "source_node_id": ("relay_source_node_id", "MEM_MESH_RELAY_SOURCE_NODE_ID"),
        "hub_token": ("relay_hub_token", "MEM_MESH_RELAY_HUB_TOKEN"),
        "sonnet_api_key": ("relay_sonnet_api_key", "MEM_MESH_RELAY_SONNET_API_KEY"),
        "sonnet_model": ("relay_sonnet_model", "MEM_MESH_RELAY_SONNET_MODEL"),
        "sonnet_base_url": (
            "relay_sonnet_base_url",
            "MEM_MESH_RELAY_SONNET_BASE_URL",
        ),
        "prompt_version": ("relay_prompt_version", "MEM_MESH_RELAY_PROMPT_VERSION"),
    }
    DEFAULT_SHAREABLE_KINDS = {
        "bug",
        "idea",
        "decision",
        "incident",
        "code_snippet",
        "git-history",
    }

    def __init__(self, db: Database, *, max_attempts: int = 3):
        self.db = db
        self.max_attempts = max_attempts

    async def ensure_schema(self) -> None:
        """Create relay tables and indexes if they do not exist."""

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

        queue_rows = sorted(
            [*item_rows, *aggregate_rows],
            key=lambda row: str(row["created_at"]),
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
        )

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
            sonnet_api_key=await self._db_backed_setting(
                key="sonnet_api_key",
                label="Sonnet API key",
                settings=settings,
                secret=True,
            ),
            sonnet_model=await self._db_backed_setting(
                key="sonnet_model",
                label="Sonnet model",
                settings=settings,
            ),
            sonnet_base_url=await self._db_backed_setting(
                key="sonnet_base_url",
                label="Sonnet endpoint",
                settings=settings,
            ),
            prompt_version=await self._db_backed_setting(
                key="prompt_version",
                label="Prompt version",
                settings=settings,
            ),
            identities=await self.list_identities(),
        )

    async def update_admin_settings(
        self, request: RelaySettingsUpdateRequest
    ) -> RelaySettingsResponse:
        """Persist dashboard-managed relay defaults."""

        for key in (
            "hub_url",
            "source_node_id",
            "hub_token",
            "sonnet_api_key",
            "sonnet_model",
            "sonnet_base_url",
            "prompt_version",
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
        timeout: float = 5.0,
        http_client: Any = None,
    ) -> RelayHubCheckResponse:
        cleaned = str(hub_url or "").strip()
        health_url = RelayHTTPClient.health_url(cleaned)
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
            return RelayHubCheckResponse(
                ok=ok,
                hub_url=cleaned,
                health_url=health_url,
                status_code=status_code,
                relay=relay,
                message=message,
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

    async def enqueue_memory_share(
        self,
        memory: Any,
        *,
        source_node_id: str,
        source_version: int,
        target_hub: str,
        event_type: str = "update",
        status: str = "active",
        allowed_kinds: Optional[Sequence[str]] = None,
    ) -> str:
        """Build and enqueue a relay outbox event from an existing memory."""

        kind = str(getattr(memory, "category", "") or "")
        allowed = set(allowed_kinds or self.DEFAULT_SHAREABLE_KINDS)
        if kind not in allowed:
            raise RelayTypeGateBlocked(f"memory kind is not team-shareable: {kind}")

        content = str(getattr(memory, "content", "") or "")
        if redact_secrets(content) != content:
            raise RelaySecretBlocked("relay payload contains a high-confidence secret")

        source_memory_id = str(getattr(memory, "id"))
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
            created_at=getattr(memory, "created_at", None),
            updated_at=getattr(memory, "updated_at", None),
        )
        return await self.enqueue_outbox(payload=request, target_hub=target_hub)

    async def enqueue_memory_share_by_id(
        self,
        memory_id: str,
        *,
        source_node_id: str,
        source_version: int,
        target_hub: str,
        event_type: str = "update",
        status: str = "active",
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
        )

    async def enqueue_project_share(
        self,
        project_id: str,
        *,
        source_node_id: str,
        source_version: int,
        target_hub: str,
        event_type: str = "update",
        status: str = "active",
    ) -> RelayShareProjectResponse:
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
                "SELECT id, payload_hash FROM relay_outbox WHERE idempotency_key = ?",
                (request.idempotency_key,),
            )
            if existing:
                if existing["payload_hash"] != request.payload_hash:
                    raise RelayIdempotencyConflict(
                        "outbox idempotency key reused with a different payload hash"
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
        backoff = min(300, 2 ** max(attempts - 1, 0))
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
            logger.exception("Relay outbox delivery failed for job %s", job.id)
            await self.mark_outbox_failed(job.id, str(exc))
            return RelayProcessResult(
                processed=False,
                job_id=job.id,
                error=str(exc),
            )

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
                return RelayIngestResponse(
                    accepted=True,
                    event_id=existing["id"],
                    current_memory_id=current["id"] if current else None,
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
            enrichment = RelayEnrichmentData.from_result(
                await text_enricher.enrich(content)
            )
            now = _utc_now()
            model = getattr(text_enricher, "model", "unknown")
            model_version = getattr(text_enricher, "model_version", model)
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
    ) -> RelaySearchResponse:
        """Simple visible-current search for the relay MVP.

        This is a safe fallback until relay sqlite-vec indexing is added. It
        keeps the read surface testable without pretending cross-corpus vector
        fusion is complete.
        """

        limit = max(1, min(limit, 50))
        if query and embedding_service is not None:
            vector_response = await self._search_vector(
                query=query,
                embedding_service=embedding_service,
                team_project_ids=team_project_ids,
                limit=limit,
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
        return current_memory_id

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
        backoff = min(300, 2 ** max(attempts - 1, 0))
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
        backoff = min(300, 2 ** max(attempts - 1, 0))
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

    async def _search_vector(
        self,
        *,
        query: str,
        embedding_service: Any,
        team_project_ids: Optional[Sequence[str]],
        limit: int,
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
            params: list[Any] = [_json_dumps(query_embedding), limit * 3]
            where = ["c.visible = 1"]
            if team_project_ids:
                placeholders = ",".join("?" for _ in team_project_ids)
                where.append(f"c.team_project_id IN ({placeholders})")
                params.extend(team_project_ids)
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
