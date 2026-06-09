"""OAuth Bearer Token Authentication Middleware."""

import logging
import secrets
from typing import Callable, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.auth.utils import parse_bearer_token
from app.core.config import get_settings, resolve_hook_token

logger = logging.getLogger(__name__)


# Hook endpoints carry their own shared-secret scheme (verify_hook_token) that
# is independent of the OAuth web_auth flag, so the OAuth middleware must not
# also gate them — otherwise a valid hook token would be rejected as a
# non-OAuth bearer when web_auth_enabled is on.
HOOK_PATH_PREFIX = "/api/hooks/claude"


def is_loopback_host(host: Optional[str]) -> bool:
    """True if ``host`` only accepts connections from the local machine.

    Treats ``127.0.0.0/8``, ``::1`` and ``localhost`` as loopback. ``0.0.0.0``,
    ``::`` and any concrete address/hostname are non-loopback (network-exposed).
    An empty/unknown host is treated as non-loopback (fail-safe).
    """
    if not host:
        return False
    h = host.strip().lower()
    if h in ("localhost", "::1", "::ffff:127.0.0.1"):
        return True
    return h.startswith("127.")


def verify_hook_token(request: Request) -> None:
    """FastAPI dependency guarding hook write endpoints.

    Independent of ``auth_enabled`` / ``web_auth_enabled`` — runs even when all
    OAuth flags are off. Rules:

    * Token configured (env or ~/.mem-mesh/hook_token) → require a matching
      ``Authorization: Bearer <token>`` (constant-time compare).
    * No token configured + server bound to loopback → allow (local dev
      backward-compat; the port is unreachable from the network).
    * No token configured + server bound to a non-loopback address →
      reject 401 (fail-closed): an exposed server must not accept anonymous
      memory writes.
    """
    configured = resolve_hook_token()
    provided = parse_bearer_token(request.headers.get("Authorization"))

    if configured:
        if not provided or not secrets.compare_digest(provided, configured):
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing hook token",
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )
        return

    if is_loopback_host(get_settings().server_host):
        return

    raise HTTPException(
        status_code=401,
        detail=(
            "Hook token required: server is bound to a non-loopback address. "
            "Set MEM_MESH_HOOK_TOKEN or write ~/.mem-mesh/hook_token."
        ),
        headers={"WWW-Authenticate": "Bearer"},
    )


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
        """
        Determine if a path requires authentication.

        Logic:
        1. If auth_enabled=False, no authentication required anywhere
        2. Public paths (health, docs, static) are always exempt
        3. OAuth paths are always exempt (needed for auth flow)
        4. For /mcp/* paths: use mcp_auth_enabled (defaults to auth_enabled)
        5. For /api/* paths: use web_auth_enabled (defaults to auth_enabled)
        6. For dashboard pages: use web_auth_enabled (defaults to auth_enabled)
        """
        # Global auth disabled = no auth anywhere
        if not settings.auth_enabled:
            return False

        # Hook endpoints use their own token scheme (verify_hook_token), which
        # runs as a route dependency regardless of OAuth flags. Exempt them here
        # so a hook bearer token is not rejected by the OAuth validator.
        if path.startswith(HOOK_PATH_PREFIX):
            return False

        # Public paths are always exempt
        for public_path in PUBLIC_PATHS:
            if path.startswith(public_path):
                return False

        # OAuth paths are always exempt (needed for auth flow)
        for oauth_path in OAUTH_PATHS:
            if path == oauth_path or path.startswith(oauth_path):
                return False

        # MCP endpoints: check mcp_auth_enabled
        # When auth_enabled=True and mcp_auth_enabled is not explicitly set,
        # it defaults to False (opt-in for MCP auth)
        if path.startswith("/mcp/"):
            return settings.mcp_auth_enabled

        # API endpoints: check web_auth_enabled
        # When auth_enabled=True and web_auth_enabled is not explicitly set,
        # it defaults to False (opt-in for Web API auth)
        if path.startswith("/api/"):
            return settings.web_auth_enabled

        # Dashboard pages (/, /work, /oauth, etc.): follow web_auth_enabled
        # This ensures dashboard pages are protected when web auth is enabled
        return settings.web_auth_enabled


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
