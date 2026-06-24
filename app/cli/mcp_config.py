"""MCP configuration manager for dev tools.

Detects installed dev tools and configures mem-mesh MCP server entries
in their respective config files without touching other entries.
"""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import urlopen

from app.cli.codex_config import (
    CODEX_CONFIG,
    build_codex_mcp_block_from_entry,
    codex_config_has_mem_mesh,
    merge_codex_mcp_config,
    remove_codex_mcp_config,
)
from app.cli.hooks.colors import bold, dim, err, info, ok, warn
from app.cli.hooks.json_ops import timestamped_backup


def has_uvx() -> bool:
    """Return True if `uvx` is available on PATH."""
    return shutil.which("uvx") is not None


# ── Tool Registry ──

MCP_TOOLS: list[dict] = [
    {
        "name": "Codex",
        "key": "codex",
        "config_path": CODEX_CONFIG,
        "detect": lambda: (Path.home() / ".codex").exists(),
    },
    {
        "name": "Claude Code",
        "key": "claude-code",
        "config_path": Path.home() / ".claude.json",
        "detect": lambda: (Path.home() / ".claude").exists(),
    },
    {
        "name": "Cursor",
        "key": "cursor",
        "config_path": Path.home() / ".cursor" / "mcp.json",
        "detect": lambda: (Path.home() / ".cursor").exists(),
    },
    {
        "name": "Kiro",
        "key": "kiro",
        "config_path": Path.home() / ".kiro" / "settings" / "mcp.json",
        "detect": lambda: (Path.home() / ".kiro").exists(),
    },
    {
        "name": "Antigravity",
        "key": "antigravity",
        "config_path": Path.home() / ".antigravity" / "mcp.json",
        "detect": lambda: (
            (Path.home() / ".antigravity").exists()
            or (
                Path.home() / "Library" / "Application Support" / "Antigravity"
            ).exists()
        ),
    },
    {
        "name": "Claude Desktop",
        "key": "claude-desktop",
        "config_path": Path.home()
        / "Library"
        / "Application Support"
        / "Claude"
        / "claude_desktop_config.json",
        "detect": lambda: (
            Path.home() / "Library" / "Application Support" / "Claude"
        ).exists(),
    },
    {
        "name": "VS Code",
        "key": "vscode",
        "config_path": Path.home() / ".vscode" / "mcp.json",
        "detect": lambda: (Path.home() / ".vscode").exists(),
    },
    {
        "name": "Windsurf",
        "key": "windsurf",
        "config_path": Path.home() / ".windsurf" / "mcp.json",
        "detect": lambda: (Path.home() / ".windsurf").exists(),
    },
    {
        "name": "LM Studio",
        "key": "lmstudio",
        "config_path": Path.home() / ".lmstudio" / "mcp.json",
        "detect": lambda: (Path.home() / ".lmstudio").exists(),
    },
]

# MCP entry key name in all config files
MCP_SERVER_KEY = "mem-mesh"


def detect_tools() -> list[dict]:
    """Detect installed dev tools that support MCP configuration."""
    detected = []
    for tool in MCP_TOOLS:
        installed = tool["detect"]()
        has_config = tool["config_path"].exists()
        detected.append(
            {
                **tool,
                "installed": installed,
                "has_config": has_config,
            }
        )
    return detected


def backup_config(config_path: Path) -> Optional[Path]:
    """Create a timestamped backup of a config file before modification.

    Returns the backup path, or None if the file doesn't exist. Delegates to the
    shared :func:`timestamped_backup` so the backup keeps the original extension
    (``.claude.json`` -> ``.claude.json.<ts>.bak``).
    """
    return timestamped_backup(config_path)


def generate_mcp_entry(
    mode: str,
    url: str = "http://localhost:8000",
    auto_approve: bool = True,
    tool_key: str = "",
    with_auth: bool = False,
    token: Optional[str] = None,
) -> dict:
    """Generate a mem-mesh MCP server entry.

    Args:
        mode: 'uvx', 'stdio', or 'http' (alias 'sse' — both emit type:"http")
        url: API server URL (used for http mode)
        auto_approve: Whether to add autoApprove list for common tools
        tool_key: Tool registry key (e.g. 'claude-code', 'cursor') for MEM_MESH_CLIENT env
        with_auth: For http mode, embed an ``Authorization: Bearer <token>``
            header with the LITERAL hook token (mem-mesh owns this config file and
            bakes the secret in, so the MCP client needs no ``${ENV}`` expansion).
            When with_auth is set but ``token`` is falsy, no header is emitted.
        token: The literal hook token to bake into the auth header (resolved from
            the ~/.mem-mesh/hook_token SSOT by the caller).
    """
    approve_list = [
        "add",
        "search",
        "context",
        "update",
        "delete",
        "stats",
        "pin_add",
        "pin_complete",
        "pin_promote",
        "session_resume",
        "session_end",
        "link",
        "unlink",
        "get_links",
        "batch_operations",
        "weekly_review",
    ]

    if mode in ("sse", "http"):
        # Streamable HTTP transport. "sse" is a backward-compatible alias; the
        # entry type is always "http" so the connection survives a server
        # restart — legacy type:"sse" connections hang after a restart because
        # their server-side SSE stream and session queue are gone.
        entry: dict = {
            "url": f"{url.rstrip('/')}/mcp/sse",
            "type": "http",
        }
        if with_auth and token:
            # Literal token: mem-mesh manages this config file, so the secret is
            # baked in rather than referencing an env var the MCP client would
            # have to expand. Falsy token -> header omitted (caller warns).
            entry["headers"] = {"Authorization": f"Bearer {token}"}
    elif mode == "uvx":
        # uvx mode — each MCP client spawns an isolated, cached mem-mesh install.
        # No pre-install needed; uvx downloads on first run, reuses cache after.
        entry = {
            "command": "uvx",
            "args": ["--from", "mem-mesh[server]", "mem-mesh-mcp-stdio"],
        }
    else:
        # stdio mode — use the current Python interpreter
        python_path = sys.executable
        entry = {
            "command": python_path,
            "args": ["-m", "app.mcp_stdio"],
        }

    # Build the env block. MEM_MESH_CLIENT lets the server tag memories with the
    # source tool. For local backends (stdio/uvx), propagate an *explicitly set*
    # MEM_MESH_DATABASE_PATH so a GUI-launched client — which does not inherit
    # the shell env — still uses the same database. Never guess a path.
    env: Dict[str, str] = {}
    if tool_key:
        env["MEM_MESH_CLIENT"] = tool_key.replace("-", "_")
    if mode in ("uvx", "stdio"):
        db_path = os.environ.get("MEM_MESH_DATABASE_PATH")
        if db_path:
            env["MEM_MESH_DATABASE_PATH"] = db_path
    if env:
        entry["env"] = env

    if auto_approve:
        entry["autoApprove"] = approve_list

    return entry


def read_config(config_path: Path) -> dict:
    """Read and parse a JSON config file. Returns empty dict structure if missing."""
    if not config_path.exists():
        return {"mcpServers": {}}

    try:
        text = config_path.read_text(encoding="utf-8")
        data = json.loads(text)
        if "mcpServers" not in data:
            data["mcpServers"] = {}
        return data
    except (json.JSONDecodeError, OSError):
        return {"mcpServers": {}}


def write_config(config_path: Path, data: dict) -> None:
    """Write config data to JSON file, creating parent directories if needed."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def configure_tool(
    tool: dict,
    mcp_entry: dict,
    do_backup: bool = True,
) -> tuple[bool, str]:
    """Configure mem-mesh MCP entry for a single tool.

    Returns (success, message).
    """
    config_path: Path = tool["config_path"]

    if tool["key"] == "codex":
        backup_path = None
        if do_backup and config_path.exists():
            backup_path = backup_config(config_path)
        already = codex_config_has_mem_mesh(config_path)
        try:
            merge_codex_mcp_config(
                config_path, build_codex_mcp_block_from_entry(mcp_entry)
            )
        except OSError as e:
            return False, f"write failed: {e}"
        msg = "updated" if already else "added"
        if backup_path:
            msg += f" (backup: {backup_path.name})"
        return True, msg

    # Read existing config
    data = read_config(config_path)

    # No-op when already identical — return before backing up to avoid churn.
    existing = data["mcpServers"].get(MCP_SERVER_KEY)
    if existing == mcp_entry:
        return True, "already up to date"

    # Back up only when the entry actually changes.
    backup_path = None
    if do_backup and config_path.exists():
        backup_path = backup_config(config_path)

    # Update only the mem-mesh entry
    action = "updated" if existing else "added"
    data["mcpServers"][MCP_SERVER_KEY] = mcp_entry

    # Write back
    try:
        write_config(config_path, data)
    except OSError as e:
        return False, f"write failed: {e}"

    msg = f"{action}"
    if backup_path:
        msg += f" (backup: {backup_path.name})"
    return True, msg


def remove_tool_config(tool: dict) -> tuple[bool, str]:
    """Remove mem-mesh MCP entry from a tool's config.

    Returns (success, message).
    """
    config_path: Path = tool["config_path"]

    if tool["key"] == "codex":
        if not config_path.exists():
            return True, "no config file"
        if not codex_config_has_mem_mesh(config_path):
            return True, "not configured"
        backup_config(config_path)
        try:
            remove_codex_mcp_config(config_path)
        except OSError as e:
            return False, f"write failed: {e}"
        return True, "removed"

    if not config_path.exists():
        return True, "no config file"

    data = read_config(config_path)
    if MCP_SERVER_KEY not in data.get("mcpServers", {}):
        return True, "not configured"

    # Backup before removal
    backup_config(config_path)

    del data["mcpServers"][MCP_SERVER_KEY]
    try:
        write_config(config_path, data)
    except OSError as e:
        return False, f"write failed: {e}"

    return True, "removed"


def verify_tool_config(
    tool: dict, url: str = "http://localhost:8000"
) -> tuple[bool, str]:
    """Verify that mem-mesh MCP is correctly configured for a tool.

    Checks:
    1. Config file has mcpServers.mem-mesh entry
    2. For http mode, tests URL reachability (health check)
    3. For Claude Code, checks project-specific overrides that shadow global config

    Returns (success, message).
    """
    config_path: Path = tool["config_path"]

    if tool["key"] == "codex":
        if not config_path.exists():
            return False, "config file not found"
        if not codex_config_has_mem_mesh(config_path):
            return False, "mem-mesh entry missing"
        return True, "configured (Codex config.toml)"

    if not config_path.exists():
        return False, "config file not found"

    data = read_config(config_path)
    entry = data.get("mcpServers", {}).get(MCP_SERVER_KEY)
    if not entry:
        return False, "mem-mesh entry missing"

    warnings: list[str] = []

    # Claude Code: check project-specific overrides
    if tool["key"] == "claude-code":
        warnings.extend(_check_claude_project_overrides(data, entry))

    # http mode — check URL reachability
    if "url" in entry:
        # Check transport type key
        if entry.get("transport") and not entry.get("type"):
            warnings.append("uses 'transport' key (should be 'type' for Claude Code)")

        sse_url = entry["url"]
        health_url = sse_url.rsplit("/mcp/sse", 1)[0] + "/health"
        try:
            with urlopen(health_url, timeout=3) as resp:
                if resp.status == 200:
                    status = "configured (HTTP, server reachable)"
        except (URLError, OSError):
            status = "configured (HTTP, server not reachable — start with `python -m app.web`)"

        if warnings:
            return False, f"{status} — WARN: {'; '.join(warnings)}"
        return True, status

    # stdio mode
    if "command" in entry:
        if warnings:
            return False, f"configured (stdio) — WARN: {'; '.join(warnings)}"
        return True, "configured (stdio)"

    if warnings:
        return False, f"configured — WARN: {'; '.join(warnings)}"
    return True, "configured"


def _check_claude_project_overrides(data: dict, global_entry: dict) -> list[str]:
    """Check if any Claude Code project-specific mcpServers override the global config.

    Common issue: global config has type=http, but project-specific config
    has type=sse (leftover from migration), causing MCP tool calls to hang.
    """
    warnings = []
    global_type = global_entry.get("type") or global_entry.get("transport", "")

    projects = data.get("projects", {})
    for project_path, project_conf in projects.items():
        proj_mcp = project_conf.get("mcpServers", {}).get(MCP_SERVER_KEY)
        if not proj_mcp:
            continue

        proj_type = proj_mcp.get("type") or proj_mcp.get("transport", "")

        # Project type differs from global type
        if proj_type and global_type and proj_type != global_type:
            short_path = project_path.replace(str(Path.home()), "~")
            warnings.append(
                f"project '{short_path}' overrides type={proj_type} "
                f"(global={global_type}) — MCP may hang"
            )
        # Project uses legacy 'transport' key
        elif proj_mcp.get("transport") and not proj_mcp.get("type"):
            short_path = project_path.replace(str(Path.home()), "~")
            warnings.append(
                f"project '{short_path}' uses 'transport' key (should be 'type')"
            )

    return warnings


# ── Interactive Flow ──


def _prompt_choice(prompt: str, options: list[str], default: str = "") -> str:
    """Simple numbered choice prompt."""
    for i, opt in enumerate(options, 1):
        print(f"    {bold(str(i))}. {opt}")
    while True:
        raw = input(f"  {prompt} ").strip()
        if not raw and default:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print(f"    Enter 1-{len(options)}")


def _existing_mem_mesh_entry(tool: dict) -> Optional[Any]:
    """Return the tool's current mem-mesh MCP entry, or None if absent.

    Used to guard against silently rewriting a working entry under ``--yes``.
    For Codex (TOML, different shape) a truthy sentinel is returned when an
    entry exists so the guard preserves it rather than comparing dicts.
    """
    config_path: Path = tool["config_path"]
    if not config_path.exists():
        return None
    if tool["key"] == "codex":
        return {"__codex__": True} if codex_config_has_mem_mesh(config_path) else None
    data = read_config(config_path)
    return data.get("mcpServers", {}).get(MCP_SERVER_KEY)


def _entry_mode(entry: Optional[Any]) -> Optional[str]:
    """Classify an existing entry's transport: 'http' | 'uvx' | 'stdio' | None.

    Inverse of :func:`generate_mcp_entry`. Used to keep an entry on its current
    backend during a non-interactive fix (so http stays http) rather than
    flipping it. Returns None for an unrecognized shape (e.g. the Codex
    sentinel), which means "no opinion — use the chosen mode".
    """
    if not isinstance(entry, dict):
        return None
    if "url" in entry:
        return "http"
    command = str(entry.get("command", ""))
    args = entry.get("args", []) or []
    if command == "uvx" or any("uvx" in str(a) for a in args):
        return "uvx"
    if any("app.mcp_stdio" in str(a) or "mem-mesh-mcp-stdio" in str(a) for a in args):
        return "stdio"
    if "command" in entry:
        return "stdio"
    return None


def run_mcp_setup(
    url: str = "http://localhost:8000",
    yes: bool = False,
    preferred_mode: Optional[str] = None,
    server_reachable: bool = False,
    with_auth: bool = False,
    token: Optional[str] = None,
    step_label: str = "[3/3]",
) -> Dict[str, Any]:
    """Interactive MCP configuration step for onboarding.

    Args:
        url: API URL for http mode
        yes: Non-interactive (auto-pick best mode)
        preferred_mode: If set ('uvx'|'stdio'|'http'|'sse'), skip mode prompt
        server_reachable: When True (server is up — possibly auth-gated), the
            non-interactive auto-pick prefers ``http`` over ``uvx`` so a working
            HTTP deployment is not flipped to an isolated local uvx install.

    Returns:
        A summary dict for machine consumption (the onboarding ``--json``
        output). Always returned; human-readable progress is still printed.
        Shape: ``{"status": "configured"|"skipped"|"no_tools", "mode": str,
        "detected_tools": [keys], "configured": [...], "verification": [...]}``.
    """
    print(bold(f"{step_label} MCP Configuration"))
    print()

    # Resolve the literal hook token once — it gets baked into each tool's MCP
    # config (Option 2). An explicit token (from `mcp config --token`) wins;
    # otherwise read the ~/.mem-mesh/hook_token SSOT. If auth is requested but no
    # token exists, drop auth with a warning rather than baking an empty header.
    # Always-auth (Option 2): bake the token whenever one is resolvable,
    # regardless of whether the server enforces auth right now. The server
    # ignores the Bearer header when auth is off, so it is harmless — and it
    # avoids a re-install if auth is toggled on later, keeping every tool
    # (including Codex, which already does this) consistent. The legacy
    # `with_auth` gate based on a network probe is no longer consulted.
    if token is None:
        from app.core.config import resolve_hook_token

        token = resolve_hook_token()
    with_auth = bool(token)
    if not token:
        print(
            f"  {warn('No hook token (~/.mem-mesh/hook_token) — MCP configured without an auth header.')}"
        )

    # Show the API URL exactly as resolved by the caller. The caller owns
    # precedence (explicit --url > MEM_MESH_API_URL env > ~/.mem-mesh/api_url >
    # default); re-applying the env override here would silently ignore an
    # explicit --url.
    print(f"  API URL: {info(url)}")
    print()

    # Detect tools
    tools = detect_tools()
    installed_tools = [t for t in tools if t["installed"]]
    detected_keys = [t["key"] for t in installed_tools]

    if not installed_tools:
        print(f"  {warn('No supported dev tools detected.')}")
        print(
            dim(
                "  Supported: Codex, Cursor, Kiro, Antigravity, Claude Desktop, VS Code, Windsurf, LM Studio"
            )
        )
        print()
        return {"status": "no_tools", "detected_tools": []}

    # Show detected tools
    print(f"  {bold('Detected tools:')}")
    for t in tools:
        if t["installed"]:
            config_status = (
                ok("config exists") if t["has_config"] else dim("no config yet")
            )
            # Check if mem-mesh already configured
            if t["has_config"]:
                if t["key"] == "codex":
                    configured = codex_config_has_mem_mesh(t["config_path"])
                else:
                    data = read_config(t["config_path"])
                    configured = MCP_SERVER_KEY in data.get("mcpServers", {})
                if configured:
                    config_status = ok("mem-mesh configured")
            print(
                f"    {ok('✓')} {t['name']:<16} {dim(str(t['config_path']))}  [{config_status}]"
            )
        else:
            print(f"    {dim('✗')} {t['name']:<16} {dim('not installed')}")
    print()

    uvx_available = has_uvx()

    if preferred_mode in ("uvx", "stdio", "http", "sse"):
        mode = preferred_mode
        targets = installed_tools
        print(f"  {bold('Connection mode:')} {info(mode)} {dim('(pre-selected)')}")
        print()
    elif yes:
        # Non-interactive auto-pick. If the server is reachable (even when
        # auth-gated), prefer HTTP so an existing working deployment is not
        # flipped to an isolated local uvx install. Only fall back to uvx when
        # there is no reachable server to talk to.
        if server_reachable:
            mode = "http"
        else:
            mode = "uvx" if uvx_available else "http"
        targets = installed_tools
    else:
        # Choose connection mode — HTTP first (recommended): the standard
        # server-backed deployment the dashboard, hooks, and the env SSOT assume.
        print(f"  {bold('Connection mode:')}")
        mode_options: list[str] = []
        mode_keys: list[str] = []
        mode_options.append(
            f"HTTP {dim('(recommended — streamable HTTP via a running API server at ' + url + ')')}"
        )
        mode_keys.append("http")
        if uvx_available:
            mode_options.append(
                f"uvx {dim('(auto-spawned by each tool, no server to manage)')}"
            )
            mode_keys.append("uvx")
        mode_options.append(
            f"Stdio {dim('(local Python — runs MCP process per tool)')}"
        )
        mode_keys.append("stdio")
        mode_options.append(f"Skip {dim('(configure later)')}")
        mode_keys.append("skip")

        chosen_mode = _prompt_choice(
            "Choose [1]: ", mode_options, default=mode_options[0]
        )
        mode = mode_keys[mode_options.index(chosen_mode)]
        if mode == "skip":
            print(f"  {dim('Skipping MCP configuration.')}")
            print()
            return {"status": "skipped", "mode": mode, "detected_tools": detected_keys}
        print()

        # Choose which tools to configure
        if len(installed_tools) == 1:
            targets = installed_tools
            print(f"  Configuring: {info(installed_tools[0]['name'])}")
        else:
            tool_names = [t["name"] for t in installed_tools]
            print(f"  {bold('Configure mem-mesh MCP for:')}")
            target_options = [
                f"All detected ({', '.join(tool_names)})",
                "Select individually",
                "Skip",
            ]
            chosen_target = _prompt_choice(
                "Choose [1]: ", target_options, default=target_options[0]
            )
            target_idx = target_options.index(chosen_target)

            if target_idx == 2:
                print(f"  {dim('Skipping MCP configuration.')}")
                print()
                return {
                    "status": "skipped",
                    "mode": mode,
                    "detected_tools": detected_keys,
                }
            elif target_idx == 0:
                targets = installed_tools
            else:
                # Individual selection
                targets = []
                for t in installed_tools:
                    answer = (
                        input(f"    Configure {bold(t['name'])}? [Y/n] ")
                        .strip()
                        .lower()
                    )
                    if answer not in ("n", "no"):
                        targets.append(t)
        print()

    if not targets:
        print(f"  {dim('No tools selected.')}")
        print()
        return {"status": "skipped", "mode": mode, "detected_tools": detected_keys}

    # Show sample MCP entry
    sample_entry = generate_mcp_entry(
        mode=mode, url=url, tool_key=targets[0]["key"], with_auth=with_auth, token=token
    )
    print(f"  {bold('MCP entry')} ({mode} mode):")
    # Mask the literal bearer token before printing to the console / --json log;
    # the real value still lands in the config file (the accepted tradeoff).
    display_entry = dict(sample_entry)
    if "headers" in display_entry and token:
        from app.core.redaction import mask_secret

        display_entry["headers"] = {"Authorization": f"Bearer {mask_secret(token)}"}
    entry_json = json.dumps({"mem-mesh": display_entry}, indent=2)
    for line in entry_json.splitlines():
        print(f"    {dim(line)}")
    print()

    # Under non-interactive auto mode (no explicit preferred_mode) we must NOT
    # silently FLIP an existing entry to a different backend — that is the
    # footgun where `install --yes` turned a working HTTP entry into a local uvx
    # one (separate DB). But a same-transport fix (correcting a legacy
    # `transport` key, refreshing the URL) MUST still apply, or a misconfigured
    # entry could never be repaired non-interactively. So for an existing entry
    # we regenerate in its CURRENT transport; only an explicit mode choice
    # (preferred_mode / interactive selection) may change the backend.
    auto_mode = yes and not preferred_mode

    # Configure each tool (with tool-specific MEM_MESH_CLIENT env)
    configured: List[Dict[str, Any]] = []
    for t in targets:
        entry_mode = mode
        if auto_mode:
            existing_mode = _entry_mode(_existing_mem_mesh_entry(t))
            if existing_mode and existing_mode != mode:
                entry_mode = existing_mode  # keep the backend, fix the contents
        mcp_entry = generate_mcp_entry(
            mode=entry_mode, url=url, tool_key=t["key"], with_auth=with_auth, token=token
        )
        success, msg = configure_tool(t, mcp_entry, do_backup=True)
        configured.append(
            {"tool": t["name"], "key": t["key"], "ok": success, "result": msg}
        )
        if success:
            print(f"  {ok('✓')} {t['name']}: {msg}")
        else:
            print(f"  {err('✗')} {t['name']}: {msg}")
    print()

    # Verify configuration
    verification: List[Dict[str, Any]] = []
    print(f"  {bold('Verification:')}")
    for t in targets:
        _ok, vmsg = verify_tool_config(t, url=url)
        verification.append(
            {"tool": t["name"], "key": t["key"], "ok": _ok, "message": vmsg}
        )
        if _ok:
            print(f"  {ok('✓')} {t['name']}: {vmsg}")
        else:
            print(f"  {warn('!')} {t['name']}: {vmsg}")
    print()

    return {
        "status": "configured",
        "mode": mode,
        "detected_tools": detected_keys,
        "configured": configured,
        "verification": verification,
    }
