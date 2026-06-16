"""Dashboard Connect API — copy-paste client config (hooks + MCP).

Wraps the CLI renderers (``install_hooks`` / ``mcp_config``) so the browser can
produce ready-to-paste settings with the server's real URL and hook token filled
in. This eliminates the token-mismatch / wrong-URL class of setup errors (the
exact failures ``doctor`` reports) — the server knows its own URL and token, so
the operator never hand-edits them.

The plaintext hook token is gated by the same reveal policy as the security
routes (authenticated surface or loopback); otherwise only a masked value is
returned. Responses are ``no-store``.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, Response

from app.core import runtime_config as rc
from app.core.config import resolve_hook_token

from .security import _can_reveal, _mask

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connect", tags=["Connect"])

# Where each client's config lives (shown as paste-target guidance).
_HOOK_SETTINGS_PATH = {
    "claude": "~/.claude/settings.json",
    "cursor": "~/.cursor/settings.json (hooks)",
    "kiro": "~/.kiro/hooks.json",
}
_MCP_CONFIG_PATH = {
    "claude-desktop": "~/Library/Application Support/Claude/claude_desktop_config.json",
    "claude-code": "~/.claude.json  (or project .mcp.json)",
    "cursor": "~/.cursor/mcp.json",
    "generic": "your MCP client's config file",
}


def _server_url(request: Request, override: Optional[str] = None) -> str:
    """The origin the client should point at.

    Precedence: explicit ``override`` (the page's Server URL field, for a one-off
    preview) > the shared ``public_url`` runtime setting (env or dashboard-set,
    so a reverse-proxied/domain deployment emits the domain for ALL users) >
    the request origin (``request.base_url``, honoring proxy headers).
    """
    for candidate in (override, rc.effective_str("public_url")):
        if candidate:
            c = candidate.strip().rstrip("/")
            if c.startswith("http://") or c.startswith("https://"):
                return c
    return str(request.base_url).rstrip("/")


@router.get("/config")
async def connect_config(request: Request, response: Response):
    """The shared public URL (env > dashboard DB > unset) and the origin fallback.

    The page uses this as the Server URL default for every user — set once,
    shared by all — instead of a per-browser localStorage value.
    """
    response.headers["Cache-Control"] = "no-store"
    pub, source = rc.effective("public_url")
    return {
        "public_url": pub or "",
        "source": source,
        "env_pinned": rc.is_env_pinned("public_url"),
        "origin": str(request.base_url).rstrip("/"),
    }


@router.get("/hooks")
async def connect_hooks(
    request: Request,
    response: Response,
    client: str = "claude",
    mode: str = "http",
    profile: str = "standard",
    server_url: Optional[str] = None,
):
    """Render a paste-ready Claude Code hooks block for settings.json.

    ``mode=http`` emits native HTTP hooks pointing at this server, authenticated
    with ``Authorization: Bearer ${MEM_MESH_HOOK_TOKEN}``; ``mode=api`` emits
    bash+curl command hooks. The actual token is returned separately (subject to
    the reveal policy) so the operator can set ``MEM_MESH_HOOK_TOKEN``.
    """
    response.headers["Cache-Control"] = "no-store"
    url = _server_url(request, server_url)

    from app.cli.install_hooks import _build_claude_hooks_settings

    settings = _build_claude_hooks_settings(profile, mode, url)

    # Claude Code's native HTTP hooks refuse private/link-local/CGNAT hosts
    # (Tailscale/VPN/LAN) as an SSRF guard — only loopback and public addresses
    # pass. Flag a blocked URL so the page can steer the user to api (command)
    # mode instead of emitting an http config that fails at runtime.
    http_hook_blocked = None
    if mode == "http":
        try:
            from app.cli.hooks.netcheck import check_http_hook_url

            http_hook_blocked = check_http_hook_url(url)
        except Exception:  # pragma: no cover - defensive
            http_hook_blocked = None

    token = resolve_hook_token()
    reveal = _can_reveal(request)
    return {
        "client": client,
        "mode": mode,
        "profile": profile,
        "server_url": url,
        "settings": settings,
        "settings_path": _HOOK_SETTINGS_PATH.get(client, "~/.claude/settings.json"),
        "http_hook_blocked": http_hook_blocked,
        "hook_token": token if reveal else None,
        "hook_token_masked": _mask(token) if token else "",
        "hook_token_env": "MEM_MESH_HOOK_TOKEN",
        "note": (
            "HTTP-mode hooks (events with a server endpoint) work by paste alone "
            "and read the token from MEM_MESH_HOOK_TOKEN (never stored in "
            "settings.json — export it where the client runs). Events without an "
            "endpoint stay command hooks that also need the shell scripts; for "
            "the complete set run `mem-mesh-hooks install`."
        ),
        # Hooks for Cursor/Kiro depend on installed shell scripts, so paste is
        # only partial — flag it so the page can recommend the CLI installer.
        "paste_complete": client == "claude" and mode == "http",
    }


@router.get("/mcp")
async def connect_mcp(
    request: Request,
    response: Response,
    client: str = "claude-desktop",
    mode: str = "http",
    server_url: Optional[str] = None,
):
    """Render a paste-ready ``mcpServers`` block for an MCP client.

    ``mode=http`` points at ``{server}/mcp/sse``; ``uvx``/``stdio`` spawn a local
    server. When MCP OAuth is enabled, the client performs the OAuth flow on
    first connect — register a client in the MCP OAuth tab if needed.
    """
    response.headers["Cache-Control"] = "no-store"
    url = _server_url(request, server_url)

    from app.cli.mcp_config import MCP_SERVER_KEY, generate_mcp_entry

    entry = generate_mcp_entry(mode, url, tool_key=client)

    # When MCP OAuth is on, an http-transport client must authenticate. Surface
    # the OAuth endpoints so the page can offer one-click client registration.
    # /mcp is guarded only when auth is enabled globally AND mcp auth resolves on
    # (matches BearerTokenMiddleware._requires_auth).
    mcp_auth_on = bool(
        rc.effective_bool("auth_enabled") and rc.effective_tribool("mcp_auth_enabled")
    )
    if mcp_auth_on and mode in ("http", "sse"):
        # Static token header (jina-style) so the pasted block authenticates
        # without the interactive OAuth flow — the server accepts its hook token
        # as an MCP API key on /mcp. Env-ref form; the value is returned below.
        entry["headers"] = {"Authorization": "Bearer ${MEM_MESH_HOOK_TOKEN}"}
    oauth = None
    if mode in ("http", "sse"):
        # Always surface the EXISTING OAuth clients (registered in Security → MCP
        # OAuth) and whether MCP auth is actually ON. This clarifies the common
        # confusion: making a client does NOT enable OAuth — mcp_auth_enabled
        # must be on too. When off, the page shows the clients exist but are not
        # enforced and links to Security to enable.
        svc = getattr(request.app.state, "oauth_service", None)
        clients = []
        if svc is not None:
            try:
                for c in await svc.list_clients(limit=20):
                    clients.append(
                        {
                            "client_id": c.client_id,
                            "client_name": getattr(c, "client_name", ""),
                            "is_active": getattr(c, "is_active", True),
                        }
                    )
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("connect: listing OAuth clients failed: %s", e)
        oauth = {
            "enabled": mcp_auth_on,
            "metadata_url": f"{url}/.well-known/oauth-authorization-server",
            "authorize_url": f"{url}/oauth/authorize",
            "token_url": f"{url}/oauth/token",
            "register_url": f"{url}/oauth/register",
            "clients": clients,
        }
    return {
        "client": client,
        "mode": mode,
        "server_url": url,
        "config": {"mcpServers": {MCP_SERVER_KEY: entry}},
        "config_path": _MCP_CONFIG_PATH.get(client, "your MCP client's config file"),
        "oauth_required": mcp_auth_on,
        "oauth": oauth,
        "mcp_token": (
            resolve_hook_token() if (mcp_auth_on and _can_reveal(request)) else None
        ),
        "mcp_token_masked": _mask(resolve_hook_token()) if mcp_auth_on else "",
        "mcp_token_env": "MEM_MESH_HOOK_TOKEN",
    }
