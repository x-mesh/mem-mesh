"""Relay REST API routes."""

import json
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.core import runtime_config as rc
from app.core.config import get_settings
from app.core.errors import RelayInviteInvalid
from app.core.schemas.relay import (
    RelayAdminOverviewResponse,
    RelayAuthCheckResponse,
    RelayAutoShareListResponse,
    RelayAutoShareSubscription,
    RelayAutoShareUpdateRequest,
    RelayCancelResponse,
    RelayHealthResponse,
    RelayHubCheckRequest,
    RelayHubCheckResponse,
    RelayIdentityCreateRequest,
    RelayIdentityCreateResponse,
    RelayIdentityDeleteResponse,
    RelayIdentityRotateRequest,
    RelayIdentityUpdateRequest,
    RelayIngestRequest,
    RelayIngestResponse,
    RelayInviteCreateRequest,
    RelayInviteCreateResponse,
    RelayInviteDeleteResponse,
    RelayInviteListResponse,
    RelayMaterializeResponse,
    RelayPairConnectRequest,
    RelayPairConnectResponse,
    RelayPairRequest,
    RelayPairResponse,
    RelayProjectDigestResponse,
    RelayPurgeResponse,
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
    RelayHTTPClient,
    RelayIdempotencyConflict,
    RelaySecretBlocked,
    RelayService,
    RelayTypeGateBlocked,
    RelayUnauthorized,
)

from ...common.dependencies import get_database, get_embedding_service
from ...oauth.middleware import is_loopback_host

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/relay/v1", tags=["Relay"])


def _require_admin_access(request: Request) -> None:
    """Authorize destructive relay admin actions (purge / retry / materialize).

    Mirrors the dashboard secret-reveal policy (route_modules/security.py
    ``_can_reveal``): allow when OAuth web auth gated this request, when a
    logged-in Basic Auth dashboard session is attached, or when the caller is on
    loopback. Otherwise 403 — so a 0.0.0.0-exposed server with auth disabled
    never lets an unauthenticated remote caller trigger destructive admin ops,
    while the default local dashboard (loopback) keeps working without config.
    """

    if rc.effective_bool("auth_enabled") and rc.effective_tribool("web_auth_enabled"):
        return
    if getattr(request.state, "dashboard_session", None):
        return
    client = request.client.host if request.client else None
    if is_loopback_host(client):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "Relay admin actions require an authenticated dashboard session "
            "or loopback access"
        ),
    )


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


@router.get("/auth/check", response_model=RelayAuthCheckResponse)
async def check_relay_auth(
    authorization: Optional[str] = Header(default=None),
    service: RelayService = Depends(get_relay_service),
) -> RelayAuthCheckResponse:
    """Authenticate a relay token without side effects.

    Used by a personal node's 'Check Hub' to verify its hub token, not just
    reachability. Requires the ``write`` scope, since delivering to the hub
    (ingest) needs write — so a valid-but-read-only token still fails here.
    """

    token = _extract_bearer_token(authorization)
    try:
        identity = await service.authorize(token, require_scope="write")
    except RelayUnauthorized as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    raw_scopes = identity.get("scopes_json")
    try:
        scopes = (
            json.loads(raw_scopes)
            if isinstance(raw_scopes, str)
            else (raw_scopes or [])
        )
    except Exception:
        scopes = []
    return RelayAuthCheckResponse(
        ok=True,
        node_id=str(identity.get("source_node_id") or ""),
        user_id=str(identity.get("user_id") or ""),
        scopes=list(scopes),
    )


async def _resolve_share_defaults(
    service: RelayService,
    *,
    source_node_id: Optional[str],
    source_version: Optional[int],
    target_hub: Optional[str],
) -> tuple[str, Optional[int], str]:
    """Resolve hub_url/source_node_id (required, config-backed) and pass
    source_version through unresolved. Unlike the other two, source_version has
    no static default here — leaving it None lets the service layer derive it
    per-memory from updated_at (same as auto-share), instead of every share
    reusing one sticky version number and colliding on re-share after an edit.
    """
    effective = await service.get_effective_config(get_settings())
    values = effective["values"]
    resolved_source_node_id = source_node_id or values["source_node_id"]
    resolved_target_hub = target_hub or values["hub_url"]
    if not resolved_source_node_id:
        raise HTTPException(status_code=400, detail="Relay source node is not set")
    if not resolved_target_hub:
        raise HTTPException(status_code=400, detail="Relay team hub URL is not set")
    return resolved_source_node_id, source_version, resolved_target_hub


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
    _: None = Depends(_require_admin_access),
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
    _: None = Depends(_require_admin_access),
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
    _: None = Depends(_require_admin_access),
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


@router.post("/admin/cancel-dead-letters", response_model=RelayCancelResponse)
async def cancel_relay_admin_dead_letters(
    payload: RelayRetryRequest,
    _: None = Depends(_require_admin_access),
    service: RelayService = Depends(get_relay_service),
) -> RelayCancelResponse:
    """Discard dead-lettered relay jobs so they stop being retried or shown."""

    try:
        return await service.cancel_dead_letters(
            queue=payload.queue,
            job_id=payload.id,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Relay dead-letter cancel failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/admin/auto-share", response_model=RelayAutoShareListResponse)
async def list_relay_auto_share(
    _: None = Depends(_require_admin_access),
    service: RelayService = Depends(get_relay_service),
) -> RelayAutoShareListResponse:
    """List projects with continuous relay sharing enabled."""

    try:
        subscriptions = await service.list_auto_share_subscriptions()
        return RelayAutoShareListResponse(subscriptions=subscriptions)
    except Exception:
        logger.exception("Relay auto-share list failed")
        raise HTTPException(status_code=500, detail="Relay auto-share list failed")


@router.put("/admin/auto-share/{project_id}", response_model=RelayAutoShareSubscription)
async def set_relay_auto_share(
    project_id: str,
    payload: RelayAutoShareUpdateRequest,
    _: None = Depends(_require_admin_access),
    service: RelayService = Depends(get_relay_service),
) -> RelayAutoShareSubscription:
    """Enable or disable continuous relay sharing for a project."""

    try:
        return await service.set_project_auto_share(
            project_id,
            enabled=payload.enabled,
            include_relay_origin=payload.include_relay_origin,
            settings=get_settings(),
        )
    except Exception:
        logger.exception("Relay auto-share update failed")
        raise HTTPException(status_code=500, detail="Relay auto-share update failed")


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
    _: None = Depends(_require_admin_access),
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
    """Check hub reachability and, if a token is available, verify it too."""

    try:
        settings = get_settings()
        token = (payload.token or "").strip()
        if not token:
            # Fall back to the stored hub token so the check validates the
            # actually-configured credential even when the input is masked.
            effective = await service.get_effective_config(settings)
            token = str(effective["values"].get("hub_token") or "").strip()
        return await service.check_hub(
            payload.hub_url,
            token=token or None,
            timeout=settings.relay_http_timeout,
        )
    except Exception as exc:
        logger.exception("Relay hub check failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/admin/invites", response_model=RelayInviteListResponse)
async def list_relay_invites(
    _: None = Depends(_require_admin_access),
    service: RelayService = Depends(get_relay_service),
) -> RelayInviteListResponse:
    """List pairing invites issued by this hub."""

    try:
        return RelayInviteListResponse(invites=await service.list_invites())
    except Exception as exc:
        logger.exception("Relay invite list failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/admin/invites", response_model=RelayInviteCreateResponse)
async def create_relay_invite(
    payload: RelayInviteCreateRequest,
    request: Request,
    _: None = Depends(_require_admin_access),
    service: RelayService = Depends(get_relay_service),
) -> RelayInviteCreateResponse:
    """Issue a one-time pairing invite code (shown once — copy it immediately).

    The code embeds a hub URL so the redeeming node auto-fills its Team Hub URL
    from the code alone. Precedence: the per-invite ``hub_url`` (admin can edit
    it in the form), else the effective ``public_url`` setting, else the request
    origin.
    """

    try:
        settings = get_settings()
        effective = await service.get_effective_config(settings)
        default_hub = str(effective["values"].get("public_url") or "").strip()
        explicit_hub = (payload.hub_url or "").strip()
        hub_url = explicit_hub or default_hub or str(request.base_url).rstrip("/")
        invite, code = await service.create_invite(payload, hub_url=hub_url)
        # Remember the admin's entered hub URL as the default for next time.
        if explicit_hub and explicit_hub != default_hub:
            await service.update_admin_settings(
                RelaySettingsUpdateRequest(public_url=explicit_hub)
            )
        return RelayInviteCreateResponse(invite=invite, code=code)
    except Exception as exc:
        logger.exception("Relay invite creation failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/admin/invites/{code_prefix}", response_model=RelayInviteDeleteResponse)
async def delete_relay_invite(
    code_prefix: str,
    _: None = Depends(_require_admin_access),
    service: RelayService = Depends(get_relay_service),
) -> RelayInviteDeleteResponse:
    """Revoke a pairing invite by its visible code prefix."""

    try:
        removed = await service.delete_invite(code_prefix)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.exception("Relay invite delete failed")
        raise HTTPException(status_code=500, detail=str(exc))
    if not removed:
        raise HTTPException(status_code=404, detail="Relay invite not found")
    return RelayInviteDeleteResponse(ok=True, code_prefix=code_prefix)


@router.post("/pair", response_model=RelayPairResponse)
async def pair_relay_node(
    payload: RelayPairRequest,
    service: RelayService = Depends(get_relay_service),
) -> RelayPairResponse:
    """Redeem a one-time invite code for a node identity + bearer token.

    Public by design: the invite code itself is the credential (single-use,
    TTL-bounded, hash-stored — the same trust model as the bearer tokens it
    mints).
    """

    try:
        return await service.redeem_invite(payload)
    except RelayInviteInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Relay pairing failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/admin/pair", response_model=RelayPairConnectResponse)
async def connect_relay_node_with_invite(
    payload: RelayPairConnectRequest,
    _: None = Depends(_require_admin_access),
    service: RelayService = Depends(get_relay_service),
) -> RelayPairConnectResponse:
    """Personal-node side of pairing: redeem an invite against the hub and
    self-configure hub_url / hub_token / source_node_id in one step."""

    settings = get_settings()
    hub_url = payload.hub_url.strip()
    client = RelayHTTPClient(timeout=settings.relay_http_timeout)
    try:
        pair = await client.send_pair(
            target_hub=hub_url,
            payload=RelayPairRequest(
                code=payload.code,
                source_node_id=payload.source_node_id,
            ),
        )
    except RelayInviteInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Relay pairing request failed")
        raise HTTPException(status_code=502, detail=f"hub unreachable: {exc}")

    try:
        await service.update_admin_settings(
            RelaySettingsUpdateRequest(
                hub_url=hub_url,
                hub_token=pair.token,
                source_node_id=pair.source_node_id,
            )
        )
    except Exception as exc:
        logger.exception("Relay pairing settings persist failed")
        raise HTTPException(
            status_code=500, detail=f"paired but saving settings failed: {exc}"
        )

    check: Optional[RelayHubCheckResponse] = None
    try:
        check = await service.check_hub(
            hub_url, token=pair.token, timeout=settings.relay_http_timeout
        )
    except Exception:
        logger.warning("Relay pairing post-check failed", exc_info=True)

    return RelayPairConnectResponse(
        ok=True,
        hub_url=hub_url,
        source_node_id=pair.source_node_id,
        user_id=pair.user_id,
        scopes=pair.scopes,
        message="paired — hub URL, token, and source node id saved",
        check=check,
    )


@router.post("/admin/identities", response_model=RelayIdentityCreateResponse)
async def create_relay_identity(
    payload: RelayIdentityCreateRequest,
    _: None = Depends(_require_admin_access),
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
    _: None = Depends(_require_admin_access),
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


@router.delete(
    "/admin/identities/{token_hash_prefix}",
    response_model=RelayIdentityDeleteResponse,
)
async def delete_relay_identity(
    token_hash_prefix: str,
    _: None = Depends(_require_admin_access),
    service: RelayService = Depends(get_relay_service),
) -> RelayIdentityDeleteResponse:
    """Permanently remove a hub identity (hard delete; PUT with revoked=true is
    the reversible soft alternative)."""

    try:
        removed = await service.delete_identity(token_hash_prefix)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.exception("Relay identity delete failed")
        raise HTTPException(status_code=500, detail=str(exc))
    if not removed:
        raise HTTPException(status_code=404, detail="Relay identity not found")
    return RelayIdentityDeleteResponse(ok=True, token_hash_prefix=token_hash_prefix)


@router.post(
    "/admin/identities/{token_hash_prefix}/rotate",
    response_model=RelayIdentityCreateResponse,
)
async def rotate_relay_identity(
    token_hash_prefix: str,
    payload: RelayIdentityRotateRequest,
    _: None = Depends(_require_admin_access),
    service: RelayService = Depends(get_relay_service),
) -> RelayIdentityCreateResponse:
    """Rotate an identity's token (metadata kept, old token invalidated at once).

    The new token is returned once when generated — copy it immediately.
    """

    try:
        rotated = await service.rotate_identity(
            token_hash_prefix, new_token=payload.token
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.exception("Relay identity rotation failed")
        raise HTTPException(status_code=500, detail=str(exc))
    if rotated is None:
        raise HTTPException(status_code=404, detail="Relay identity not found")
    identity, token, generated = rotated
    return RelayIdentityCreateResponse(
        identity=identity,
        token=token if generated else None,
        token_generated=generated,
        token_hash_prefix=identity.token_hash_prefix,
    )


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
            exclude_source_node=payload.exclude_source_node,
            kinds=payload.kinds,
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
    _: None = Depends(_require_admin_access),
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
    _: None = Depends(_require_admin_access),
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
