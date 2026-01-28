"""OAuth 2.1 endpoints per MCP 2025-03-26 spec."""

import time
import logging
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Request, HTTPException, Form, Query, Depends
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.config import get_settings
from app.core.auth import OAuthService
from app.core.auth.schemas import (
    OAuthMetadata,
    OAuthAuthorizeRequest,
    OAuthTokenRequest,
    OAuthTokenResponse,
    OAuthTokenError,
    OAuthClientRegistrationRequest,
    OAuthClientRegistrationResponse,
    OAuthClientCreate,
    OAuthTokenRevokeRequest,
    OAuthTokenIntrospectResponse,
)
from app.core.auth.service import (
    OAuthError,
    InvalidClientError,
    InvalidGrantError,
    InvalidRequestError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["OAuth"])


def get_oauth_service(request: Request) -> OAuthService:
    return request.app.state.oauth_service


@router.get("/.well-known/oauth-authorization-server")
async def oauth_metadata(request: Request) -> OAuthMetadata:
    """OAuth Authorization Server Metadata (RFC 8414)."""
    settings = get_settings()
    base_url = settings.oauth_issuer

    return OAuthMetadata(
        issuer=base_url,
        authorization_endpoint=f"{base_url}/oauth/authorize",
        token_endpoint=f"{base_url}/oauth/token",
        registration_endpoint=f"{base_url}/oauth/register",
        revocation_endpoint=f"{base_url}/oauth/revoke",
        introspection_endpoint=f"{base_url}/oauth/introspect",
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        token_endpoint_auth_methods_supported=["none", "client_secret_post"],
        code_challenge_methods_supported=["S256"],
        scopes_supported=["read", "write"],
        service_documentation=f"{base_url}/docs",
    )


@router.get("/oauth/authorize")
async def authorize(
    request: Request,
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query(default="S256"),
    scope: Optional[str] = Query(default="read write"),
    state: Optional[str] = Query(default=None),
    service: OAuthService = Depends(get_oauth_service),
):
    """Authorization endpoint - issues authorization codes."""
    if response_type != "code":
        return _redirect_with_error(
            redirect_uri,
            "unsupported_response_type",
            "Only 'code' response type is supported",
            state,
        )

    try:
        scopes = scope.split() if scope else ["read", "write"]

        auth_code = await service.create_authorization_code(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scopes=scopes,
            state=state,
        )

        params = {"code": auth_code.code}
        if state:
            params["state"] = state

        return RedirectResponse(
            url=f"{redirect_uri}?{urlencode(params)}",
            status_code=302,
        )

    except InvalidClientError as e:
        return _redirect_with_error(
            redirect_uri, "invalid_client", e.description, state
        )
    except InvalidRequestError as e:
        return _redirect_with_error(
            redirect_uri, "invalid_request", e.description, state
        )
    except Exception as e:
        logger.error(f"Authorization error: {e}")
        return _redirect_with_error(redirect_uri, "server_error", str(e), state)


@router.post("/oauth/token")
async def token(
    request: Request,
    grant_type: str = Form(...),
    code: Optional[str] = Form(default=None),
    redirect_uri: Optional[str] = Form(default=None),
    code_verifier: Optional[str] = Form(default=None),
    refresh_token: Optional[str] = Form(default=None),
    client_id: Optional[str] = Form(default=None),
    client_secret: Optional[str] = Form(default=None),
    scope: Optional[str] = Form(default=None),
    service: OAuthService = Depends(get_oauth_service),
):
    """Token endpoint - exchanges codes for tokens."""
    try:
        token_request = OAuthTokenRequest(
            grant_type=grant_type,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            scope=scope,
        )

        response = await service.process_token_request(token_request)
        return response

    except OAuthError as e:
        return JSONResponse(
            status_code=400,
            content=OAuthTokenError(
                error=e.error, error_description=e.description
            ).model_dump(),
        )
    except Exception as e:
        logger.error(f"Token error: {e}")
        return JSONResponse(
            status_code=500,
            content=OAuthTokenError(
                error="server_error", error_description=str(e)
            ).model_dump(),
        )


@router.post("/oauth/register")
async def register_client(
    request: Request,
    registration: OAuthClientRegistrationRequest,
    service: OAuthService = Depends(get_oauth_service),
):
    """Dynamic Client Registration (RFC 7591)."""
    try:
        scopes = registration.scope.split() if registration.scope else ["read", "write"]

        client_params = OAuthClientCreate(
            client_name=registration.client_name,
            redirect_uris=registration.redirect_uris,
            scopes=scopes,
            grant_types=registration.grant_types,
            client_type="public"
            if registration.token_endpoint_auth_method == "none"
            else "confidential",
        )

        client, plain_secret = await service.create_client(client_params)

        return OAuthClientRegistrationResponse(
            client_id=client.client_id,
            client_secret=plain_secret
            if client.client_type == "confidential"
            else None,
            client_id_issued_at=int(time.time()),
            client_secret_expires_at=0,
            client_name=client.client_name,
            redirect_uris=client.get_redirect_uris(),
            grant_types=client.get_grant_types(),
            token_endpoint_auth_method=registration.token_endpoint_auth_method,
            scope=" ".join(client.get_scopes()),
        )

    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/oauth/revoke")
async def revoke_token(
    request: Request,
    token: str = Form(...),
    token_type_hint: Optional[str] = Form(default=None),
    service: OAuthService = Depends(get_oauth_service),
):
    """Token Revocation (RFC 7009)."""
    await service.revoke_token(token, token_type_hint)
    return JSONResponse(status_code=200, content={})


@router.post("/oauth/introspect")
async def introspect_token(
    request: Request,
    token: str = Form(...),
    token_type_hint: Optional[str] = Form(default=None),
    service: OAuthService = Depends(get_oauth_service),
):
    """Token Introspection (RFC 7662)."""
    token_info = await service.validate_access_token(token)

    if not token_info:
        return OAuthTokenIntrospectResponse(active=False)

    from datetime import datetime

    exp_dt = datetime.fromisoformat(token_info.access_token_expires_at.rstrip("Z"))
    created_dt = datetime.fromisoformat(token_info.created_at.rstrip("Z"))

    return OAuthTokenIntrospectResponse(
        active=True,
        scope=" ".join(token_info.get_scopes()),
        client_id=token_info.client_id,
        exp=int(exp_dt.timestamp()),
        iat=int(created_dt.timestamp()),
    )


def _redirect_with_error(
    redirect_uri: str, error: str, description: str, state: Optional[str] = None
) -> RedirectResponse:
    params = {"error": error, "error_description": description}
    if state:
        params["state"] = state
    return RedirectResponse(
        url=f"{redirect_uri}?{urlencode(params)}",
        status_code=302,
    )
