"""Relay REST API routes."""

import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.config import get_settings
from app.core.schemas.relay import (
    RelayAdminOverviewResponse,
    RelayIdentityCreateRequest,
    RelayIdentityCreateResponse,
    RelayIngestRequest,
    RelayIngestResponse,
    RelayProjectDigestResponse,
    RelaySearchRequest,
    RelaySearchResponse,
    RelaySettingsResponse,
    RelaySettingsUpdateRequest,
    RelayShareMemoryRequest,
    RelayShareMemoryResponse,
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


@router.post("/ingest", response_model=RelayIngestResponse)
async def ingest_relay_event(
    payload: RelayIngestRequest,
    authorization: Optional[str] = Header(default=None),
    service: RelayService = Depends(get_relay_service),
) -> RelayIngestResponse:
    """Accept one deterministic relay event from a personal node."""

    token = _extract_bearer_token(authorization)
    try:
        return await service.ingest(token, payload)
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
        outbox_id = await service.enqueue_memory_share_by_id(
            memory_id,
            source_node_id=payload.source_node_id,
            source_version=payload.source_version,
            target_hub=payload.target_hub,
            event_type=payload.event_type,
            status=payload.status,
        )
        return RelayShareMemoryResponse(outbox_id=outbox_id)
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
