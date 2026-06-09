"""OAuth Bearer Token Authentication Middleware."""

import logging
import secrets
from typing import Callable, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.auth.utils import parse_bearer_token
from app.core.config import (
    get_effective_bind_host,
    get_settings,
    resolve_hook_token,
)

logger = logging.getLogger(__name__)

# One-time guard so the "exposed without token" warning is logged once, not on
# every hook request. Reset is only needed in tests.
_exposure_warned = False


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


def warn_if_hook_exposed_without_token(host: Optional[str] = None) -> bool:
    """Emit a one-time WARNING when hook endpoints are open on a non-loopback bind.

    "Open" = no hook token configured. Uses the *effective* bind host (the host
    uvicorn actually bound to) rather than the static ``settings.server_host``.
    Returns whether the exposure condition holds (token unset + non-loopback),
    regardless of whether the warning was emitted this call (it logs at most
    once). Called both at server start and on the first unauthenticated hook
    request, so the notice surfaces whichever happens first.
    """
    effective = host if host is not None else get_effective_bind_host()
    exposed = resolve_hook_token() is None and not is_loopback_host(effective)
    if exposed:
        global _exposure_warned
        if not _exposure_warned:
            _exposure_warned = True
            logger.warning(
                "Hook write endpoints are exposed on non-loopback host %s "
                "WITHOUT a hook token; requests are accepted UNAUTHENTICATED. "
                "Set MEM_MESH_HOOK_TOKEN (or write ~/.mem-mesh/hook_token), or "
                "restrict access with a firewall.",
                effective,
            )
    return exposed


def verify_hook_token(request: Request) -> None:
    """FastAPI dependency guarding hook endpoints.

    Independent of ``auth_enabled`` / ``web_auth_enabled`` — runs even when all
    OAuth flags are off. Policy (loopback judged against the *effective* bind
    host, not the static ``settings.server_host``):

    * Token configured (env or ~/.mem-mesh/hook_token) → require a matching
      ``Authorization: Bearer <token>`` (constant-time compare), on any host.
    * No token configured + loopback bind → allow (local dev).
    * No token configured + non-loopback bind → **allow**, but emit a one-time
      prominent WARNING. A 0.0.0.0 bind is treated as a deliberate operator
      choice with the firewall as the trust boundary, not a fail-closed
      condition. (This intentionally reverses the earlier 401 fail-closed.)
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

    # Token unset: allow regardless of bind host; warn once if exposed.
    warn_if_hook_exposed_without_token()
    return


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
