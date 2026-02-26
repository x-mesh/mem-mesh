#!/usr/bin/env python3
"""mem-mesh-hooks: Install/uninstall mem-mesh hooks for Claude Code, Kiro, and Cursor.

Prompts and behavioral rules are defined in app.cli.prompts.behaviors (single
source of truth).  IDE-specific renderers in app.cli.prompts.renderers transform
those canonical definitions into each IDE's native format.

Bump PROMPT_VERSION in behaviors.py when rules change, then re-run:
    mem-mesh-hooks install --target all
    mem-mesh-hooks sync-project
"""

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.cli.prompts.behaviors import PROMPT_VERSION
from app.cli.prompts.renderers import (
    VERSION_MARKER,
    extract_prompt_version,
    render_cursor_context,
    render_cursor_followup,
    render_kiro_auto_create_pin,
    render_kiro_auto_save,
    render_kiro_load_context,
    render_rules_text,
)

DEFAULT_URL = "https://meme.24x365.online"

# ---------------------------------------------------------------------------
# Hook script templates — bash boilerplate only; prompt text comes from renderers
# ---------------------------------------------------------------------------

# The __RULES_TEXT__ placeholder is replaced with render_rules_text() output.
# The __FOLLOWUP_MSG__ placeholder is replaced with render_cursor_followup().
# The __DEFAULT_URL__ / __MEM_MESH_PATH__ are replaced at install time.

TRACK_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# PostToolUse hook: track code changes to mem-mesh
# stdin: {"tool_name":"Write|Edit","tool_input":{...}} JSON

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE_PATH" ] && exit 0

# Only track known file types
case "$FILE_PATH" in
  *.py|*.ts|*.js|*.jsx|*.tsx|*.json|*.md|*.yaml|*.yml|*.toml|*.sh) ;;
  *) exit 0 ;;
esac

# Exclude internal files
case "$FILE_PATH" in
  */.cursor/*|*/.claude/*|*/.kiro/*) exit 0 ;;
esac

# Extract project ID from directory name
PROJECT_DIR=$(basename "$(cd "$(dirname "$FILE_PATH")" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null || dirname "$FILE_PATH")")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"

# Build change summary
if [ "$TOOL_NAME" = "Write" ]; then
  PREVIEW=$(echo "$INPUT" | jq -r '.tool_input.content // empty' | head -c 300)
  CONTENT="file: ${FILE_PATH}\nchange: new file or overwrite\ncontent: ${PREVIEW}"
elif [ "$TOOL_NAME" = "Edit" ]; then
  OLD=$(echo "$INPUT" | jq -r '.tool_input.old_string // empty' | head -c 150)
  NEW=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty' | head -c 150)
  CONTENT="file: ${FILE_PATH}\nchange: '${OLD}' -> '${NEW}'"
else
  exit 0
fi

# Minimum length check (API requires >= 10 chars)
[ ${#CONTENT} -lt 15 ] && exit 0

EXT="${FILE_PATH##*.}"

PAYLOAD=$(jq -n \
  --arg content "$CONTENT" \
  --arg project_id "$PROJECT_DIR" \
  --arg source "__SOURCE_TAG__" \
  --arg ext "$EXT" \
  '{
    content: $content,
    project_id: $project_id,
    category: "code_snippet",
    source: $source,
    tags: ["auto-save", "file-change", $ext]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
"""

STOP_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Stop hook: save conversation summary to mem-mesh
# stdin: {"stop_hook_active":bool,"last_assistant_message":"..."} JSON

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

INPUT=$(cat)

# Prevent infinite loop
ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

# Extract message + minimum length filter
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 50 ] && exit 0

SUMMARY=$(echo "$MESSAGE" | head -c 500)

# Extract project ID from CWD
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

PAYLOAD=$(jq -n \
  --arg content "[conversation summary] $SUMMARY" \
  --arg project_id "$PROJECT_DIR" \
  --arg source "__SOURCE_TAG__" \
  '{
    content: $content,
    project_id: $project_id,
    category: "git-history",
    source: $source,
    tags: ["auto-save", "conversation", "__IDE_TAG__"]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
"""

KIRO_STOP_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Kiro agentResponse hook: save conversation summary to mem-mesh

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

RESPONSE="${KIRO_RESULT:-}"
[ ${#RESPONSE} -lt 50 ] && exit 0

SUMMARY=$(echo "$RESPONSE" | head -c 500)

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

PAYLOAD=$(jq -n \
  --arg content "[kiro response] $SUMMARY" \
  --arg project_id "$PROJECT_DIR" \
  --arg source "kiro-hook" \
  '{
    content: $content,
    project_id: $project_id,
    category: "git-history",
    source: $source,
    tags: ["auto-save", "conversation", "kiro"]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
"""

# Cursor sessionStart: injects rules via additional_context.
# __RULES_CONTEXT__ is replaced with render_cursor_context() output.
CURSOR_SESSION_START_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Cursor sessionStart hook: load mem-mesh session context
# Returns additional_context JSON for the agent

set -euo pipefail
command -v jq >/dev/null 2>&1 || { echo '{}'; exit 0; }
command -v curl >/dev/null 2>&1 || { echo '{}'; exit 0; }

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

INPUT=$(cat)

# Detect project from CWD
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"

# Try to fetch session resume data from API
RESUME_DATA=$(curl -s --max-time 5 \
  "${API_URL}/api/pins/session/resume?project_id=${PROJECT_DIR}&expand=smart" \
  2>/dev/null) || RESUME_DATA='{"error": "mem-mesh API not available"}'

CONTEXT="## mem-mesh Memory Integration (Auto-loaded)

### 세션 복원 결과
${RESUME_DATA}

### 작업 규칙
__RULES_TEXT__"

jq -n --arg ctx "$CONTEXT" '{ additional_context: $ctx }'
"""

# Cursor stop hook with followup_message.
# __FOLLOWUP_MSG__ is replaced with render_cursor_followup() output.
CURSOR_STOP_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Cursor stop hook: conditionally suggest saving to mem-mesh
# stdin: {"last_assistant_message":"...", "transcript":[...]} JSON

set -euo pipefail

INPUT=$(cat)

# Check if there were meaningful tool uses (file edits, code changes)
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
print(json.dumps({'followup_message': '''__FOLLOWUP_MSG__'''}))
"
else
    echo '{}'
fi
"""

# ---------------------------------------------------------------------------
# Local mode hook templates (python direct, no curl)
# ---------------------------------------------------------------------------

LOCAL_TRACK_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# PostToolUse hook: track code changes to mem-mesh (local mode)
# Writes directly to local SQLite via Python

set -euo pipefail
command -v python3 >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE_PATH" ] && exit 0

case "$FILE_PATH" in
  *.py|*.ts|*.js|*.jsx|*.tsx|*.json|*.md|*.yaml|*.yml|*.toml|*.sh) ;;
  *) exit 0 ;;
esac

case "$FILE_PATH" in
  */.cursor/*|*/.claude/*|*/.kiro/*) exit 0 ;;
esac

PROJECT_DIR=$(basename "$(cd "$(dirname "$FILE_PATH")" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null || dirname "$FILE_PATH")")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"

if [ "$TOOL_NAME" = "Write" ]; then
  PREVIEW=$(echo "$INPUT" | jq -r '.tool_input.content // empty' | head -c 300)
  CONTENT="file: ${FILE_PATH}\nchange: new file or overwrite\ncontent: ${PREVIEW}"
elif [ "$TOOL_NAME" = "Edit" ]; then
  OLD=$(echo "$INPUT" | jq -r '.tool_input.old_string // empty' | head -c 150)
  NEW=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty' | head -c 150)
  CONTENT="file: ${FILE_PATH}\nchange: '${OLD}' -> '${NEW}'"
else
  exit 0
fi

[ ${#CONTENT} -lt 15 ] && exit 0

EXT="${FILE_PATH##*.}"

python3 -c "
import sys, asyncio, json
sys.path.insert(0, '$MEM_MESH_PATH')
from app.core.storage.direct import DirectStorageManager
async def save():
    s = DirectStorageManager()
    await s.initialize()
    await s.add_memory(
        content=$(python3 -c "import json; print(json.dumps('''$CONTENT'''))"),
        project_id='$PROJECT_DIR',
        category='code_snippet',
        source='hook-local',
        tags=['auto-save', 'file-change', '$EXT'],
    )
asyncio.run(save())
" 2>/dev/null || true

exit 0
"""

LOCAL_STOP_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Stop hook: save conversation summary to mem-mesh (local mode)

set -euo pipefail
command -v python3 >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 50 ] && exit 0

SUMMARY=$(echo "$MESSAGE" | head -c 500)
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

python3 -c "
import sys, asyncio, json
sys.path.insert(0, '$MEM_MESH_PATH')
from app.core.storage.direct import DirectStorageManager
async def save():
    s = DirectStorageManager()
    await s.initialize()
    await s.add_memory(
        content='[conversation summary] ' + $(python3 -c "import json; print(json.dumps('''$SUMMARY'''))"),
        project_id='$PROJECT_DIR',
        category='git-history',
        source='hook-local',
        tags=['auto-save', 'conversation'],
    )
asyncio.run(save())
" 2>/dev/null || true

exit 0
"""


# ---------------------------------------------------------------------------
# Claude Code hooks settings patch
# ---------------------------------------------------------------------------

CLAUDE_HOOKS_SETTINGS: Dict[str, Any] = {
    "hooks": {
        "PostToolUse": [
            {
                "matcher": "Write|Edit",
                "hooks": [
                    {
                        "type": "command",
                        "command": "~/.claude/hooks/mem-mesh-track.sh",
                        "timeout": 10,
                        "async": True,
                    }
                ],
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "~/.claude/hooks/mem-mesh-stop.sh",
                        "timeout": 10,
                        "async": True,
                    }
                ]
            }
        ],
    }
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_template(
    template: str,
    url: str,
    *,
    source_tag: str = "claude-code-hook",
    ide_tag: str = "claude",
    project_id: str = "mem-mesh",
) -> str:
    """Replace all placeholders in a template string."""
    result = template.replace("__DEFAULT_URL__", url)
    result = result.replace("__VERSION_MARKER__", VERSION_MARKER)
    result = result.replace("__SOURCE_TAG__", source_tag)
    result = result.replace("__IDE_TAG__", ide_tag)
    # Inject renderer-generated text
    result = result.replace("__RULES_TEXT__", render_rules_text(project_id))
    result = result.replace("__FOLLOWUP_MSG__", render_cursor_followup(project_id))
    return result


def _render_local_template(
    template: str,
    mem_mesh_path: str,
) -> str:
    """Replace placeholders for local mode templates."""
    result = template.replace("__MEM_MESH_PATH__", mem_mesh_path)
    result = result.replace("__VERSION_MARKER__", VERSION_MARKER)
    return result


def _write_script(path: Path, content: str) -> None:
    """Write a shell script and make it executable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _merge_json_settings(path: Path, patch: Dict[str, Any]) -> None:
    """Merge patch into an existing JSON file, preserving other keys."""
    existing: Dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    # Deep-merge hooks section only; preserve everything else
    for key, value in patch.items():
        if key == "hooks" and key in existing and isinstance(existing[key], dict):
            existing[key].update(value)
        else:
            existing[key] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _remove_json_key(path: Path, key: str) -> None:
    """Remove a top-level key from a JSON file."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if key in data:
        del data[key]
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def _remove_kiro_mem_mesh_hooks(path: Path) -> None:
    """Remove mem-mesh entries from Kiro hooks.json, preserving others."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    hooks: List[Any] = data.get("hooks", [])
    data["hooks"] = [h for h in hooks if not h.get("name", "").startswith("mem-mesh:")]
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Install / Uninstall commands
# ---------------------------------------------------------------------------

HOME = Path.home()

CLAUDE_HOOKS_DIR = HOME / ".claude" / "hooks"
CLAUDE_SETTINGS = HOME / ".claude" / "settings.json"

KIRO_HOOKS_DIR = HOME / ".kiro" / "hooks"
KIRO_SETTINGS = HOME / ".kiro" / "settings" / "hooks.json"

CURSOR_HOOKS_DIR = HOME / ".cursor" / "hooks"
CURSOR_SETTINGS = HOME / ".cursor" / "hooks.json"

CURSOR_HOOKS_SETTINGS: Dict[str, Any] = {
    "version": 1,
    "hooks": {
        "sessionStart": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": str(CURSOR_HOOKS_DIR / "mem-mesh-session-start.sh"),
                        "timeout": 15,
                    }
                ]
            }
        ],
        "postToolUse": [
            {
                "matcher": "Write|Edit",
                "hooks": [
                    {
                        "type": "command",
                        "command": str(CURSOR_HOOKS_DIR / "mem-mesh-track.sh"),
                        "timeout": 10,
                    }
                ],
            }
        ],
        "stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": str(CURSOR_HOOKS_DIR / "mem-mesh-stop.sh"),
                        "timeout": 10,
                    }
                ]
            }
        ],
    },
}


def _install_claude(url: str, mode: str = "api", path: str = "") -> None:
    """Install mem-mesh hooks for Claude Code."""
    print("[claude] Installing hook scripts...")

    track_script = CLAUDE_HOOKS_DIR / "mem-mesh-track.sh"
    stop_script = CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh"

    if mode == "local":
        _write_script(track_script, _render_local_template(LOCAL_TRACK_HOOK_TEMPLATE, path))
        _write_script(stop_script, _render_local_template(LOCAL_STOP_HOOK_TEMPLATE, path))
    else:
        _write_script(
            track_script,
            _render_template(
                TRACK_HOOK_TEMPLATE, url,
                source_tag="claude-code-hook", ide_tag="claude",
            ),
        )
        _write_script(
            stop_script,
            _render_template(
                STOP_HOOK_TEMPLATE, url,
                source_tag="claude-code-hook", ide_tag="claude",
            ),
        )
    print(f"  -> {track_script}")
    print(f"  -> {stop_script}")

    print("[claude] Updating settings.json...")
    _merge_json_settings(CLAUDE_SETTINGS, CLAUDE_HOOKS_SETTINGS)
    print(f"  -> {CLAUDE_SETTINGS}")

    print("[claude] Done.")


def _install_kiro(url: str, mode: str = "api", path: str = "") -> None:
    """Install mem-mesh hooks for Kiro."""
    print("[kiro] Installing hook script...")

    stop_script = KIRO_HOOKS_DIR / "mem-mesh-stop.sh"
    if mode == "local":
        _write_script(stop_script, _render_local_template(LOCAL_STOP_HOOK_TEMPLATE, path))
    else:
        _write_script(
            stop_script,
            _render_template(
                KIRO_STOP_HOOK_TEMPLATE, url,
                source_tag="kiro-hook", ide_tag="kiro",
            ),
        )
    print(f"  -> {stop_script}")

    print("[kiro] Updating hooks.json...")
    kiro_hook_entry = {
        "name": "mem-mesh: Save Response",
        "trigger": "agentResponse",
        "action": "shell",
        "command": str(stop_script),
        "env": {"KIRO_RESULT": "$response"},
    }

    # Load existing or create new
    existing: Dict[str, Any] = {"hooks": []}
    if KIRO_SETTINGS.exists():
        try:
            existing = json.loads(KIRO_SETTINGS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {"hooks": []}

    hooks: List[Any] = existing.get("hooks", [])

    # Remove existing mem-mesh hooks, then add new
    hooks = [h for h in hooks if not h.get("name", "").startswith("mem-mesh:")]
    hooks.append(kiro_hook_entry)
    existing["hooks"] = hooks

    KIRO_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    KIRO_SETTINGS.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"  -> {KIRO_SETTINGS}")

    print("[kiro] Done.")


def _install_cursor(url: str, mode: str = "api", path: str = "") -> None:
    """Install mem-mesh hooks for Cursor."""
    print("[cursor] Installing hook scripts...")

    session_start_script = CURSOR_HOOKS_DIR / "mem-mesh-session-start.sh"
    track_script = CURSOR_HOOKS_DIR / "mem-mesh-track.sh"
    stop_script = CURSOR_HOOKS_DIR / "mem-mesh-stop.sh"

    if mode == "local":
        _write_script(
            session_start_script,
            _render_local_template(CURSOR_SESSION_START_TEMPLATE, path),
        )
        _write_script(track_script, _render_local_template(LOCAL_TRACK_HOOK_TEMPLATE, path))
        _write_script(stop_script, _render_local_template(LOCAL_STOP_HOOK_TEMPLATE, path))
    else:
        _write_script(
            session_start_script,
            _render_template(
                CURSOR_SESSION_START_TEMPLATE, url,
                source_tag="cursor-hook", ide_tag="cursor",
            ),
        )
        _write_script(
            track_script,
            _render_template(
                TRACK_HOOK_TEMPLATE, url,
                source_tag="cursor-hook", ide_tag="cursor",
            ),
        )
        _write_script(
            stop_script,
            _render_template(
                CURSOR_STOP_TEMPLATE, url,
                source_tag="cursor-hook", ide_tag="cursor",
            ),
        )
    print(f"  -> {session_start_script}")
    print(f"  -> {track_script}")
    print(f"  -> {stop_script}")

    print("[cursor] Updating hooks.json...")
    _merge_json_settings(CURSOR_SETTINGS, CURSOR_HOOKS_SETTINGS)
    print(f"  -> {CURSOR_SETTINGS}")

    print("[cursor] Done.")


def _uninstall_claude() -> None:
    """Remove mem-mesh hooks for Claude Code."""
    print("[claude] Removing hook scripts...")
    for name in ("mem-mesh-track.sh", "mem-mesh-stop.sh"):
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
    ):
        script = CURSOR_HOOKS_DIR / name
        if script.exists():
            script.unlink()
            print(f"  removed {script}")

    print("[cursor] Removing hooks from hooks.json...")
    _remove_json_key(CURSOR_SETTINGS, "hooks")

    print("[cursor] Done.")


# ---------------------------------------------------------------------------
# Status command (with version detection)
# ---------------------------------------------------------------------------


def _check_script(path: Path) -> str:
    """Check if a script exists and is executable."""
    if not path.exists():
        return "not installed"
    if not os.access(path, os.X_OK):
        return "exists but NOT executable"
    return "installed"


def _check_script_version(path: Path) -> str:
    """Check script status including prompt version."""
    base = _check_script(path)
    if base != "installed":
        return base
    content = path.read_text(encoding="utf-8")
    version = extract_prompt_version(content)
    if version == 0:
        return "installed (no version marker)"
    if version < PROMPT_VERSION:
        return f"installed (prompt-version: {version} -> outdated)"
    return f"installed (prompt-version: {version})"


def _extract_url_from_script(path: Path) -> Optional[str]:
    """Extract the default URL from an installed script."""
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    for line in content.splitlines():
        if "MEM_MESH_API_URL:-" in line:
            start = line.find(":-") + 2
            end = line.find("}", start)
            if start > 1 and end > start:
                url = line[start:end].strip('"').strip("'")
                return url
    return None


def _check_kiro_hook_version(path: Path) -> str:
    """Check prompt version in a .kiro.hook JSON file."""
    if not path.exists():
        return "not found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "parse error"
    version_str = data.get("version", "0")
    try:
        version = int(version_str)
    except ValueError:
        return f"installed (version: {version_str})"
    if version < PROMPT_VERSION:
        return f"installed (prompt-version: {version} -> outdated)"
    return f"installed (prompt-version: {version})"


def cmd_status() -> None:
    """Print installation status."""
    print("=== mem-mesh hooks status ===")
    print(f"Prompt version: {PROMPT_VERSION} (current)\n")

    # Claude Code
    print("[Claude Code]")
    track = CLAUDE_HOOKS_DIR / "mem-mesh-track.sh"
    stop = CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh"
    print(f"  track hook:  {_check_script_version(track)}")
    print(f"  stop hook:   {_check_script_version(stop)}")

    url = _extract_url_from_script(track) or _extract_url_from_script(stop)
    if url:
        print(f"  target URL:  {url}")

    if CLAUDE_SETTINGS.exists():
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
            has_hooks = "hooks" in settings
            print(f"  settings.json hooks: {'configured' if has_hooks else 'not configured'}")
        except (json.JSONDecodeError, OSError):
            print("  settings.json: parse error")
    else:
        print("  settings.json: not found")

    print()

    # Kiro
    print("[Kiro]")
    kiro_stop = KIRO_HOOKS_DIR / "mem-mesh-stop.sh"
    print(f"  stop hook:   {_check_script_version(kiro_stop)}")

    url = _extract_url_from_script(kiro_stop)
    if url:
        print(f"  target URL:  {url}")

    if KIRO_SETTINGS.exists():
        try:
            data = json.loads(KIRO_SETTINGS.read_text(encoding="utf-8"))
            mem_hooks = [
                h for h in data.get("hooks", [])
                if h.get("name", "").startswith("mem-mesh:")
            ]
            print(f"  hooks.json:  {len(mem_hooks)} mem-mesh hook(s) registered")
        except (json.JSONDecodeError, OSError):
            print("  hooks.json: parse error")
    else:
        print("  hooks.json: not found")

    print()

    # Cursor
    print("[Cursor]")
    cursor_session = CURSOR_HOOKS_DIR / "mem-mesh-session-start.sh"
    cursor_track = CURSOR_HOOKS_DIR / "mem-mesh-track.sh"
    cursor_stop = CURSOR_HOOKS_DIR / "mem-mesh-stop.sh"
    print(f"  session hook: {_check_script_version(cursor_session)}")
    print(f"  track hook:   {_check_script_version(cursor_track)}")
    print(f"  stop hook:    {_check_script_version(cursor_stop)}")

    url = (
        _extract_url_from_script(cursor_track)
        or _extract_url_from_script(cursor_stop)
    )
    if url:
        print(f"  target URL:   {url}")

    if CURSOR_SETTINGS.exists():
        try:
            settings = json.loads(CURSOR_SETTINGS.read_text(encoding="utf-8"))
            has_hooks = "hooks" in settings
            print(
                f"  hooks.json:   {'configured' if has_hooks else 'not configured'}"
            )
        except (json.JSONDecodeError, OSError):
            print("  hooks.json:   parse error")
    else:
        print("  hooks.json:   not found")

    # Project-local hooks
    project_root = _find_project_root()
    if project_root:
        print()
        print("[Project Local]")

        # Kiro hooks
        kiro_dir = project_root / ".kiro" / "hooks"
        for name in ("auto-save-conversations", "auto-create-pin-on-task", "load-project-context"):
            hook_file = kiro_dir / f"{name}.kiro.hook"
            print(f"  {name}: {_check_kiro_hook_version(hook_file)}")

        # Cursor hooks
        cursor_dir = project_root / ".cursor" / "hooks"
        for name in ("mem-mesh-session-start.sh", "mem-mesh-auto-save.sh"):
            script = cursor_dir / name
            print(f"  {name}: {_check_script_version(script)}")

    print()
    print(f"Run 'mem-mesh-hooks install --target all' to update global hooks.")
    print(f"Run 'mem-mesh-hooks sync-project' to update project-local hooks.")


# ---------------------------------------------------------------------------
# Sync-project command
# ---------------------------------------------------------------------------


def _find_project_root() -> Optional[Path]:
    """Find the mem-mesh project root (where CLAUDE.md exists)."""
    # First try: relative to this file
    candidate = Path(__file__).resolve().parent.parent.parent
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
print(json.dumps({{'additional_context': ctx}}))
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

    print("[cursor] Done.")


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


def cmd_install(
    target: str,
    url: str,
    mode: str = "api",
    path: str = "",
) -> None:
    """Install hooks for the specified target."""
    if mode == "local":
        resolved = path or str(Path(__file__).resolve().parent.parent.parent)
        print(f"Installing mem-mesh hooks (mode: local, path: {resolved})")
        print(f"Prompt version: {PROMPT_VERSION}\n")
    else:
        resolved = ""
        print(f"Installing mem-mesh hooks (mode: api, url: {url})")
        print(f"Prompt version: {PROMPT_VERSION}\n")

    if target in ("claude", "all"):
        _install_claude(url, mode, resolved)
        print()
    if target in ("kiro", "all"):
        _install_kiro(url, mode, resolved)
        print()
    if target in ("cursor", "all"):
        _install_cursor(url, mode, resolved)
        print()
    print("Installation complete. Run 'mem-mesh-hooks status' to verify.")


def cmd_uninstall(target: str) -> None:
    """Uninstall hooks for the specified target."""
    print("Uninstalling mem-mesh hooks\n")
    if target in ("claude", "all"):
        _uninstall_claude()
        print()
    if target in ("kiro", "all"):
        _uninstall_kiro()
        print()
    if target in ("cursor", "all"):
        _uninstall_cursor()
        print()
    print("Uninstallation complete.")


# ---------------------------------------------------------------------------
# Interactive installer
# ---------------------------------------------------------------------------


def _prompt_choice(prompt: str, options: List[str], default: int = 0) -> int:
    """Show numbered options and return the selected index."""
    for i, opt in enumerate(options, 1):
        marker = " (default)" if i - 1 == default else ""
        print(f"  {i}) {opt}{marker}")
    while True:
        raw = input(f"  Select [{default + 1}]: ").strip()
        if not raw:
            return default
        try:
            choice = int(raw)
            if 1 <= choice <= len(options):
                return choice - 1
        except ValueError:
            pass
        print(f"  Please enter 1-{len(options)}")


def cmd_interactive() -> None:
    """Interactive hook installation wizard."""
    print("=" * 44)
    print("  mem-mesh hooks installer (interactive)")
    print("=" * 44)
    print()

    # Step 1: target
    print("[1/3] Select target IDE:")
    targets = ["Claude Code", "Kiro", "Cursor", "All"]
    target_keys = ["claude", "kiro", "cursor", "all"]
    idx = _prompt_choice("", targets, default=3)
    target = target_keys[idx]
    print()

    # Step 2: storage mode
    print("[2/3] Select storage mode:")
    modes = [
        f"API  — Send to remote server ({DEFAULT_URL})",
        "Local — Save directly to local SQLite",
    ]
    mode_idx = _prompt_choice("", modes, default=0)
    mode = "api" if mode_idx == 0 else "local"
    print()

    # Step 3: mode-specific config
    url = DEFAULT_URL
    mem_path = ""
    if mode == "api":
        print(f"[3/3] API URL [{DEFAULT_URL}]:")
        raw = input("  > ").strip()
        if raw:
            url = raw
    else:
        default_path = str(Path(__file__).resolve().parent.parent.parent)
        print(f"[3/3] mem-mesh project path [{default_path}]:")
        raw = input("  > ").strip()
        mem_path = raw if raw else default_path
    print()

    cmd_install(target, url, mode, mem_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point for mem-mesh-hooks."""
    parser = argparse.ArgumentParser(
        prog="mem-mesh-hooks",
        description="Install/uninstall mem-mesh auto-tracking hooks for Claude Code, Kiro, and Cursor.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    target_choices = ["claude", "kiro", "cursor", "all"]

    # install
    install_parser = subparsers.add_parser("install", help="Install hooks")
    install_parser.add_argument(
        "--target",
        choices=target_choices,
        default="all",
        help="Target tool (default: all)",
    )
    install_parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"mem-mesh API URL (default: {DEFAULT_URL})",
    )
    install_parser.add_argument(
        "--mode",
        choices=["api", "local"],
        default="api",
        help="Storage mode: api (remote server) or local (SQLite direct)",
    )
    install_parser.add_argument(
        "--path",
        default="",
        help="mem-mesh project path (required for local mode)",
    )
    install_parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Run interactive installer wizard",
    )

    # uninstall
    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall hooks")
    uninstall_parser.add_argument(
        "--target",
        choices=target_choices,
        default="all",
        help="Target tool (default: all)",
    )

    # status
    subparsers.add_parser("status", help="Show installation status")

    # sync-project
    sync_parser = subparsers.add_parser(
        "sync-project",
        help="Regenerate project-local hooks from shared prompts",
    )
    sync_parser.add_argument(
        "--target",
        choices=["kiro", "cursor", "all"],
        default="all",
        help="Target to sync (default: all)",
    )
    sync_parser.add_argument(
        "--project-id",
        default="mem-mesh",
        help="Project ID for hook prompts (default: mem-mesh)",
    )

    args = parser.parse_args(argv)

    # No subcommand or install -i → interactive mode
    if args.command is None or (
        args.command == "install" and getattr(args, "interactive", False)
    ):
        cmd_interactive()
        return

    if args.command == "install":
        cmd_install(args.target, args.url, args.mode, args.path)
    elif args.command == "uninstall":
        cmd_uninstall(args.target)
    elif args.command == "status":
        cmd_status()
    elif args.command == "sync-project":
        cmd_sync_project(args.target, args.project_id)


if __name__ == "__main__":
    main()
