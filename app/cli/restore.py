"""`mem-mesh restore` — recover a config file from a timestamped backup.

The MCP setup and hook installers write ``<file>.<YYYYMMDD_HHMMSS>.bak`` before
every change (see :func:`app.cli.hooks.json_ops.timestamped_backup`). This is the
single recovery entry point that lists those backups across every known config
file (all dev-tool MCP configs + the hook ``settings.json`` files) and restores a
chosen one — always backing up the *current* file first, so a restore is itself
reversible.
"""

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from app.cli.hooks.colors import bold, dim, err, header, info, ok, warn
from app.cli.hooks.constants import CLAUDE_SETTINGS, CURSOR_SETTINGS, KIRO_SETTINGS
from app.cli.hooks.json_ops import timestamped_backup

# <name>.<YYYYMMDD_HHMMSS>.bak  (the format timestamped_backup writes)
_TS_RE = re.compile(r"\.(\d{8}_\d{6})\.bak$")


def _short(path: Path) -> str:
    home = str(Path.home())
    s = str(path)
    return "~" + s[len(home) :] if s.startswith(home) else s


def _candidate_files() -> List[Tuple[str, Path]]:
    """All config files that may have backups: dev-tool MCP configs + hook settings."""
    from app.cli.mcp_config import detect_tools

    out: List[Tuple[str, Path]] = []
    seen = set()

    for tool in detect_tools():
        p: Path = tool["config_path"]
        if str(p) not in seen:
            seen.add(str(p))
            out.append((f"{tool['name']} (MCP)", p))

    for label, p in [
        ("Claude Code (hooks)", CLAUDE_SETTINGS),
        ("Kiro (hooks)", KIRO_SETTINGS),
        ("Cursor (hooks)", CURSOR_SETTINGS),
    ]:
        if str(p) not in seen:
            seen.add(str(p))
            out.append((label, p))

    return out


def _backups_for(path: Path) -> List[Path]:
    """Backups for ``path``, newest first. Includes the malformed ``<name>.bak``."""
    parent = path.parent
    if not parent.exists():
        return []
    matches = list(parent.glob(path.name + ".*.bak")) + list(
        parent.glob(path.name + ".bak")
    )
    uniq = {str(p): p for p in matches}.values()

    def _key(p: Path) -> str:
        m = _TS_RE.search(p.name)
        return m.group(1) if m else ""  # untimestamped (malformed) sorts last

    return sorted(uniq, key=_key, reverse=True)


def _target_for(backup: Path) -> Optional[Path]:
    """Derive the original file a backup restores to (strip the .<ts>.bak suffix)."""
    name = backup.name
    m = _TS_RE.search(name)
    if m:
        return backup.with_name(name[: m.start()])
    if name.endswith(".bak"):
        return backup.with_name(name[:-4])
    return None


def _describe(backup: Path) -> str:
    """A human-readable line for one backup: timestamp + size."""
    m = _TS_RE.search(backup.name)
    when = backup.name
    if m:
        try:
            when = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S").strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            when = m.group(1)
    elif backup.name.endswith(".bak"):
        when = "untimestamped (malformed-file backup)"
    try:
        size = backup.stat().st_size
    except OSError:
        size = 0
    return f"{when}  {dim(f'({size} bytes)')}"


def _prompt_choice(prompt: str, options: List[str]) -> int:
    """Numbered prompt; returns the chosen 0-based index, or -1 to cancel."""
    for i, opt in enumerate(options, 1):
        print(f"    {bold(str(i))}. {opt}")
    print(f"    {bold('0')}. {dim('cancel')}")
    while True:
        raw = input(f"  {prompt} ").strip()
        if raw == "0":
            return -1
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print(f"    Enter 0-{len(options)}")


def _do_restore(backup: Path, target: Path) -> Optional[Path]:
    """Back up the current target (if any), then copy the backup over it.

    Returns the path of the current-state backup (so the restore is reversible),
    or None when the target did not previously exist.
    """
    safety = timestamped_backup(target)  # snapshot current before overwriting
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, target)
    return safety


def cmd_restore(
    list_only: bool = False,
    from_backup: Optional[str] = None,
    yes: bool = False,
) -> int:
    """Restore a config file from a backup. Returns an exit code."""
    print()
    print(header("=== mem-mesh restore ==="))
    print()

    # --- Direct restore of a specific backup file ---
    if from_backup:
        backup = Path(from_backup).expanduser()
        if not backup.exists():
            print(f"  {err(f'backup not found: {backup}')}")
            return 1
        target = _target_for(backup)
        if target is None:
            print(
                f"  {err('not a recognizable backup name (expected <file>.<ts>.bak)')}"
            )
            return 1
        print(f"  Restore: {info(_short(backup))}")
        print(f"       to: {info(_short(target))}")
        if not yes:
            ans = input(f"  {warn('Overwrite current file?')} [y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                print(f"  {dim('cancelled.')}")
                return 0
        safety = _do_restore(backup, target)
        print(f"  {ok('restored.')}")
        if safety:
            print(dim(f"  current file backed up to {_short(safety)}"))
        print()
        return 0

    # --- Collect every file that has at least one backup ---
    files_with_backups: List[Tuple[str, Path, List[Path]]] = []
    for label, path in _candidate_files():
        backups = _backups_for(path)
        if backups:
            files_with_backups.append((label, path, backups))

    if not files_with_backups:
        print(f"  {dim('No backups found.')}")
        print(
            dim("  Backups are created automatically before mem-mesh changes a config.")
        )
        print()
        return 0

    # --- List mode: print and exit ---
    if list_only:
        for label, path, backups in files_with_backups:
            print(f"  {bold(label)}  {dim(_short(path))}")
            for b in backups:
                print(f"      {_describe(b)}")
            print()
        print(
            dim(
                "  Restore with: mem-mesh restore --from <backup>  (or run interactively)"
            )
        )
        print()
        return 0

    # --- Interactive: pick a file, then a backup ---
    if not _interactive_ok():
        print(f"  {warn('Non-interactive shell — use --list then --from <backup>.')}")
        print()
        return 1

    file_options = [
        f"{label}  {dim(_short(path))}  {dim(f'({len(backups)} backups)')}"
        for label, path, backups in files_with_backups
    ]
    print(f"  {bold('Which config to restore?')}")
    fi = _prompt_choice("Choose: ", file_options)
    if fi < 0:
        print(f"  {dim('cancelled.')}")
        return 0
    label, path, backups = files_with_backups[fi]
    print()

    print(f"  {bold(f'Backups for {label}:')}")
    backup_options = [_describe(b) for b in backups]
    bi = _prompt_choice("Restore which backup: ", backup_options)
    if bi < 0:
        print(f"  {dim('cancelled.')}")
        return 0
    chosen = backups[bi]
    print()

    print(f"  Restore: {info(_short(chosen))}")
    print(f"       to: {info(_short(path))}")
    if not yes:
        ans = input(f"  {warn('Overwrite current file?')} [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print(f"  {dim('cancelled.')}")
            return 0
    safety = _do_restore(chosen, path)
    print(f"  {ok('restored.')}")
    if safety:
        print(dim(f"  current file backed up to {_short(safety)}"))
    print()
    return 0


def _interactive_ok() -> bool:
    import sys

    return sys.stdin.isatty() and sys.stdout.isatty()
