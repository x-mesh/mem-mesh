"""Relay REST API routes."""

import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.config import get_settings
from app.core.schemas.relay import (
    RelayAdminOverviewResponse,
    RelayHealthResponse,
    RelayHubCheckRequest,
    RelayHubCheckResponse,
    RelayIdentityCreateRequest,
    RelayIdentityCreateResponse,
    RelayIdentityUpdateRequest,
    RelayIngestRequest,
    RelayIngestResponse,
    RelayMaterializeResponse,
    RelayPurgeResponse,
    RelayProjectDigestResponse,
    RelayRetryRequest,
    RelayRetryResponse,
    RelaySearchRequest,
    RelaySearchResponse,
    RelaySettingsResponse,
    RelaySettingsUpdateRequest,
    RelayShareMemoryRequest,
    RelayShareMemoryResponse,
    RelayShareProjectRequest,
    RelayShareProjectResponse,
)
from app.core.services.relay import (
    RelayIdempotencyConflict,
    RelaySecretBlocked,
    RelayService,
    RelayTypeGateBlocked,
    RelayUnauthorized,
)

from ...common.dependencies import get_database, get_embedding_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/relay/v1", tags=["Relay"])


async def get_relay_service(db=Depends(get_database)) -> RelayService:
    service = RelayService(db)
    await service.ensure_schema()
    return service


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Expected Bearer token")
    return token


@router.get("/health", response_model=RelayHealthResponse)
async def get_relay_health() -> RelayHealthResponse:
    """Lightweight public health endpoint for personal-node hub checks."""

    return RelayHealthResponse()


async def _resolve_share_defaults(
    service: RelayService,
    *,
    source_node_id: Optional[str],
    source_version: Optional[int],
    target_hub: Optional[str],
) -> tuple[str, int, str]:
    effective = await service.get_effective_config(get_settings())
    values = effective["values"]
    resolved_source_node_id = source_node_id or values["source_node_id"]
    resolved_target_hub = target_hub or values["hub_url"]
    resolved_source_version = (
        source_version
        if source_version is not None
        else values["default_source_version"]
    )
    if not resolved_source_node_id:
        raise HTTPException(status_code=400, detail="Relay source node is not set")
    if not resolved_target_hub:
        raise HTTPException(status_code=400, detail="Relay team hub URL is not set")
    return resolved_source_node_id, resolved_source_version, resolved_target_hub


@router.get("/admin/overview", response_model=RelayAdminOverviewResponse)
async def get_relay_admin_overview(
    limit: int = 10,
    service: RelayService = Depends(get_relay_service),
) -> RelayAdminOverviewResponse:
    """Return relay queue and digest status for the dashboard admin UI."""

    try:
        return await service.get_admin_overview(limit=limit)
    except Exception as exc:
        logger.exception("Relay admin overview failed")
        raise HTTPException(status_code=500, detail=str(exc))


async def _notify_relay_projection(
    service: RelayService,
    *,
    action: str,
    current_memory_id: str,
    memory_event: str,
    extra: Optional[dict] = None,
) -> None:
    try:
        from ...websocket.realtime import notifier

        snapshot = await service.get_relay_notification_snapshot(current_memory_id)
        payload = {
            "action": action,
            **snapshot,
            **(extra or {}),
        }
        await notifier.notify_relay_ingested(payload)

        memory_id = str(snapshot["materialized_memory_id"])
        relay_memory = snapshot.get("relay_memory") or {}
        memory = snapshot.get("memory")
        if memory_event == "deleted":
            await notifier.notify_memory_deleted(
                memory_id, relay_memory.get("team_project_id")
            )
        elif memory_event == "created" and memory:
            await notifier.notify_memory_created(memory)
        elif memory_event == "updated" and memory:
            await notifier.notify_memory_updated(memory_id, memory)
    except Exception as exc:
        logger.warning("Relay realtime notification failed: %s", exc)


async def _notify_relay_materialized(result: RelayMaterializeResponse) -> None:
    try:
        from ...websocket.realtime import notifier

        await notifier.notify_relay_materialized(result.model_dump())
    except Exception as exc:
        logger.warning("Relay materialize notification failed: %s", exc)


@router.post("/admin/materialize", response_model=RelayMaterializeResponse)
async def materialize_relay_admin_memories(
    limit: int = 1000,
    service: RelayService = Depends(get_relay_service),
) -> RelayMaterializeResponse:
    """Backfill visible relay current rows into ordinary memories."""

    try:
        result = await service.materialize_current_memories(limit=limit)
        await _notify_relay_materialized(result)
        return result
    except Exception as exc:
        logger.exception("Relay memory materialization failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/admin/purge-current", response_model=RelayPurgeResponse)
async def purge_relay_admin_current_memories(
    limit: int = 10000,
    service: RelayService = Depends(get_relay_service),
) -> RelayPurgeResponse:
    """Hide visible relay current rows so materialize cannot recreate them."""

    try:
        return await service.purge_current_memories(limit=limit)
    except Exception as exc:
        logger.exception("Relay current purge failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/admin/retry-dead-letters", response_model=RelayRetryResponse)
async def retry_relay_admin_dead_letters(
    payload: RelayRetryRequest,
    service: RelayService = Depends(get_relay_service),
) -> RelayRetryResponse:
    """Move dead-lettered relay jobs back to pending."""

    try:
        return await service.retry_dead_letters(
            queue=payload.queue,
            job_id=payload.id,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Relay dead-letter retry failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/admin/settings", response_model=RelaySettingsResponse)
async def get_relay_admin_settings(
    service: RelayService = Depends(get_relay_service),
) -> RelaySettingsResponse:
    """Return dashboard-managed relay settings and worker configuration state."""

    try:
        return await service.get_admin_settings(get_settings())
    except Exception as exc:
        logger.exception("Relay admin settings failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/admin/settings", response_model=RelaySettingsResponse)
async def update_relay_admin_settings(
    payload: RelaySettingsUpdateRequest,
    service: RelayService = Depends(get_relay_service),
) -> RelaySettingsResponse:
    """Update relay defaults used by the dashboard share UI."""

    try:
        return await service.update_admin_settings(payload)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.exception("Relay admin settings update failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/admin/hub/check", response_model=RelayHubCheckResponse)
async def check_relay_hub(
    payload: RelayHubCheckRequest,
    service: RelayService = Depends(get_relay_service),
) -> RelayHubCheckResponse:
    """Check whether a configured team hub URL exposes relay health."""

    try:
        return await service.check_hub(
            payload.hub_url,
            timeout=get_settings().relay_http_timeout,
        )
    except Exception as exc:
        logger.exception("Relay hub check failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/admin/identities", response_model=RelayIdentityCreateResponse)
async def create_relay_identity(
    payload: RelayIdentityCreateRequest,
    service: RelayService = Depends(get_relay_service),
) -> RelayIdentityCreateResponse:
    """Register a source node token in the team hub identity registry."""

    token_generated = payload.token is None
    token = payload.token or secrets.token_urlsafe(32)
    try:
        token_hash = await service.register_identity(
            token=token,
            user_id=payload.user_id,
            source_node_id=payload.source_node_id,
            display_name=payload.display_name,
            home_domain=payload.home_domain,
            scopes=payload.scopes,
        )
        identity = await service.get_identity(token_hash)
        if identity is None:
            raise RuntimeError("registered relay identity could not be loaded")
        return RelayIdentityCreateResponse(
            identity=identity,
            token=token if token_generated else None,
            token_generated=token_generated,
            token_hash_prefix=identity.token_hash_prefix,
        )
    except Exception as exc:
        logger.exception("Relay identity registration failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.put(
    "/admin/identities/{token_hash_prefix}", response_model=RelayIdentityCreateResponse
)
async def update_relay_identity(
    token_hash_prefix: str,
    payload: RelayIdentityUpdateRequest,
    service: RelayService = Depends(get_relay_service),
) -> RelayIdentityCreateResponse:
    """Update a hub identity by its visible token hash prefix."""

    try:
        identity = await service.update_identity(token_hash_prefix, payload)
        if identity is None:
            raise HTTPException(status_code=404, detail="Relay identity not found")
        return RelayIdentityCreateResponse(
            identity=identity,
            token=None,
            token_generated=False,
            token_hash_prefix=identity.token_hash_prefix,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.exception("Relay identity update failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/ingest", response_model=RelayIngestResponse)
async def ingest_relay_event(
    payload: RelayIngestRequest,
    authorization: Optional[str] = Header(default=None),
    service: RelayService = Depends(get_relay_service),
) -> RelayIngestResponse:
    """Accept one deterministic relay event from a personal node."""

    token = _extract_bearer_token(authorization)
    try:
        result = await service.ingest(token, payload)
        if result.current_memory_id:
            memory_event = "none"
            if result.applied_to_current:
                if payload.event_type == "retract":
                    memory_event = "deleted"
                elif result.current_created:
                    memory_event = "created"
                else:
                    memory_event = "updated"
            elif result.replayed:
                memory_event = "updated"
            await _notify_relay_projection(
                service,
                action=payload.event_type,
                current_memory_id=result.current_memory_id,
                memory_event=memory_event,
                extra={
                    "event_id": result.event_id,
                    "replayed": result.replayed,
                    "applied_to_current": result.applied_to_current,
                    "queued_item": result.queued_item,
                },
            )
        return result
    except RelayUnauthorized as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except RelayIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RelaySecretBlocked as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Relay ingest failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/search", response_model=RelaySearchResponse)
async def search_relay_view(
    payload: RelaySearchRequest,
    authorization: Optional[str] = Header(default=None),
    service: RelayService = Depends(get_relay_service),
    embedding_service=Depends(get_embedding_service),
) -> RelaySearchResponse:
    """Search the team relay view."""

    token = _extract_bearer_token(authorization)
    try:
        await service.authorize(token, require_scope="read")
        return await service.search(
            query=payload.query,
            team_project_ids=payload.team_project_ids,
            limit=payload.limit,
            embedding_service=embedding_service,
        )
    except RelayUnauthorized as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.exception("Relay search failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/projects/{team_project_id}/digest",
    response_model=RelayProjectDigestResponse,
)
async def get_project_digest(
    team_project_id: str,
    authorization: Optional[str] = Header(default=None),
    service: RelayService = Depends(get_relay_service),
) -> RelayProjectDigestResponse:
    """Return the latest bounded-stale relay project digest."""

    token = _extract_bearer_token(authorization)
    try:
        await service.authorize(token, require_scope="read")
        digest = await service.get_project_digest(team_project_id)
        if digest is None:
            raise HTTPException(status_code=404, detail="Relay digest not found")
        return digest
    except HTTPException:
        raise
    except RelayUnauthorized as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        logger.exception("Relay digest fetch failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/outbox/share/{memory_id}",
    response_model=RelayShareMemoryResponse,
)
async def share_memory_to_relay_outbox(
    memory_id: str,
    payload: RelayShareMemoryRequest,
    service: RelayService = Depends(get_relay_service),
) -> RelayShareMemoryResponse:
    """Queue an existing local memory for relay delivery."""

    try:
        source_node_id, source_version, target_hub = await _resolve_share_defaults(
            service,
            source_node_id=payload.source_node_id,
            source_version=payload.source_version,
            target_hub=payload.target_hub,
        )
        outbox_id = await service.enqueue_memory_share_by_id(
            memory_id,
            source_node_id=source_node_id,
            source_version=source_version,
            target_hub=target_hub,
            event_type=payload.event_type,
            status=payload.status,
            force=payload.force,
        )
        return RelayShareMemoryResponse(
            outbox_id=outbox_id,
            target_hub=target_hub,
            source_node_id=source_node_id,
        )
    except HTTPException:
        raise
    except KeyError:
        raise HTTPException(status_code=404, detail="Memory not found")
    except RelayTypeGateBlocked as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except RelaySecretBlocked as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RelayIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.exception("Relay share enqueue failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/outbox/share-project/{project_id}",
    response_model=RelayShareProjectResponse,
)
async def share_project_to_relay_outbox(
    project_id: str,
    payload: RelayShareProjectRequest,
    service: RelayService = Depends(get_relay_service),
) -> RelayShareProjectResponse:
    """Queue all shareable local memories in a project for relay delivery."""

    try:
        source_node_id, source_version, target_hub = await _resolve_share_defaults(
            service,
            source_node_id=payload.source_node_id,
            source_version=payload.source_version,
            target_hub=payload.target_hub,
        )
        return await service.enqueue_project_share(
            project_id,
            source_node_id=source_node_id,
            source_version=source_version,
            target_hub=target_hub,
            event_type=payload.event_type,
            status=payload.status,
            force=payload.force,
        )
    except HTTPException:
        raise
    except KeyError:
        raise HTTPException(status_code=404, detail="Project has no memories")
    except RelayIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.exception("Relay project share enqueue failed")
        raise HTTPException(status_code=500, detail=str(exc))
