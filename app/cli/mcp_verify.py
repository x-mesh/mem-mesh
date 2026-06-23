"""`mem-mesh mcp verify` — verify the mem-mesh MCP entry across every dev tool.

Reuses the shared ``collect_mcp_status`` collector so the verdict matches what
``status``/``config``/``doctor`` report. Exit code reflects health so the
command is scriptable: 0 when every configured tool verifies, non-zero when any
configured tool has a problem.
"""

from app.cli.hooks.colors import bold, dim, err, header, info, ok, warn
from app.cli.hooks.constants import DEFAULT_URL
from app.cli.hooks.diagnostics import collect_mcp_status, entry_json
from app.cli.hooks.render import render_entry_source


def cmd_mcp_verify(url: str = DEFAULT_URL, verbose: bool = False) -> int:
    """Verify MCP configuration for all detected tools. Returns an exit code."""
    print()
    print(header("=== mem-mesh MCP verification ==="))
    print(f"  API URL: {info(url)}")
    print()

    tools = collect_mcp_status(url)
    installed = [t for t in tools if t.installed]

    if not installed:
        print(f"  {warn('No supported dev tools detected.')}")
        print(
            dim(
                "  Supported: Codex, Claude Code, Cursor, Kiro, Antigravity, "
                "Claude Desktop, VS Code, Windsurf, LM Studio"
            )
        )
        print()
        return 0

    configured = [t for t in installed if t.configured]
    failed = [t for t in configured if not t.verified]

    for t in installed:
        mode = t.mode or "-"
        if not t.configured:
            print(f"  {dim('·')} {t.name:<15} {dim('not configured')}")
            continue
        if t.verified:
            print(f"  {ok('✓')} {t.name:<15} {info(mode):<8} {dim(t.verify_message)}")
        else:
            print(f"  {err('✗')} {t.name:<15} {info(mode):<8} {err(t.verify_message)}")
        if verbose and t.configured:
            render_entry_source(t.config_path, t.entry_lines, entry_json(t.entry))
    print()

    # Summary
    print(header("[Summary]"))
    print(
        f"  {bold(str(len(configured)))} configured, "
        f"{ok(str(len(configured) - len(failed)))} ok, "
        f"{(err if failed else dim)(str(len(failed)))} failing"
    )
    if failed:
        print()
        print(dim("  → run `mem-mesh doctor` for connectivity + auth details."))
    print()

    return 1 if failed else 0
