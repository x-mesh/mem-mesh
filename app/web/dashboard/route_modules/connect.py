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

import base64
import json
import logging
from pathlib import Path
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
    "kiro": "~/.kiro/settings/hooks.json + ~/.kiro/hooks/*.kiro.hook",
    "codex": "~/.codex/hooks.json (installer managed)",
}
_MCP_CONFIG_PATH = {
    "claude-desktop": "~/Library/Application Support/Claude/claude_desktop_config.json",
    "claude-code": "~/.claude.json  (or project .mcp.json)",
    "cursor": "~/.cursor/mcp.json",
    "kiro": "~/.kiro/settings/mcp.json",
    "antigravity": "~/.antigravity/mcp.json",
    "codex": "~/.codex/config.toml",
    "generic": "your MCP client's config file",
}

_INSTALL_TARGETS = {"codex", "claude", "kiro", "antigravity", "all"}


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


def _json_b64(data: dict) -> str:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _with_mcp_auth(entry: dict, token_required: bool) -> dict:
    if token_required and "url" in entry:
        entry = dict(entry)
        entry["headers"] = {"Authorization": "Bearer ${MEM_MESH_HOOK_TOKEN}"}
    return entry


def _bootstrap_payload(
    *,
    target: str,
    url: str,
    profile: str,
    mcp_auth_on: bool,
    token: Optional[str],
) -> dict:
    """Build a client-side install payload for machines without mem-mesh code."""
    from app.cli.codex_config import build_codex_mcp_block_from_entry
    from app.cli.install_hooks import (
        ENHANCED_STOP_HOOK_TEMPLATE,
        KIRO_STOP_HOOK_TEMPLATE,
        POST_TOOL_USE_HOOK_TEMPLATE,
        PRECOMPACT_HOOK_TEMPLATE,
        SESSION_END_HOOK_TEMPLATE,
        SESSION_START_HOOK_TEMPLATE,
        STOP_DECIDE_HOOK_TEMPLATE,
        STOP_HOOK_TEMPLATE,
        SUBAGENT_START_HOOK_TEMPLATE,
        SUBAGENT_STOP_HOOK_TEMPLATE,
        TASK_COMPLETED_HOOK_TEMPLATE,
        USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
        _build_claude_hooks_settings,
        _build_codex_hooks_settings,
        _render_template,
    )
    from app.cli.mcp_config import MCP_SERVER_KEY, generate_mcp_entry
    from app.cli.prompts.renderers import (
        render_kiro_auto_create_pin,
        render_kiro_auto_save,
        render_kiro_load_context,
    )

    clients = {}

    if target in ("codex", "all"):
        codex_scripts = {
            "mem-mesh-session-start.sh": _render_template(
                SESSION_START_HOOK_TEMPLATE,
                url,
                source_tag="codex-hook",
                ide_tag="codex",
                client_tag="codex",
            ),
            "mem-mesh-precompact.sh": _render_template(
                PRECOMPACT_HOOK_TEMPLATE,
                url,
                source_tag="codex-hook",
                ide_tag="codex",
                client_tag="codex",
            ),
        }
        if profile == "enhanced":
            codex_scripts["mem-mesh-stop-enhanced.sh"] = _render_template(
                ENHANCED_STOP_HOOK_TEMPLATE,
                url,
                source_tag="codex-hook",
                ide_tag="codex",
                client_tag="codex",
            )
        elif profile == "minimal":
            codex_scripts["mem-mesh-stop.sh"] = _render_template(
                STOP_HOOK_TEMPLATE,
                url,
                source_tag="codex-hook",
                ide_tag="codex",
                client_tag="codex",
            )
        else:
            codex_scripts["mem-mesh-stop-decide.sh"] = _render_template(
                STOP_DECIDE_HOOK_TEMPLATE,
                url,
                source_tag="codex-hook",
                ide_tag="codex",
                client_tag="codex",
            )
        if profile != "minimal":
            codex_scripts.update(
                {
                    "mem-mesh-user-prompt-submit.sh": _render_template(
                        USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
                        url,
                        source_tag="codex-hook",
                        ide_tag="codex",
                        client_tag="codex",
                    ),
                    "mem-mesh-post-tool-use.sh": _render_template(
                        POST_TOOL_USE_HOOK_TEMPLATE,
                        url,
                        source_tag="codex-hook",
                        ide_tag="codex",
                        client_tag="codex",
                    ),
                    "mem-mesh-subagent-start.sh": _render_template(
                        SUBAGENT_START_HOOK_TEMPLATE,
                        url,
                        source_tag="codex-hook",
                        ide_tag="codex",
                        client_tag="codex",
                    ),
                    "mem-mesh-subagent-stop.sh": _render_template(
                        SUBAGENT_STOP_HOOK_TEMPLATE,
                        url,
                        source_tag="codex-hook",
                        ide_tag="codex",
                        client_tag="codex",
                    ),
                }
            )
        codex_entry = _with_mcp_auth(
            generate_mcp_entry("http", url, tool_key="codex"), mcp_auth_on
        )
        clients["codex"] = {
            "hooks_dir": "~/.codex/hooks",
            "scripts": codex_scripts,
            "hooks_json_path": "~/.codex/hooks.json",
            "hooks_json": _build_codex_hooks_settings(
                Path("__HOME__/.codex/hooks"), profile, mode="api"
            ),
            "codex_toml_path": "~/.codex/config.toml",
            "codex_toml": build_codex_mcp_block_from_entry(codex_entry),
        }

    if target in ("claude", "all"):
        claude_scripts = {
            "mem-mesh-session-start.sh": _render_template(
                SESSION_START_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
                client_tag="claude_code",
            ),
            "mem-mesh-precompact.sh": _render_template(
                PRECOMPACT_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
                client_tag="claude_code",
            ),
            "mem-mesh-session-end.sh": _render_template(
                SESSION_END_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
                client_tag="claude_code",
            ),
        }
        if profile == "enhanced":
            claude_scripts["mem-mesh-stop-enhanced.sh"] = _render_template(
                ENHANCED_STOP_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
                client_tag="claude_code",
            )
        elif profile == "minimal":
            claude_scripts["mem-mesh-stop.sh"] = _render_template(
                STOP_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
                client_tag="claude_code",
            )
        else:
            claude_scripts["mem-mesh-stop-decide.sh"] = _render_template(
                STOP_DECIDE_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
                client_tag="claude_code",
            )
        if profile != "minimal":
            claude_scripts.update(
                {
                    "mem-mesh-user-prompt-submit.sh": _render_template(
                        USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
                        url,
                        source_tag="claude-code-hook",
                        ide_tag="claude",
                        client_tag="claude_code",
                    ),
                    "mem-mesh-post-tool-use.sh": _render_template(
                        POST_TOOL_USE_HOOK_TEMPLATE,
                        url,
                        source_tag="claude-code-hook",
                        ide_tag="claude",
                        client_tag="claude_code",
                    ),
                    "mem-mesh-subagent-start.sh": _render_template(
                        SUBAGENT_START_HOOK_TEMPLATE,
                        url,
                        source_tag="claude-code-hook",
                        ide_tag="claude",
                        client_tag="claude_code",
                    ),
                    "mem-mesh-subagent-stop.sh": _render_template(
                        SUBAGENT_STOP_HOOK_TEMPLATE,
                        url,
                        source_tag="claude-code-hook",
                        ide_tag="claude",
                        client_tag="claude_code",
                    ),
                    "mem-mesh-task-completed.sh": _render_template(
                        TASK_COMPLETED_HOOK_TEMPLATE,
                        url,
                        source_tag="claude-code-hook",
                        ide_tag="claude",
                        client_tag="claude_code",
                    ),
                }
            )
        claude_entry = _with_mcp_auth(
            generate_mcp_entry("http", url, tool_key="claude-code"), mcp_auth_on
        )
        clients["claude"] = {
            "hooks_dir": "~/.claude/hooks",
            "scripts": claude_scripts,
            "hooks_json_path": "~/.claude/settings.json",
            "hooks_json": _build_claude_hooks_settings(
                profile, mode="api", url=url, hooks_prefix="__HOME__/.claude/hooks"
            ),
            "mcp_json_path": "~/.claude.json",
            "mcp_json": {"mcpServers": {MCP_SERVER_KEY: claude_entry}},
        }

    if target in ("kiro", "all"):
        kiro_entry = _with_mcp_auth(
            generate_mcp_entry("http", url, tool_key="kiro"), mcp_auth_on
        )
        clients["kiro"] = {
            "hooks_dir": "~/.kiro/hooks",
            "scripts": {
                "mem-mesh-stop.sh": _render_template(
                    KIRO_STOP_HOOK_TEMPLATE,
                    url,
                    source_tag="kiro-hook",
                    ide_tag="kiro",
                    client_tag="kiro",
                )
            },
            "kiro_hooks_json_path": "~/.kiro/settings/hooks.json",
            "kiro_hooks_json": {
                "hooks": [
                    {
                        "name": "mem-mesh: Save Response",
                        "trigger": "agentResponse",
                        "action": "shell",
                        "command": "__HOME__/.kiro/hooks/mem-mesh-stop.sh",
                        "env": {"KIRO_RESULT": "$response"},
                    }
                ]
            },
            "kiro_hook_files_dir": "~/.kiro/hooks",
            "kiro_hook_files": {
                "auto-save-conversations.kiro.hook": render_kiro_auto_save(),
                "auto-create-pin-on-task.kiro.hook": render_kiro_auto_create_pin(),
                "load-project-context.kiro.hook": render_kiro_load_context(),
            },
            "mcp_json_path": "~/.kiro/settings/mcp.json",
            "mcp_json": {"mcpServers": {MCP_SERVER_KEY: kiro_entry}},
        }

    if target in ("antigravity", "all"):
        antigravity_entry = _with_mcp_auth(
            generate_mcp_entry("http", url, tool_key="antigravity"), mcp_auth_on
        )
        clients["antigravity"] = {
            "mcp_json_path": "~/.antigravity/mcp.json",
            "mcp_json": {"mcpServers": {MCP_SERVER_KEY: antigravity_entry}},
        }

    return {
        "target": target,
        "server_url": url,
        "profile": profile,
        "token": token or "",
        "token_revealed": bool(token),
        "mcp_auth_on": mcp_auth_on,
        "rules_installed": any(
            client.get("hooks_json_path") or client.get("kiro_hook_files_dir")
            for client in clients.values()
        ),
        "clients": clients,
    }


def build_install_script(
    request: Request,
    *,
    target: str,
    profile: str = "standard",
    server_url: Optional[str] = None,
) -> str:
    """Return a self-contained shell installer for a local client machine."""
    target = target.lower().removesuffix(".sh")
    if target not in _INSTALL_TARGETS:
        raise ValueError(f"unknown install target: {target}")
    if profile not in ("minimal", "standard", "enhanced"):
        raise ValueError(f"unknown hook profile: {profile}")

    url = _server_url(request, server_url)
    mcp_auth_on = bool(
        rc.effective_bool("auth_enabled") and rc.effective_tribool("mcp_auth_enabled")
    )
    token = resolve_hook_token() if _can_reveal(request) else None
    payload = _json_b64(
        _bootstrap_payload(
            target=target,
            url=url,
            profile=profile,
            mcp_auth_on=mcp_auth_on,
            token=token,
        )
    )
    return f"""#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "mem-mesh installer requires python3 on this client machine." >&2
  exit 1
fi

python3 - <<'PY'
import base64
import json
import os
import re
import stat
from pathlib import Path

payload = json.loads(base64.b64decode("{payload}").decode("utf-8"))
home = Path.home()


def expand(path):
    return Path(path.replace("~", str(home), 1))


def subst(value):
    if isinstance(value, str):
        return value.replace("__HOME__", str(home))
    if isinstance(value, list):
        return [subst(v) for v in value]
    if isinstance(value, dict):
        return {{k: subst(v) for k, v in value.items()}}
    return value


def read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")


def is_mem_mesh_hook_entry(entry):
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks", [])
    if not isinstance(hooks, list):
        return False
    for hook in hooks:
        if not isinstance(hook, dict):
            continue
        command = str(hook.get("command", ""))
        url = str(hook.get("url", ""))
        status = str(hook.get("statusMessage", ""))
        if "mem-mesh-" in command or "/api/hooks/claude/" in url or "mem-mesh" in status:
            return True
    return False


def merge_hooks_json(path, incoming):
    existing = read_json(path, {{"hooks": {{}}}})
    if not isinstance(existing, dict):
        existing = {{"hooks": {{}}}}
    existing_hooks = existing.get("hooks")
    if not isinstance(existing_hooks, dict):
        existing_hooks = {{}}
    for event, entries in incoming.get("hooks", {{}}).items():
        current = existing_hooks.get(event, [])
        if not isinstance(current, list):
            current = []
        existing_hooks[event] = [e for e in current if not is_mem_mesh_hook_entry(e)] + entries
    existing["hooks"] = existing_hooks
    write_json(path, existing)


def merge_mcp_json(path, incoming):
    existing = read_json(path, {{"mcpServers": {{}}}})
    if not isinstance(existing, dict):
        existing = {{"mcpServers": {{}}}}
    servers = existing.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {{}}
    servers.update(incoming.get("mcpServers", {{}}))
    existing["mcpServers"] = servers
    write_json(path, existing)


def merge_kiro_hooks_json(path, incoming):
    existing = read_json(path, {{"hooks": []}})
    if not isinstance(existing, dict):
        existing = {{"hooks": []}}
    hooks = existing.get("hooks")
    if not isinstance(hooks, list):
        hooks = []
    incoming_hooks = incoming.get("hooks", [])
    names = {{
        h.get("name")
        for h in incoming_hooks
        if isinstance(h, dict) and isinstance(h.get("name"), str)
    }}
    existing["hooks"] = [
        h
        for h in hooks
        if not (isinstance(h, dict) and h.get("name") in names)
    ] + incoming_hooks
    write_json(path, existing)


def write_hook_files(path, files):
    path.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = path / name
        if isinstance(content, (dict, list)):
            target.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
        else:
            target.write_text(str(content), encoding="utf-8")


def strip_codex_mem_mesh(text):
    lines = text.splitlines(keepends=True)
    result = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped == "# >>> mem-mesh managed MCP":
            skipping = True
            continue
        if skipping:
            if stripped == "# <<< mem-mesh managed MCP":
                skipping = False
            continue
        if re.match(r"^\\s*\\[mcp_servers\\.mem-mesh(?:\\.|\\])", line):
            skipping = True
            continue
        if skipping and stripped.startswith("[") and not re.match(r"^\\s*\\[mcp_servers\\.mem-mesh(?:\\.|\\])", line):
            skipping = False
        if not skipping:
            result.append(line)
    return "".join(result).rstrip() + "\\n"


def merge_codex_toml(path, block):
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    merged = strip_codex_mem_mesh(existing)
    if merged.strip():
        merged += "\\n"
    merged += block.rstrip() + "\\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(merged, encoding="utf-8")


mem_dir = home / ".mem-mesh"
mem_dir.mkdir(parents=True, exist_ok=True)
(mem_dir / "api_url").write_text(payload["server_url"] + "\\n", encoding="utf-8")
if payload.get("token"):
    token_file = mem_dir / "hook_token"
    token_file.write_text(payload["token"] + "\\n", encoding="utf-8")
    token_file.chmod(0o600)

installed = []
for name, client in payload["clients"].items():
    hooks_dir = None
    if client.get("hooks_dir"):
        hooks_dir = expand(client["hooks_dir"])
        hooks_dir.mkdir(parents=True, exist_ok=True)
        for script_name, content in client.get("scripts", {{}}).items():
            path = hooks_dir / script_name
            path.write_text(content, encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    if client.get("hooks_json_path"):
        merge_hooks_json(expand(client["hooks_json_path"]), subst(client["hooks_json"]))
    if client.get("kiro_hooks_json_path"):
        merge_kiro_hooks_json(
            expand(client["kiro_hooks_json_path"]), subst(client["kiro_hooks_json"])
        )
    if client.get("kiro_hook_files_dir"):
        write_hook_files(
            expand(client["kiro_hook_files_dir"]), subst(client.get("kiro_hook_files", {{}}))
        )
    if client.get("mcp_json_path"):
        merge_mcp_json(expand(client["mcp_json_path"]), subst(client["mcp_json"]))
    if client.get("codex_toml_path"):
        merge_codex_toml(expand(client["codex_toml_path"]), subst(client["codex_toml"]))
    installed.append(name)

print("mem-mesh client install complete: " + ", ".join(installed))
print("server_url: " + payload["server_url"])
if payload.get("rules_installed"):
    print("hook rules: session_resume on start, pin_add for file-changing or multi-step work, pin_complete on finish")
else:
    print("hook rules: not installed for this MCP-only target")
if payload.get("token_revealed"):
    print("hook token: written to ~/.mem-mesh/hook_token")
    if payload.get("mcp_auth_on"):
        print("MCP auth is on. Export MEM_MESH_HOOK_TOKEN where the client runs:")
        print('  export MEM_MESH_HOOK_TOKEN="$(cat ~/.mem-mesh/hook_token)"')
else:
    print("hook token was not embedded. If auth is enabled, set MEM_MESH_HOOK_TOKEN or run this from an authenticated/local dashboard.")
PY
"""


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


@router.get("/install/{target}.sh")
async def connect_install(
    request: Request,
    response: Response,
    target: str,
    profile: str = "standard",
    server_url: Optional[str] = None,
):
    """Return a self-contained local bootstrap script for client machines."""
    response.headers["Cache-Control"] = "no-store"
    try:
        script = build_install_script(
            request, target=target, profile=profile, server_url=server_url
        )
    except ValueError as exc:
        response.status_code = 400
        return f"#!/usr/bin/env bash\necho {json.dumps(str(exc))} >&2\nexit 1\n"
    return Response(
        script,
        media_type="text/x-shellscript; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


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
        "rules_note": (
            "Installed hook context tells the agent to run session_resume, create "
            "pins for file-changing or multi-step work, and call pin_complete "
            "before final response."
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
    config = {"mcpServers": {MCP_SERVER_KEY: entry}}
    config_text = None
    config_format = "json"
    if client == "codex":
        from app.cli.codex_config import build_codex_mcp_block_from_entry

        config_text = build_codex_mcp_block_from_entry(entry)
        config_format = "toml"

    return {
        "client": client,
        "mode": mode,
        "server_url": url,
        "config": config,
        "config_text": config_text,
        "config_format": config_format,
        "config_path": _MCP_CONFIG_PATH.get(client, "your MCP client's config file"),
        "oauth_required": mcp_auth_on,
        "oauth": oauth,
        "mcp_token": (
            resolve_hook_token() if (mcp_auth_on and _can_reveal(request)) else None
        ),
        "mcp_token_masked": _mask(resolve_hook_token()) if mcp_auth_on else "",
        "mcp_token_env": "MEM_MESH_HOOK_TOKEN",
    }
