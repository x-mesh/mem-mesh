"""IDE-specific hook uninstallation logic."""

from app.cli.hooks.constants import (
    CLAUDE_HOOKS_DIR,
    CLAUDE_SETTINGS,
    CURSOR_HOOKS_DIR,
    CURSOR_SETTINGS,
    KIRO_CLI_AGENT,
    KIRO_HOOKS_DIR,
    KIRO_SCRIPTS_DIR,
    KIRO_SETTINGS,
)
from app.cli.hooks.json_ops import (
    _atomic_write_text,
    _remove_kiro_mem_mesh_hooks,
    _remove_mem_mesh_hooks_from_json,
)
import json


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
        "mem-mesh-user-prompt-submit.sh",
        "mem-mesh-subagent-start.sh",
        "mem-mesh-subagent-stop.sh",
        "mem-mesh-task-completed.sh",
    ):
        script = CLAUDE_HOOKS_DIR / name
        if script.exists():
            script.unlink()
            print(f"  removed {script}")

    print("[claude] Removing mem-mesh hooks from settings.json...")
    _remove_mem_mesh_hooks_from_json(CLAUDE_SETTINGS)

    print("[claude] Done.")


def _remove_kiro_cli_agent_hook(path) -> None:
    """Remove mem-mesh stop hook entries from a Kiro CLI custom agent."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(data, dict):
        return
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return
    stop_hooks = hooks.get("stop")
    if not isinstance(stop_hooks, list):
        return
    filtered = [
        entry
        for entry in stop_hooks
        if not (
            isinstance(entry, dict)
            and "mem-mesh-stop.sh" in str(entry.get("command", ""))
        )
    ]
    if filtered == stop_hooks:
        return
    if filtered:
        hooks["stop"] = filtered
    else:
        hooks.pop("stop", None)
    if not hooks:
        data.pop("hooks", None)
    _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _uninstall_kiro() -> None:
    """Remove mem-mesh hooks for Kiro."""
    print("[kiro] Removing hook scripts...")
    for script in (
        KIRO_SCRIPTS_DIR / "mem-mesh-stop.sh",
        KIRO_HOOKS_DIR / "mem-mesh-stop.sh",
        KIRO_HOOKS_DIR / "mem-mesh-save-response.kiro.hook",
    ):
        if script.exists():
            script.unlink()
            print(f"  removed {script}")

    print("[kiro] Removing legacy mem-mesh hooks from hooks.json...")
    _remove_kiro_mem_mesh_hooks(KIRO_SETTINGS)
    print("[kiro] Removing mem-mesh hook from Kiro CLI agent...")
    _remove_kiro_cli_agent_hook(KIRO_CLI_AGENT)

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

    print("[cursor] Removing mem-mesh hooks from hooks.json...")
    _remove_mem_mesh_hooks_from_json(CURSOR_SETTINGS)

    print("[cursor] Done.")
