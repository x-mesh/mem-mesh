"""Unified system status for mem-mesh.

Shows server, hooks, token and MCP configuration status in one view. All facts
come from the shared ``app.cli.hooks.diagnostics`` collectors so this surface
stays consistent with ``config``, ``doctor`` and ``mcp verify``.
"""

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
from app.cli.hooks.diagnostics import (
    collect_claude_overrides,
    collect_mcp_status,
    collect_token_status,
    entry_json,
)
from app.cli.hooks.render import render_entry_source
from app.cli.hooks.status import (
    _detect_profile,
    _extract_url_from_script,
    probe_api,
    resolve_api_url,
)


def _count_installed_hooks(hooks_dir: Path) -> int:
    """Count installed mem-mesh hook scripts."""
    if not hooks_dir.exists():
        return 0
    return len(list(hooks_dir.glob("mem-mesh-*.sh")))


def _render_token_section() -> None:
    """[Hook Token]: source + masked preview (never the raw value)."""
    print(header("[Hook Token]"))
    token = collect_token_status()
    if token.source == "env":
        print(
            f"  MEM_MESH_HOOK_TOKEN: {ok('set')} {info(token.masked)} "
            f"{dim('(shell env — HTTP hooks/MCP authenticated)')}"
        )
    elif token.present:
        label = {"data_file": "data dir", "legacy_file": "~/.mem-mesh"}.get(
            token.source, token.source
        )
        print(
            f"  MEM_MESH_HOOK_TOKEN: {warn('file only')} {info(token.masked)} "
            f"{dim(f'(from {label}; HTTP/MCP need: mem-mesh hooks setup-token)')}"
        )
    else:
        print(
            f"  MEM_MESH_HOOK_TOKEN: {dim('not set')} "
            f"{dim('(only needed for an authenticated server)')}"
        )
    print()


def _render_mcp_section(url: str, verbose: bool) -> bool:
    """[MCP]: every detected dev tool's mem-mesh entry. Returns True if any issue."""
    print(header("[MCP]"))
    tools = collect_mcp_status(url)
    installed = [t for t in tools if t.installed]
    any_issue = False

    if not installed:
        print(f"  {dim('No supported dev tools detected.')}")
        print()
        return False

    for t in installed:
        mode = t.mode or "-"
        if t.configured and t.verified:
            print(f"  {ok('✓')} {t.name:<15} {info(mode):<14} {dim(t.verify_message)}")
        elif t.configured:
            any_issue = True
            print(
                f"  {warn('!')} {t.name:<15} {info(mode):<14} {warn(t.verify_message)}"
            )
        else:
            print(f"  {dim('·')} {t.name:<15} {dim('not configured')}")
        if verbose and t.configured:
            render_entry_source(t.config_path, t.entry_lines, entry_json(t.entry))

    skipped = [t for t in tools if not t.installed]
    if skipped:
        print(f"  {dim('not installed: ' + ', '.join(t.name for t in skipped))}")
    print()

    # Claude Code project-scoped overrides that shadow the global entry.
    overrides = collect_claude_overrides()
    if overrides:
        any_issue = True
        print(header("[MCP Overrides] (Claude Code, per-project)"))
        home = str(Path.home())
        for ov in overrides:
            path = (
                ("~" + ov.project_path[len(home) :])
                if ov.project_path.startswith(home)
                else ov.project_path
            )
            flag = warn("differs from global") if ov.differs else dim("matches global")
            print(f"  {warn('!') if ov.differs else dim('·')} {path}")
            print(f"      {dim(ov.summary)}  {flag}")
        print(
            dim(
                "  These shadow the global entry for those projects. Clean: mem-mesh mcp clean"
            )
        )
        print()

    return any_issue


def cmd_system_status(verbose: bool = False) -> None:
    """Print unified system status."""
    print()
    print(header("=== mem-mesh system status ==="))
    print()

    # --- Server (3-state probe: ok / auth-required / unreachable) ---
    print(header("[Server]"))
    baked_url = _extract_url_from_script(
        CLAUDE_HOOKS_DIR / "mem-mesh-session-start.sh"
    ) or _extract_url_from_script(CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh")
    url, source = resolve_api_url(baked_url)
    print(f"  URL:        {info(url)} {dim(f'(from {source})')}")

    probe = probe_api(url)
    if probe.ok:
        print(f"  Health:     {ok(probe.message)}")
        print(f"  Dashboard:  {info(url + '/dashboard')}")
    elif probe.auth_required:
        print(f"  Health:     {warn(probe.message)}")
        print(
            f"  {dim('Server is up but gated by auth — set MEM_MESH_HOOK_TOKEN or check your proxy.')}"
        )
    else:
        print(f"  Health:     {err(probe.message)}")
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

    # --- Hook token ---
    _render_token_section()

    # --- MCP (all detected dev tools) ---
    any_issue = _render_mcp_section(url, verbose)
    if probe.ok:
        print(header("[MCP SSE]"))
        print(f"  SSE:        {ok(url + '/mcp/sse')}")
        print()

    if any_issue or not probe.ok:
        print(dim("  → run `mem-mesh doctor` for full diagnostics and fixes."))
        print()
