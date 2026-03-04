"""Project-local hook synchronization commands."""

import json
import sys
from pathlib import Path
from typing import Optional

from app.cli.prompts.behaviors import PROMPT_VERSION
from app.cli.prompts.renderers import (
    VERSION_MARKER,
    render_cursor_followup,
    render_kiro_auto_create_pin,
    render_kiro_auto_save,
    render_kiro_load_context,
    render_rules_text,
)
from app.cli.hooks.renderer import _write_script
from app.cli.hooks.installer import _build_cursor_hooks_settings
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

    # session-start: uses Python direct import (project-local)
    session_start_content = f"""#!/bin/bash
{VERSION_MARKER}
# mem-mesh Session Start Hook for Cursor (project-local)
# Injects mem-mesh usage instructions into the session context.

set -euo pipefail

INPUT=$(cat)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

RESUME_OUTPUT=""
RESUME_OUTPUT=$(python3 -c "
import sys, json
sys.path.insert(0, '$PROJECT_ROOT')
try:
    from app.core.services.pin_service import PinService
    from app.core.storage.direct import DirectStorageManager
    import asyncio

    async def get_resume():
        storage = DirectStorageManager()
        await storage.initialize()
        pin_svc = PinService(storage)
        result = await pin_svc.session_resume('{project_id}', expand='smart')
        return json.dumps(result, ensure_ascii=False, default=str)

    print(asyncio.run(get_resume()))
except Exception as e:
    print(json.dumps({{'error': str(e)}}))
" 2>/dev/null) || RESUME_OUTPUT='{{"error": "mem-mesh not available"}}'

RULES_TEXT="{render_rules_text(project_id)}"

CONTEXT="## mem-mesh Memory Integration (Auto-loaded)

### 세션 복원 결과
\\`\\`\\`json
${{RESUME_OUTPUT}}
\\`\\`\\`

### 작업 규칙
$RULES_TEXT"

python3 -c "
import json, sys
ctx = sys.stdin.read()
print(json.dumps({{'hookSpecificOutput': {{'hookEventName': 'SessionStart', 'additionalContext': ctx}}}}))
" <<< "$CONTEXT"
"""

    # auto-save (stop event)
    followup_msg = render_cursor_followup(project_id)
    auto_save_content = f"""#!/bin/bash
{VERSION_MARKER}
# mem-mesh Auto-Save Hook for Cursor (stop event, project-local)

set -euo pipefail

INPUT=$(cat)

HAS_TOOL_USE=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    transcript = data.get('transcript', [])
    meaningful = any(
        msg.get('type') == 'tool_use' and
        msg.get('tool_name', '') in ('Edit', 'Write', 'Bash', 'NotebookEdit')
        for msg in transcript
        if isinstance(msg, dict)
    )
    print('true' if meaningful else 'false')
except Exception:
    print('false')
" 2>/dev/null) || HAS_TOOL_USE="false"

if [ "$HAS_TOOL_USE" = "true" ]; then
    python3 -c "
import json
print(json.dumps({{'followup_message': '''{followup_msg}'''}}))
"
else
    echo '{{}}'
fi
"""

    # session-end
    session_end_content = f"""#!/bin/bash
{VERSION_MARKER}
# mem-mesh Session End Hook for Cursor (project-local)

set -euo pipefail

INPUT=$(cat)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

python3 -c "
import sys, json
sys.path.insert(0, '$PROJECT_ROOT')
try:
    from app.core.services.pin_service import PinService
    from app.core.storage.direct import DirectStorageManager
    import asyncio

    async def end_session():
        storage = DirectStorageManager()
        await storage.initialize()
        pin_svc = PinService(storage)
        result = await pin_svc.session_end('{project_id}')
        return result

    asyncio.run(end_session())
except Exception:
    pass
" 2>/dev/null || true
"""

    print("[cursor] Regenerating project-local hooks...")
    scripts = {
        "mem-mesh-session-start.sh": session_start_content,
        "mem-mesh-auto-save.sh": auto_save_content,
        "mem-mesh-session-end.sh": session_end_content,
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
