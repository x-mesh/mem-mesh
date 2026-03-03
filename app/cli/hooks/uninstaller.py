"""IDE-specific hook uninstallation logic."""

from app.cli.hooks.constants import (
    CLAUDE_HOOKS_DIR,
    CLAUDE_SETTINGS,
    CURSOR_HOOKS_DIR,
    CURSOR_SETTINGS,
    KIRO_HOOKS_DIR,
    KIRO_SETTINGS,
)
from app.cli.hooks.json_ops import _remove_json_key, _remove_kiro_mem_mesh_hooks


def _uninstall_claude() -> None:
    """Remove mem-mesh hooks for Claude Code."""
    print("[claude] Removing hook scripts...")
    for name in (
        "mem-mesh-session-start.sh",
        "mem-mesh-track.sh",
        "mem-mesh-stop.sh",
        "mem-mesh-stop-decide.sh",
        "mem-mesh-stop-enhanced.sh",
        "mem-mesh-reflect.sh",
        "mem-mesh-session-end.sh",
        "mem-mesh-precompact.sh",
    ):
        script = CLAUDE_HOOKS_DIR / name
        if script.exists():
            script.unlink()
            print(f"  removed {script}")

    print("[claude] Removing hooks from settings.json...")
    _remove_json_key(CLAUDE_SETTINGS, "hooks")

    print("[claude] Done.")


def _uninstall_kiro() -> None:
    """Remove mem-mesh hooks for Kiro."""
    print("[kiro] Removing hook scripts...")
    script = KIRO_HOOKS_DIR / "mem-mesh-stop.sh"
    if script.exists():
        script.unlink()
        print(f"  removed {script}")

    print("[kiro] Removing mem-mesh hooks from hooks.json...")
    _remove_kiro_mem_mesh_hooks(KIRO_SETTINGS)

    print("[kiro] Done.")


def _uninstall_cursor() -> None:
    """Remove mem-mesh hooks for Cursor."""
    print("[cursor] Removing hook scripts...")
    for name in (
        "mem-mesh-session-start.sh",
        "mem-mesh-track.sh",
        "mem-mesh-stop.sh",
        "mem-mesh-session-end.sh",
    ):
        script = CURSOR_HOOKS_DIR / name
        if script.exists():
            script.unlink()
            print(f"  removed {script}")

    print("[cursor] Removing hooks from hooks.json...")
    _remove_json_key(CURSOR_SETTINGS, "hooks")

    print("[cursor] Done.")
