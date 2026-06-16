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

    An explicit ``override`` (the page's Server URL field) wins when it is a
    valid http(s) URL — so a reverse-proxied deployment served on a domain can
    emit that domain instead of the internal bind. Otherwise the dashboard's own
    origin (``request.base_url``, honoring proxy headers when configured).
    """
    if override:
        o = override.strip().rstrip("/")
        if o.startswith("http://") or o.startswith("https://"):
            return o
    return str(request.base_url).rstrip("/")


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

    token = resolve_hook_token()
    reveal = _can_reveal(request)
    return {
        "client": client,
        "mode": mode,
        "profile": profile,
        "server_url": url,
        "settings": settings,
        "settings_path": _HOOK_SETTINGS_PATH.get(client, "~/.claude/settings.json"),
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
    oauth = (
        {
            "metadata_url": f"{url}/.well-known/oauth-authorization-server",
            "authorize_url": f"{url}/oauth/authorize",
            "token_url": f"{url}/oauth/token",
            "register_url": f"{url}/oauth/register",
        }
        if mcp_auth_on and mode in ("http", "sse")
        else None
    )
    return {
        "client": client,
        "mode": mode,
        "server_url": url,
        "config": {"mcpServers": {MCP_SERVER_KEY: entry}},
        "config_path": _MCP_CONFIG_PATH.get(client, "your MCP client's config file"),
        "oauth_required": oauth is not None,
        "oauth": oauth,
    }
