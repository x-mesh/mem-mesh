"""Onboarding wizard for mem-mesh.

Performs 3-step setup:
1. API server connectivity check
2. Hook installation
3. MCP configuration check
"""

import json
import os
from pathlib import Path
from typing import Optional

from app.cli.hooks.colors import bold, dim, err, header, info, ok, warn
from app.cli.hooks.constants import DEFAULT_URL, CLAUDE_HOOKS_DIR
from app.cli.hooks.status import check_connectivity, resolve_api_url


def _detect_target() -> str:
    """Auto-detect which IDE to install hooks for."""
    targets = []
    if CLAUDE_HOOKS_DIR.parent.exists():
        targets.append("claude")
    kiro_dir = Path.home() / ".kiro"
    if kiro_dir.exists():
        targets.append("kiro")
    cursor_dir = Path.home() / ".cursor"
    if cursor_dir.exists():
        targets.append("cursor")

    if not targets:
        return "claude"  # default
    if len(targets) == 1:
        return targets[0]
    return "all"


def _check_mcp_config(url: str) -> tuple[bool, str]:
    """Check if MCP server is configured in claude_desktop_config.json."""
    config_path = Path.home() / ".claude" / "claude_desktop_config.json"
    if not config_path.exists():
        return False, "not found"
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, "parse error"

    mcp_servers = data.get("mcpServers", {})
    for name, server in mcp_servers.items():
        if "mem-mesh" in name.lower() or "mem_mesh" in name.lower():
            return True, f"configured as '{name}'"
        # Check command/args for mem-mesh references
        cmd = server.get("command", "")
        args = server.get("args", [])
        if "mem-mesh" in cmd or any("mem-mesh" in str(a) or "mem_mesh" in str(a) for a in args):
            return True, f"configured as '{name}'"

    return False, "no mem-mesh entry"


def cmd_onboarding(
    url: Optional[str] = None,
    target: str = "auto",
    profile: str = "standard",
    yes: bool = False,
) -> None:
    """Run the onboarding wizard."""
    print()
    print(header("=== mem-mesh setup ==="))
    print()

    # --- Step 1: Server check ---
    print(bold("[1/3] API Server Check"))

    if url:
        resolved_url = url.rstrip("/")
        source = "command line"
    else:
        resolved_url, source = resolve_api_url()

    print(f"  URL:          {info(resolved_url)} {dim(f'(from {source})')}")

    reachable, message = check_connectivity(resolved_url)
    if reachable:
        print(f"  Health check: {ok(message)}")
    else:
        print(f"  Health check: {err(message)}")
        print()
        print(warn("  Server is not running."))
        print(dim("  Start it with: mem-mesh serve"))
        print(dim("  Or with Docker: docker-compose up -d"))
        print()
        if not yes:
            answer = input("  Continue without server? [Y/n] ").strip().lower()
            if answer in ("n", "no"):
                print("\nSetup cancelled.")
                return
        else:
            print(dim("  (--yes: continuing without server)"))
    print()

    # --- Step 2: Hook installation ---
    print(bold("[2/3] Hook Installation"))

    if target == "auto":
        target = _detect_target()
        print(f"  Detected IDE: {info(target)}")
    else:
        print(f"  Target:       {info(target)}")
    print(f"  Profile:      {info(profile)}")

    if not yes:
        answer = input(f"  Install hooks for {target}? [Y/n] ").strip().lower()
        if answer in ("n", "no"):
            print(dim("  Skipping hook installation."))
            print()
            _step3_mcp(resolved_url)
            _print_summary(resolved_url, reachable, False, target)
            return

    # Use the resolved URL (or DEFAULT_URL if not set)
    install_url = resolved_url if resolved_url else DEFAULT_URL

    try:
        from app.cli.install_hooks import cmd_install

        cmd_install(target, install_url, "api", "", profile)
        hooks_installed = True
        print(f"  {ok('Hooks installed successfully.')}")
    except Exception as e:
        print(f"  {err(f'Hook installation failed: {e}')}")
        hooks_installed = False
    print()

    # --- Step 3: MCP config ---
    _step3_mcp(resolved_url)

    # --- Summary ---
    _print_summary(resolved_url, reachable, hooks_installed, target)


def _step3_mcp(url: str) -> None:
    """Step 3: Check MCP configuration."""
    print(bold("[3/3] MCP Configuration"))

    configured, mcp_message = _check_mcp_config(url)
    if configured:
        print(f"  claude_desktop_config.json: {ok(mcp_message)}")
    else:
        print(f"  claude_desktop_config.json: {warn(mcp_message)}")
        print(dim("  To add MCP server, update ~/.claude/claude_desktop_config.json"))
        print(dim("  with a mem-mesh server entry pointing to your API URL."))
    print()


def _print_summary(url: str, server_ok: bool, hooks_ok: bool, target: str) -> None:
    """Print onboarding summary."""
    print(header("=== Setup Complete ==="))
    print()
    print(f"  API server:  {ok(url) if server_ok else warn(url + ' (not running)')}")
    print(f"  Dashboard:   {info(url + '/dashboard') if server_ok else dim('unavailable')}")
    print(f"  Hooks:       {ok(f'installed ({target})') if hooks_ok else warn('not installed')}")
    print()
    if not server_ok:
        print(f"  {bold('Next step:')} Start the server with {info('mem-mesh serve')}")
    print(dim("  Run 'mem-mesh status' for full system check."))
    print(dim("  Run 'mem-mesh hooks doctor' for hook diagnostics."))
    print()
