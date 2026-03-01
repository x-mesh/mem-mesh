"""Dashboard OAuth Client Management API."""

import logging

from fastapi import APIRouter, Request, HTTPException, Depends

from app.core.auth import OAuthService
from app.core.auth.schemas import (
    OAuthClientCreate,
    OAuthClientUpdate,
    OAuthClientResponse,
    OAuthClientWithSecretResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth", tags=["OAuth Management"])


def get_oauth_service(request: Request) -> OAuthService:
    service = getattr(request.app.state, "oauth_service", None)
    if not service:
        raise HTTPException(status_code=503, detail="OAuth service not available")
    return service


@router.get("/clients")
async def list_oauth_clients(
    include_inactive: bool = False,
    limit: int = 50,
    offset: int = 0,
    service: OAuthService = Depends(get_oauth_service),
):
    """List all OAuth clients."""
    clients = await service.list_clients(
        include_inactive=include_inactive,
        limit=limit,
        offset=offset,
    )
    return {
        "clients": [service.client_to_response(c) for c in clients],
        "total": len(clients),
    }


@router.post("/clients", response_model=OAuthClientWithSecretResponse)
async def create_oauth_client(
    params: OAuthClientCreate,
    service: OAuthService = Depends(get_oauth_service),
):
    """Create a new OAuth client. Returns client_secret only once."""
    try:
        client, plain_secret = await service.create_client(params)
        return service.client_to_response_with_secret(client, plain_secret)
    except Exception as e:
        logger.error(f"Create OAuth client error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/clients/{client_id}", response_model=OAuthClientResponse)
async def get_oauth_client(
    client_id: str,
    service: OAuthService = Depends(get_oauth_service),
):
    """Get OAuth client details."""
    client = await service.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return service.client_to_response(client)


@router.put("/clients/{client_id}", response_model=OAuthClientResponse)
async def update_oauth_client(
    client_id: str,
    params: OAuthClientUpdate,
    service: OAuthService = Depends(get_oauth_service),
):
    """Update OAuth client."""
    client = await service.update_client(client_id, params)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return service.client_to_response(client)


@router.delete("/clients/{client_id}")
async def delete_oauth_client(
    client_id: str,
    service: OAuthService = Depends(get_oauth_service),
):
    """Delete (deactivate) OAuth client."""
    success = await service.delete_client(client_id)
    if not success:
        raise HTTPException(status_code=404, detail="Client not found")

    await service.revoke_all_client_tokens(client_id)
    return {"success": True, "client_id": client_id}


@router.post("/clients/{client_id}/regenerate-secret")
async def regenerate_client_secret(
    client_id: str,
    service: OAuthService = Depends(get_oauth_service),
):
    """Regenerate client secret. Returns new secret only once."""
    new_secret = await service.regenerate_client_secret(client_id)
    if not new_secret:
        raise HTTPException(status_code=404, detail="Client not found")

    await service.revoke_all_client_tokens(client_id)

    return {
        "client_id": client_id,
        "client_secret": new_secret,
        "message": "All existing tokens have been revoked",
    }


@router.post("/clients/{client_id}/revoke-tokens")
async def revoke_client_tokens(
    client_id: str,
    service: OAuthService = Depends(get_oauth_service),
):
    """Revoke all tokens for a client."""
    client = await service.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    count = await service.revoke_all_client_tokens(client_id)
    return {"client_id": client_id, "revoked_count": count}
