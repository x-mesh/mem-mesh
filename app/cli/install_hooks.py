#!/usr/bin/env python3
"""mem-mesh-hooks: Install/uninstall mem-mesh hooks for Claude Code and Kiro."""

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_URL = "https://meme.24x365.online"

# ---------------------------------------------------------------------------
# Hook script templates
# ---------------------------------------------------------------------------

TRACK_HOOK_TEMPLATE = r"""#!/bin/bash
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

# Exclude .claude/ internal files
case "$FILE_PATH" in
  */.claude/*) exit 0 ;;
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
  --arg source "claude-code-hook" \
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
  --arg source "claude-code-hook" \
  '{
    content: $content,
    project_id: $project_id,
    category: "git-history",
    source: $source,
    tags: ["auto-save", "conversation"]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
"""

KIRO_STOP_HOOK_TEMPLATE = r"""#!/bin/bash
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

# ---------------------------------------------------------------------------
# Claude Code hooks settings patch
# ---------------------------------------------------------------------------

CLAUDE_HOOKS_SETTINGS: Dict = {
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


def _render_template(template: str, url: str) -> str:
    """Replace __DEFAULT_URL__ placeholder with the actual URL."""
    return template.replace("__DEFAULT_URL__", url)


def _write_script(path: Path, content: str) -> None:
    """Write a shell script and make it executable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _merge_json_settings(path: Path, patch: Dict) -> None:
    """Merge patch into an existing JSON file, preserving other keys."""
    existing: Dict = {}
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
    hooks: List = data.get("hooks", [])
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


def _install_claude(url: str) -> None:
    """Install mem-mesh hooks for Claude Code."""
    print("[claude] Installing hook scripts...")

    track_script = CLAUDE_HOOKS_DIR / "mem-mesh-track.sh"
    stop_script = CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh"

    _write_script(track_script, _render_template(TRACK_HOOK_TEMPLATE, url))
    _write_script(stop_script, _render_template(STOP_HOOK_TEMPLATE, url))
    print(f"  -> {track_script}")
    print(f"  -> {stop_script}")

    print("[claude] Updating settings.json...")
    _merge_json_settings(CLAUDE_SETTINGS, CLAUDE_HOOKS_SETTINGS)
    print(f"  -> {CLAUDE_SETTINGS}")

    print("[claude] Done.")


def _install_kiro(url: str) -> None:
    """Install mem-mesh hooks for Kiro."""
    print("[kiro] Installing hook script...")

    stop_script = KIRO_HOOKS_DIR / "mem-mesh-stop.sh"
    _write_script(stop_script, _render_template(KIRO_STOP_HOOK_TEMPLATE, url))
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
    existing: Dict = {"hooks": []}
    if KIRO_SETTINGS.exists():
        try:
            existing = json.loads(KIRO_SETTINGS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {"hooks": []}

    hooks: List = existing.get("hooks", [])

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


# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------


def _check_script(path: Path) -> str:
    """Check if a script exists and is executable."""
    if not path.exists():
        return "not installed"
    if not os.access(path, os.X_OK):
        return "exists but NOT executable"
    return "installed"


def _extract_url_from_script(path: Path) -> Optional[str]:
    """Extract the default URL from an installed script."""
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    for line in content.splitlines():
        if "MEM_MESH_API_URL:-" in line:
            # Extract URL from: API_URL="${MEM_MESH_API_URL:-https://...}"
            start = line.find(":-") + 2
            end = line.find("}", start)
            if start > 1 and end > start:
                url = line[start:end].strip('"').strip("'")
                return url
    return None


def cmd_status() -> None:
    """Print installation status."""
    print("=== mem-mesh hooks status ===\n")

    # Claude Code
    print("[Claude Code]")
    track = CLAUDE_HOOKS_DIR / "mem-mesh-track.sh"
    stop = CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh"
    print(f"  track hook:  {_check_script(track)}")
    print(f"  stop hook:   {_check_script(stop)}")

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
    print(f"  stop hook:   {_check_script(kiro_stop)}")

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


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


def cmd_install(target: str, url: str) -> None:
    """Install hooks for the specified target."""
    print(f"Installing mem-mesh hooks (url: {url})\n")
    if target in ("claude", "all"):
        _install_claude(url)
        print()
    if target in ("kiro", "all"):
        _install_kiro(url)
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
    print("Uninstallation complete.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point for mem-mesh-hooks."""
    parser = argparse.ArgumentParser(
        prog="mem-mesh-hooks",
        description="Install/uninstall mem-mesh auto-tracking hooks for Claude Code and Kiro.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # install
    install_parser = subparsers.add_parser("install", help="Install hooks")
    install_parser.add_argument(
        "--target",
        choices=["claude", "kiro", "all"],
        default="all",
        help="Target tool (default: all)",
    )
    install_parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"mem-mesh API URL (default: {DEFAULT_URL})",
    )

    # uninstall
    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall hooks")
    uninstall_parser.add_argument(
        "--target",
        choices=["claude", "kiro", "all"],
        default="all",
        help="Target tool (default: all)",
    )

    # status
    subparsers.add_parser("status", help="Show installation status")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "install":
        cmd_install(args.target, args.url)
    elif args.command == "uninstall":
        cmd_uninstall(args.target)
    elif args.command == "status":
        cmd_status()


if __name__ == "__main__":
    main()
