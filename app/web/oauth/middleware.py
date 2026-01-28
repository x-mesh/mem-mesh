"""OAuth Bearer Token Authentication Middleware."""

import logging
from typing import Optional, Callable

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.auth.utils import parse_bearer_token

logger = logging.getLogger(__name__)


OAUTH_PATHS = [
    "/.well-known/oauth-authorization-server",
    "/oauth/authorize",
    "/oauth/token",
    "/oauth/register",
    "/oauth/revoke",
    "/oauth/introspect",
]

PUBLIC_PATHS = [
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/static",
    "/favicon.ico",
]


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Middleware to validate Bearer tokens on protected routes."""

    async def dispatch(self, request: Request, call_next: Callable):
        settings = get_settings()
        path = request.url.path

        if not self._requires_auth(path, settings):
            return await call_next(request)

        authorization = request.headers.get("Authorization")
        token = parse_bearer_token(authorization)

        if not token:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "error_description": "Missing or invalid Authorization header",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

        oauth_service = getattr(request.app.state, "oauth_service", None)
        if not oauth_service:
            logger.error("OAuth service not initialized")
            return await call_next(request)

        token_info = await oauth_service.validate_access_token(token)

        if not token_info:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "invalid_token",
                    "error_description": "Token is invalid or expired",
                },
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )

        request.state.oauth_token = token_info
        request.state.oauth_client_id = token_info.client_id
        request.state.oauth_scopes = token_info.get_scopes()

        return await call_next(request)

    def _requires_auth(self, path: str, settings) -> bool:
        if not settings.auth_enabled:
            return False

        for public_path in PUBLIC_PATHS:
            if path.startswith(public_path):
                return False

        for oauth_path in OAUTH_PATHS:
            if path == oauth_path or path.startswith(oauth_path):
                return False

        if path.startswith("/mcp/"):
            return settings.mcp_auth_enabled

        if path.startswith("/api/"):
            return settings.web_auth_enabled

        return False


def require_scope(required_scope: str):
    """Dependency to require specific OAuth scope."""

    async def check_scope(request: Request):
        scopes = getattr(request.state, "oauth_scopes", [])
        if required_scope not in scopes:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient scope. Required: {required_scope}",
            )
        return scopes

    return check_scope


def get_current_client(request: Request) -> Optional[str]:
    """Get authenticated client ID from request."""
    return getattr(request.state, "oauth_client_id", None)


def get_current_scopes(request: Request) -> list:
    """Get authenticated scopes from request."""
    return getattr(request.state, "oauth_scopes", [])
