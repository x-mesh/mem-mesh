"""Unified system status for mem-mesh.

Shows server, hooks, and MCP configuration status in one view.
"""

import json
from pathlib import Path

from app.cli.hooks.colors import dim, err, header, info, ok, warn
from app.cli.hooks.constants import (
    CLAUDE_HOOKS_DIR,
    CLAUDE_SETTINGS,
    CURSOR_HOOKS_DIR,
    CURSOR_SETTINGS,
    KIRO_HOOKS_DIR,
    KIRO_SETTINGS,
)
from app.cli.hooks.status import (
    _detect_profile,
    _extract_url_from_script,
    check_connectivity,
    resolve_api_url,
)


def _count_installed_hooks(hooks_dir: Path) -> int:
    """Count installed mem-mesh hook scripts."""
    if not hooks_dir.exists():
        return 0
    return len(list(hooks_dir.glob("mem-mesh-*.sh")))


def _check_mcp_stdio_config() -> tuple[bool, str]:
    """Check if MCP stdio server is configured.

    Checks Claude Code (~/.claude.json) first, then falls back to
    Claude Desktop config.
    """
    candidates = [
        ("Claude Code", Path.home() / ".claude.json"),
        ("Claude Desktop", Path.home() / ".claude" / "claude_desktop_config.json"),
    ]

    for label, config_path in candidates:
        if not config_path.exists():
            continue
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        mcp_servers = data.get("mcpServers", {})
        for name in mcp_servers:
            if "mem-mesh" in name.lower() or "mem_mesh" in name.lower():
                return True, f"'{name}' in {label}"

    return False, "not configured"


def cmd_system_status() -> None:
    """Print unified system status."""
    print()
    print(header("=== mem-mesh system status ==="))
    print()

    # --- Server ---
    print(header("[Server]"))
    baked_url = (
        _extract_url_from_script(CLAUDE_HOOKS_DIR / "mem-mesh-session-start.sh")
        or _extract_url_from_script(CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh")
    )
    url, source = resolve_api_url(baked_url)
    print(f"  URL:        {info(url)} {dim(f'(from {source})')}")

    reachable, message = check_connectivity(url)
    if reachable:
        print(f"  Health:     {ok(message)}")
        print(f"  Dashboard:  {info(url + '/dashboard')}")
    else:
        print(f"  Health:     {err(message)}")
        print(f"  Dashboard:  {dim('unavailable')}")
    print()

    # --- Hooks ---
    print(header("[Hooks]"))
    for label, hooks_dir, settings_path in [
        ("Claude Code", CLAUDE_HOOKS_DIR, CLAUDE_SETTINGS),
        ("Kiro", KIRO_HOOKS_DIR, KIRO_SETTINGS),
        ("Cursor", CURSOR_HOOKS_DIR, CURSOR_SETTINGS),
    ]:
        count = _count_installed_hooks(hooks_dir)
        if count == 0:
            print(f"  {label:12s}  {dim('no hooks installed')}")
            continue
        profile = _detect_profile(hooks_dir, settings_path)
        print(f"  {label:12s}  {ok(f'{count} hooks')} {dim(f'({profile} profile)')}")
    print()

    # --- MCP ---
    print(header("[MCP]"))
    configured, mcp_msg = _check_mcp_stdio_config()
    if configured:
        print(f"  stdio:      {ok(f'configured as {mcp_msg}')}")
    else:
        print(f"  stdio:      {warn(mcp_msg)}")

    if reachable:
        print(f"  SSE:        {ok(url + '/mcp/sse')}")
    else:
        print(f"  SSE:        {dim('unavailable (server not running)')}")
    print()
