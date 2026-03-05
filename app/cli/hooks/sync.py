"""Project-local hook synchronization commands."""

import json
import sys
from pathlib import Path
from typing import Optional

from app.cli.prompts.behaviors import PROMPT_VERSION
from app.cli.prompts.renderers import (
    render_kiro_auto_create_pin,
    render_kiro_auto_save,
    render_kiro_load_context,
)
from app.cli.hooks.renderer import _write_script
from app.cli.hooks.cursor_adapters import (
    adapt_cursor_before_submit_prompt,
    adapt_cursor_precompact,
    adapt_cursor_subagent_start,
    adapt_cursor_subagent_stop,
)
from app.cli.hooks.installer import _build_cursor_hooks_settings
from app.cli.hooks.templates import (
    CURSOR_PROJECT_AUTO_SAVE_TEMPLATE,
    CURSOR_PROJECT_SESSION_END_TEMPLATE,
    CURSOR_PROJECT_SESSION_START_TEMPLATE,
    LOCAL_PRECOMPACT_HOOK_TEMPLATE,
    LOCAL_SUBAGENT_START_HOOK_TEMPLATE,
    LOCAL_SUBAGENT_STOP_HOOK_TEMPLATE,
    LOCAL_USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
)
from app.cli.hooks.renderer import _render_local_template
from app.cli.hooks.json_ops import _remove_mem_mesh_hooks_from_json


def _find_project_root() -> Optional[Path]:
    """Find the mem-mesh project root (where CLAUDE.md exists)."""
    # First try: relative to this file
    candidate = Path(__file__).resolve().parent.parent.parent.parent
    if (candidate / "CLAUDE.md").exists() or (candidate / "pyproject.toml").exists():
        return candidate
    # Second try: CWD
    cwd = Path.cwd()
    if (cwd / "CLAUDE.md").exists() or (cwd / "pyproject.toml").exists():
        return cwd
    return None


def cmd_sync_project(target: str = "all", project_id: str = "mem-mesh") -> None:
    """Regenerate project-local hooks from shared prompt definitions."""
    project_root = _find_project_root()
    if not project_root:
        print("Error: Could not find project root. Run from the mem-mesh directory.")
        sys.exit(1)

    print(f"=== sync-project (prompt-version: {PROMPT_VERSION}) ===")
    print(f"Project root: {project_root}\n")

    if target in ("kiro", "all"):
        _sync_kiro_hooks(project_root, project_id)

    if target in ("cursor", "all"):
        _sync_cursor_hooks(project_root, project_id)

    print("\nSync complete.")


def _sync_kiro_hooks(project_root: Path, project_id: str) -> None:
    """Regenerate behavioral .kiro.hook files from shared prompts."""
    kiro_dir = project_root / ".kiro" / "hooks"
    kiro_dir.mkdir(parents=True, exist_ok=True)

    hooks = {
        "auto-save-conversations": render_kiro_auto_save(project_id),
        "auto-create-pin-on-task": render_kiro_auto_create_pin(project_id),
        "load-project-context": render_kiro_load_context(project_id),
    }

    print("[kiro] Regenerating behavioral hooks...")
    for name, hook_data in hooks.items():
        hook_file = kiro_dir / f"{name}.kiro.hook"
        hook_file.write_text(
            json.dumps(hook_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"  -> {hook_file}")

    print("[kiro] Done. (manual-* hooks untouched)")


def _sync_cursor_hooks(project_root: Path, project_id: str) -> None:
    """Regenerate project-local Cursor hooks from shared prompts."""
    cursor_dir = project_root / ".cursor" / "hooks"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    session_start_content = _render_local_template(
        CURSOR_PROJECT_SESSION_START_TEMPLATE, str(project_root), project_id=project_id
    ).replace("__PROJECT_ID__", project_id)
    auto_save_content = _render_local_template(
        CURSOR_PROJECT_AUTO_SAVE_TEMPLATE, str(project_root), project_id=project_id
    )
    session_end_content = _render_local_template(
        CURSOR_PROJECT_SESSION_END_TEMPLATE, str(project_root), project_id=project_id
    ).replace("__PROJECT_ID__", project_id)

    before_submit_prompt_content = adapt_cursor_before_submit_prompt(
        _render_local_template(LOCAL_USER_PROMPT_SUBMIT_HOOK_TEMPLATE, str(project_root))
    )
    precompact_content = adapt_cursor_precompact(
        _render_local_template(LOCAL_PRECOMPACT_HOOK_TEMPLATE, str(project_root))
    )
    subagent_start_content = adapt_cursor_subagent_start(
        _render_local_template(LOCAL_SUBAGENT_START_HOOK_TEMPLATE, str(project_root))
    )
    subagent_stop_content = adapt_cursor_subagent_stop(
        _render_local_template(LOCAL_SUBAGENT_STOP_HOOK_TEMPLATE, str(project_root))
    )

    print("[cursor] Regenerating project-local hooks...")
    scripts = {
        "mem-mesh-session-start.sh": session_start_content,
        "mem-mesh-auto-save.sh": auto_save_content,
        "mem-mesh-session-end.sh": session_end_content,
        "mem-mesh-before-submit-prompt.sh": before_submit_prompt_content,
        "mem-mesh-precompact.sh": precompact_content,
        "mem-mesh-subagent-start.sh": subagent_start_content,
        "mem-mesh-subagent-stop.sh": subagent_stop_content,
    }
    for name, content in scripts.items():
        _write_script(cursor_dir / name, content)
        print(f"  -> {cursor_dir / name}")

    template_path = project_root / ".cursor" / "hooks.mem-mesh.example.json"
    template_data = _build_cursor_hooks_settings(cursor_dir, scope="project")
    template_path.write_text(
        json.dumps(template_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"  -> {template_path}")

    settings_path = project_root / ".cursor" / "hooks.json"
    _remove_mem_mesh_hooks_from_json(settings_path)
    if settings_path.exists():
        print(f"  -> cleaned mem-mesh entries from {settings_path}")

    print("[cursor] Done.")
