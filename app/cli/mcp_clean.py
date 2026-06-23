"""`mem-mesh mcp clean` — remove project-scoped mem-mesh MCP shadows.

Claude Code stores per-project servers under ``projects.<path>.mcpServers`` in
``~/.claude.json``. When a ``mem-mesh`` entry lives there it OVERRIDES the global
one for that project — so a project can quietly talk to a different/stale server
than ``mem-mesh status`` reports. This command lists those shadows and removes
them (backing up ``~/.claude.json`` first) so the single global entry wins
everywhere.
"""

import json
from pathlib import Path
from typing import List

from app.cli.hooks.colors import bold, dim, err, header, info, ok, warn
from app.cli.hooks.diagnostics import collect_claude_overrides
from app.cli.hooks.json_ops import timestamped_backup

CLAUDE_JSON = Path.home() / ".claude.json"


def _short(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path


def cmd_mcp_clean(
    list_only: bool = False, yes: bool = False, dry_run: bool = False
) -> int:
    """Remove project-scoped mem-mesh MCP overrides. Returns an exit code."""
    print()
    print(header("=== mem-mesh mcp clean ==="))
    print()

    overrides = collect_claude_overrides()
    if not overrides:
        print(f"  {ok('No project-scoped overrides found.')}")
        print(dim("  The global ~/.claude.json entry is the single source."))
        print()
        return 0

    print(
        f"  {bold(str(len(overrides)))} project-scoped mem-mesh override(s) "
        f"in {info('~/.claude.json')}:"
    )
    for ov in overrides:
        flag = warn("differs from global") if ov.differs else dim("matches global")
        print(f"  {warn('!') if ov.differs else dim('·')} {_short(ov.project_path)}")
        print(f"      {dim(ov.summary)}  {flag}")
    print()
    print(dim("  Removing these makes each project fall back to the global entry."))
    print()

    if list_only or dry_run:
        print(
            dim(
                "  (dry run — nothing changed). Run without --list/--dry-run to remove."
            )
        )
        print()
        return 0

    if not yes:
        ans = input(f"  {warn('Remove all of the above?')} [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print(f"  {dim('cancelled.')}")
            print()
            return 0

    try:
        data = json.loads(CLAUDE_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  {err(f'cannot read ~/.claude.json: {e}')}")
        return 1

    removed: List[str] = []
    for path, conf in (data.get("projects") or {}).items():
        servers = (conf or {}).get("mcpServers", {})
        if "mem-mesh" in servers:
            del servers["mem-mesh"]
            removed.append(path)

    if not removed:
        print(f"  {dim('nothing to remove.')}")
        return 0

    backup = timestamped_backup(CLAUDE_JSON)
    CLAUDE_JSON.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"  {ok(f'Removed {len(removed)} override(s).')}")
    if backup:
        print(dim(f"  backup: {_short(str(backup))}"))
    print(dim("  Restart Claude Code so it reloads the global config."))
    print()
    return 0
