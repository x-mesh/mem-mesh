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
import re
import stat
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.cli.prompts.behaviors import PROMPT_VERSION, REFLECT_CONFIG
from app.cli.prompts.renderers import (
    VERSION_MARKER,
    extract_prompt_version,
    render_cursor_followup,
    render_enhanced_stop_prompt,
    render_kiro_auto_create_pin,
    render_kiro_auto_save,
    render_kiro_load_context,
    render_reflect_prompt,
    render_rules_text,
)
from app.cli.hooks.templates import (
    CURSOR_SESSION_START_TEMPLATE,
    CURSOR_STOP_TEMPLATE,
    ENHANCED_STOP_HOOK_TEMPLATE,
    KIRO_STOP_HOOK_TEMPLATE,
    LOCAL_ENHANCED_STOP_HOOK_TEMPLATE,
    LOCAL_PRECOMPACT_HOOK_TEMPLATE,
    LOCAL_REFLECT_HOOK_TEMPLATE,
    LOCAL_SESSION_END_HOOK_TEMPLATE,
    LOCAL_SESSION_START_HOOK_TEMPLATE,
    LOCAL_STOP_HOOK_TEMPLATE,
    LOCAL_SUBAGENT_START_HOOK_TEMPLATE,
    LOCAL_SUBAGENT_STOP_HOOK_TEMPLATE,
    LOCAL_TASK_COMPLETED_HOOK_TEMPLATE,
    LOCAL_USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
    PRECOMPACT_HOOK_TEMPLATE,
    REFLECT_HOOK_TEMPLATE,
    SESSION_END_HOOK_TEMPLATE,
    SESSION_START_HOOK_TEMPLATE,
    STOP_DECIDE_HOOK_TEMPLATE,
    STOP_HOOK_TEMPLATE,
    SUBAGENT_START_HOOK_TEMPLATE,
    SUBAGENT_STOP_HOOK_TEMPLATE,
    TASK_COMPLETED_HOOK_TEMPLATE,
    USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
)
from app.cli.hooks.keywords import KEYWORD_MATCHER_BLOCK
from app.cli.hooks.cursor_adapters import (
    adapt_cursor_before_submit_prompt,
    adapt_cursor_precompact,
    adapt_cursor_subagent_start,
    adapt_cursor_subagent_stop,
)

DEFAULT_URL = "http://localhost:8000"


# Hook profiles
# ---------------------------------------------------------------------------

HOOK_PROFILES = {
    "standard": {
        "description": "Keyword matching + structured save (no LLM, no API key, 요약+원본)",
        "hooks": [
            "session-start",
            "stop-decide",
            "user-prompt-submit",
            "subagent-start",
            "subagent-stop",
            "task-completed",
            "session-end",
            "precompact",
        ],
    },
    "enhanced": {
        "description": "Haiku API decision + structured analysis (requires ANTHROPIC_API_KEY)",
        "hooks": [
            "session-start",
            "stop-enhanced",
            "user-prompt-submit",
            "subagent-start",
            "subagent-stop",
            "task-completed",
            "session-end",
            "precompact",
        ],
    },
    "minimal": {
        "description": "Simple truncated save (async, no LLM, no decision making)",
        "hooks": ["session-start", "stop", "session-end", "precompact"],
    },
}


# ---------------------------------------------------------------------------
# Claude Code hooks settings patch
# ---------------------------------------------------------------------------


def _build_claude_hooks_settings(profile: str = "standard") -> Dict[str, Any]:
    """Build Claude Code hooks settings dynamically based on profile.

    Profiles:
      - minimal: command-based stop hook (no LLM cost, simple truncation)
      - standard: native prompt-based stop hook (hybrid summarization via Haiku)
      - enhanced: prompt stop + async reflect command (structured analysis)
    """
    settings: Dict[str, Any] = {"hooks": {}}

    # SessionStart: inject session context (all profiles)
    settings["hooks"]["SessionStart"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "~/.claude/hooks/mem-mesh-session-start.sh",
                    "timeout": 15,
                }
            ]
        }
    ]

    stop_entries: List[Dict[str, Any]] = []

    if profile == "standard":
        # Keyword matching command hook (no LLM, no API key)
        stop_entries.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "~/.claude/hooks/mem-mesh-stop-decide.sh",
                        "timeout": 10,
                        "async": True,
                    }
                ]
            }
        )
    elif profile == "enhanced":
        # Async command hook: Haiku API decides save/skip, saves directly
        stop_entries.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "~/.claude/hooks/mem-mesh-stop-enhanced.sh",
                        "timeout": 20,
                        "async": True,
                    }
                ]
            }
        )
    else:
        # minimal: old-style command hook (truncate + save via API/local)
        stop_entries.append(
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
        )

    settings["hooks"]["Stop"] = stop_entries

    # UserPromptSubmit: keyword-filtered context search (standard/enhanced only)
    if profile != "minimal":
        settings["hooks"]["UserPromptSubmit"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "~/.claude/hooks/mem-mesh-user-prompt-submit.sh",
                        "timeout": 5,
                    }
                ]
            }
        ]

    # SubagentStart: inject project context (standard/enhanced only)
    if profile != "minimal":
        settings["hooks"]["SubagentStart"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "~/.claude/hooks/mem-mesh-subagent-start.sh",
                        "timeout": 5,
                    }
                ]
            }
        ]

    # SubagentStop: auto-save important results (standard/enhanced only)
    if profile != "minimal":
        settings["hooks"]["SubagentStop"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "~/.claude/hooks/mem-mesh-subagent-stop.sh",
                        "timeout": 10,
                        "async": True,
                    }
                ]
            }
        ]

    # TaskCompleted: auto-save completed tasks (standard/enhanced only)
    if profile != "minimal":
        settings["hooks"]["TaskCompleted"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "~/.claude/hooks/mem-mesh-task-completed.sh",
                        "timeout": 10,
                        "async": True,
                    }
                ]
            }
        ]

    # SessionEnd: auto-end session on exit (all profiles)
    settings["hooks"]["SessionEnd"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "~/.claude/hooks/mem-mesh-session-end.sh",
                    "timeout": 10,
                }
            ]
        }
    ]

    # PreCompact: auto-end session before context compaction (all profiles)
    settings["hooks"]["PreCompact"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "~/.claude/hooks/mem-mesh-precompact.sh",
                    "timeout": 10,
                }
            ]
        }
    ]

    return settings


CLAUDE_HOOKS_SETTINGS: Dict[str, Any] = _build_claude_hooks_settings("standard")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_template(
    template: str,
    url: str,
    *,
    source_tag: str = "claude-code-hook",
    ide_tag: str = "claude",
    client_tag: str = "claude_code",
    project_id: str = "mem-mesh",
) -> str:
    """Replace all placeholders in a template string."""
    result = template.replace("__DEFAULT_URL__", url)
    result = result.replace("__VERSION_MARKER__", VERSION_MARKER)
    result = result.replace("__SOURCE_TAG__", source_tag)
    result = result.replace("__IDE_TAG__", ide_tag)
    result = result.replace("__CLIENT_TAG__", client_tag)
    # Inject renderer-generated text
    result = result.replace("__RULES_TEXT__", render_rules_text(project_id))
    result = result.replace("__FOLLOWUP_MSG__", render_cursor_followup(project_id))
    # Reflect hook placeholders
    result = result.replace("__REFLECT_PROMPT__", render_reflect_prompt())
    result = result.replace("__REFLECT_MODEL__", REFLECT_CONFIG.model)
    result = result.replace("__REFLECT_MAX_TOKENS__", str(REFLECT_CONFIG.max_tokens))
    result = result.replace("__REFLECT_TIMEOUT__", str(REFLECT_CONFIG.timeout_seconds))
    # Enhanced stop hook prompt
    result = result.replace("__ENHANCED_PROMPT__", render_enhanced_stop_prompt())
    # Keyword matcher block (single source of truth)
    result = result.replace("__KEYWORD_MATCHER__", KEYWORD_MATCHER_BLOCK)
    return result


def _render_local_template(
    template: str,
    mem_mesh_path: str,
    *,
    project_id: str = "mem-mesh",
) -> str:
    """Replace placeholders for local mode templates."""
    result = template.replace("__MEM_MESH_PATH__", mem_mesh_path)
    result = result.replace("__VERSION_MARKER__", VERSION_MARKER)
    result = result.replace("__RULES_TEXT__", render_rules_text(project_id))
    result = result.replace("__FOLLOWUP_MSG__", render_cursor_followup(project_id))
    # Reflect hook placeholders
    result = result.replace("__REFLECT_PROMPT__", render_reflect_prompt())
    result = result.replace("__REFLECT_MODEL__", REFLECT_CONFIG.model)
    result = result.replace("__REFLECT_MAX_TOKENS__", str(REFLECT_CONFIG.max_tokens))
    result = result.replace("__REFLECT_TIMEOUT__", str(REFLECT_CONFIG.timeout_seconds))
    # Enhanced stop hook prompt
    result = result.replace("__ENHANCED_PROMPT__", render_enhanced_stop_prompt())
    # Keyword matcher block (single source of truth)
    result = result.replace("__KEYWORD_MATCHER__", KEYWORD_MATCHER_BLOCK)
    return result


def _write_script(path: Path, content: str) -> None:
    """Write a shell script and make it executable."""
    unresolved = re.findall(r"__[A-Z0-9_]+__", content)
    if unresolved:
        tokens = ", ".join(sorted(set(unresolved)))
        raise ValueError(f"Unresolved template tokens in {path}: {tokens}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _is_mem_mesh_hook(hook: Dict[str, Any]) -> bool:
    """Return True if a hook definition belongs to mem-mesh."""
    hook_type = str(hook.get("type", ""))
    command = str(hook.get("command", ""))
    prompt = str(hook.get("prompt", ""))
    if "mem-mesh-" in command:
        return True
    if hook_type == "prompt" and "mcp__mem-mesh__add" in prompt:
        return True
    return False


def _is_mem_mesh_entry(entry: Dict[str, Any]) -> bool:
    """Return True if a hook entry contains mem-mesh managed hooks."""
    if _is_mem_mesh_hook(entry):
        return True
    hooks = entry.get("hooks", [])
    if not isinstance(hooks, list):
        return False
    return any(isinstance(hook, dict) and _is_mem_mesh_hook(hook) for hook in hooks)


def _merge_hook_entries(
    existing_entries: List[Dict[str, Any]],
    patch_entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge event entries while preserving non mem-mesh user hooks."""
    preserved = [
        entry
        for entry in existing_entries
        if isinstance(entry, dict) and not _is_mem_mesh_entry(entry)
    ]
    passthrough = [
        entry
        for entry in patch_entries
        if isinstance(entry, dict) and not _is_mem_mesh_entry(entry)
    ]
    managed = [
        entry
        for entry in patch_entries
        if isinstance(entry, dict) and _is_mem_mesh_entry(entry)
    ]
    return preserved + passthrough + managed


def _merge_json_settings(path: Path, patch: Dict[str, Any]) -> None:
    """Merge patch into an existing JSON file, preserving other keys."""
    existing: Dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    # Deep-merge hooks section only; preserve everything else.
    # For each hook event, keep existing non mem-mesh entries and upsert only
    # mem-mesh-managed entries from patch.
    for key, value in patch.items():
        if key == "hooks" and key in existing and isinstance(existing[key], dict):
            existing_hooks = existing[key]
            patch_hooks = value if isinstance(value, dict) else {}
            merged_hooks = dict(existing_hooks)
            for event_name, patch_entries in patch_hooks.items():
                current_entries = existing_hooks.get(event_name, [])
                if isinstance(current_entries, list) and isinstance(patch_entries, list):
                    merged_hooks[event_name] = _merge_hook_entries(
                        current_entries, patch_entries
                    )
                else:
                    merged_hooks[event_name] = patch_entries
            existing[key] = merged_hooks
        else:
            existing[key] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
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


def _remove_hook_event(path: Path, event_name: str) -> None:
    """Remove a specific hook event from the hooks section of a JSON file."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    hooks = data.get("hooks", {})
    if event_name in hooks:
        del hooks[event_name]
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _remove_mem_mesh_hooks_from_json(path: Path) -> None:
    """Remove mem-mesh hook entries from hooks.json, preserving user entries."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return

    changed = False
    for event_name, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        filtered = [
            entry
            for entry in entries
            if not (isinstance(entry, dict) and _is_mem_mesh_entry(entry))
        ]
        if len(filtered) != len(entries):
            hooks[event_name] = filtered
            changed = True
        if not hooks[event_name]:
            del hooks[event_name]
            changed = True

    if changed:
        if not hooks:
            data.pop("hooks", None)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _count_mem_mesh_hook_entries(path: Path) -> int:
    """Count mem-mesh hook entries in hooks.json."""
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return 0

    count = 0
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and _is_mem_mesh_entry(entry):
                count += 1
    return count


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

def _build_cursor_hooks_settings(
    hooks_dir: Path,
    scope: str = "global",
) -> Dict[str, Any]:
    """Build Cursor hooks settings from a single spec builder."""
    settings: Dict[str, Any] = {
        "version": 1,
        "hooks": {
            "sessionStart": [
                {
                    "type": "command",
                    "command": str(hooks_dir / "mem-mesh-session-start.sh"),
                    "timeout": 15,
                }
            ],
            "beforeSubmitPrompt": [
                {
                    "type": "command",
                    "command": str(hooks_dir / "mem-mesh-before-submit-prompt.sh"),
                    "timeout": 5,
                }
            ],
            "preCompact": [
                {
                    "type": "command",
                    "command": str(hooks_dir / "mem-mesh-precompact.sh"),
                    "timeout": 10,
                }
            ],
            "subagentStart": [
                {
                    "type": "command",
                    "command": str(hooks_dir / "mem-mesh-subagent-start.sh"),
                    "timeout": 5,
                }
            ],
            "subagentStop": [
                {
                    "type": "command",
                    "command": str(hooks_dir / "mem-mesh-subagent-stop.sh"),
                    "timeout": 10,
                }
            ],
            "sessionEnd": [
                {
                    "type": "command",
                    "command": str(hooks_dir / "mem-mesh-session-end.sh"),
                    "timeout": 10,
                }
            ],
        },
    }

    if scope == "project":
        settings["hooks"]["stop"] = [
            {
                "type": "command",
                "command": str(hooks_dir / "mem-mesh-auto-save.sh"),
                "timeout": 10,
            }
        ]
        return settings

    settings["hooks"]["stop"] = [
        {
            "type": "command",
            "command": str(hooks_dir / "mem-mesh-stop.sh"),
            "timeout": 10,
        }
    ]
    return settings


def _install_claude(
    url: str, mode: str = "api", path: str = "", profile: str = "standard"
) -> None:
    """Install mem-mesh hooks for Claude Code."""
    profile_info = HOOK_PROFILES[profile]
    print(f"[claude] Installing hook scripts (profile: {profile})...")

    session_start_script = CLAUDE_HOOKS_DIR / "mem-mesh-session-start.sh"
    track_script = CLAUDE_HOOKS_DIR / "mem-mesh-track.sh"
    stop_script = CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh"
    enhanced_stop_script = CLAUDE_HOOKS_DIR / "mem-mesh-stop-enhanced.sh"
    reflect_script = CLAUDE_HOOKS_DIR / "mem-mesh-reflect.sh"

    # SessionStart hook (all profiles)
    if mode == "local":
        _write_script(
            session_start_script,
            _render_local_template(LOCAL_SESSION_START_HOOK_TEMPLATE, path),
        )
    else:
        _write_script(
            session_start_script,
            _render_template(
                SESSION_START_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
            ),
        )
    print(f"  -> {session_start_script}")

    # Remove legacy track script if present
    if track_script.exists():
        track_script.unlink()
        print(f"  removed {track_script} (track hook deprecated)")

    decide_script = CLAUDE_HOOKS_DIR / "mem-mesh-stop-decide.sh"

    # Stop hook
    if "stop-decide" in profile_info["hooks"]:
        # Keyword matching command hook (no LLM, no API key)
        _write_script(
            decide_script,
            _render_template(
                STOP_DECIDE_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
            ),
        )
        print(f"  -> {decide_script}")
    elif "stop-enhanced" in profile_info["hooks"]:
        # Enhanced: async command hook with Haiku API
        if mode == "local":
            _write_script(
                enhanced_stop_script,
                _render_local_template(LOCAL_ENHANCED_STOP_HOOK_TEMPLATE, path),
            )
        else:
            _write_script(
                enhanced_stop_script,
                _render_template(
                    ENHANCED_STOP_HOOK_TEMPLATE,
                    url,
                    source_tag="claude-code-hook",
                    ide_tag="claude",
                ),
            )
        print(f"  -> {enhanced_stop_script}")
    elif "stop" in profile_info["hooks"]:
        # Command-based stop: write shell script (minimal profile)
        if mode == "local":
            _write_script(
                stop_script, _render_local_template(LOCAL_STOP_HOOK_TEMPLATE, path)
            )
        else:
            _write_script(
                stop_script,
                _render_template(
                    STOP_HOOK_TEMPLATE,
                    url,
                    source_tag="claude-code-hook",
                    ide_tag="claude",
                ),
            )
        print(f"  -> {stop_script}")

    # UserPromptSubmit hook (standard/enhanced only)
    if "user-prompt-submit" in profile_info["hooks"]:
        ups_script = CLAUDE_HOOKS_DIR / "mem-mesh-user-prompt-submit.sh"
        if mode == "local":
            _write_script(
                ups_script,
                _render_local_template(LOCAL_USER_PROMPT_SUBMIT_HOOK_TEMPLATE, path),
            )
        else:
            _write_script(
                ups_script,
                _render_template(
                    USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
                    url,
                    source_tag="claude-code-hook",
                    ide_tag="claude",
                ),
            )
        print(f"  -> {ups_script}")

    # SubagentStart hook (standard/enhanced only)
    if "subagent-start" in profile_info["hooks"]:
        sa_start_script = CLAUDE_HOOKS_DIR / "mem-mesh-subagent-start.sh"
        if mode == "local":
            _write_script(
                sa_start_script,
                _render_local_template(LOCAL_SUBAGENT_START_HOOK_TEMPLATE, path),
            )
        else:
            _write_script(
                sa_start_script,
                _render_template(
                    SUBAGENT_START_HOOK_TEMPLATE,
                    url,
                    source_tag="claude-code-hook",
                    ide_tag="claude",
                ),
            )
        print(f"  -> {sa_start_script}")

    # SubagentStop hook (standard/enhanced only)
    if "subagent-stop" in profile_info["hooks"]:
        sa_stop_script = CLAUDE_HOOKS_DIR / "mem-mesh-subagent-stop.sh"
        if mode == "local":
            _write_script(
                sa_stop_script,
                _render_local_template(LOCAL_SUBAGENT_STOP_HOOK_TEMPLATE, path),
            )
        else:
            _write_script(
                sa_stop_script,
                _render_template(
                    SUBAGENT_STOP_HOOK_TEMPLATE,
                    url,
                    source_tag="claude-code-hook",
                    ide_tag="claude",
                ),
            )
        print(f"  -> {sa_stop_script}")

    # TaskCompleted hook (standard/enhanced only)
    if "task-completed" in profile_info["hooks"]:
        tc_script = CLAUDE_HOOKS_DIR / "mem-mesh-task-completed.sh"
        if mode == "local":
            _write_script(
                tc_script,
                _render_local_template(LOCAL_TASK_COMPLETED_HOOK_TEMPLATE, path),
            )
        else:
            _write_script(
                tc_script,
                _render_template(
                    TASK_COMPLETED_HOOK_TEMPLATE,
                    url,
                    source_tag="claude-code-hook",
                    ide_tag="claude",
                ),
            )
        print(f"  -> {tc_script}")

    # SessionEnd hook (all profiles)
    session_end_script = CLAUDE_HOOKS_DIR / "mem-mesh-session-end.sh"
    if mode == "local":
        _write_script(
            session_end_script,
            _render_local_template(LOCAL_SESSION_END_HOOK_TEMPLATE, path),
        )
    else:
        _write_script(
            session_end_script,
            _render_template(
                SESSION_END_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
            ),
        )
    print(f"  -> {session_end_script}")

    # PreCompact hook (all profiles)
    precompact_script = CLAUDE_HOOKS_DIR / "mem-mesh-precompact.sh"
    if mode == "local":
        _write_script(
            precompact_script,
            _render_local_template(LOCAL_PRECOMPACT_HOOK_TEMPLATE, path),
        )
    else:
        _write_script(
            precompact_script,
            _render_template(
                PRECOMPACT_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
            ),
        )
    print(f"  -> {precompact_script}")

    # Clean up legacy scripts not belonging to current profile
    legacy_cleanup = {
        "standard": [stop_script, enhanced_stop_script, reflect_script],
        "enhanced": [stop_script, decide_script, reflect_script],
        "minimal": [enhanced_stop_script, decide_script, reflect_script],
    }
    for script in legacy_cleanup.get(profile, []):
        if script.exists():
            script.unlink()
            print(f"  removed {script} (not in {profile} profile)")

    print("[claude] Updating settings.json...")
    hooks_settings = _build_claude_hooks_settings(profile)
    _merge_json_settings(CLAUDE_SETTINGS, hooks_settings)
    # Remove legacy PostToolUse (track hook) from settings
    _remove_hook_event(CLAUDE_SETTINGS, "PostToolUse")
    print(f"  -> {CLAUDE_SETTINGS}")

    if profile == "enhanced":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            print("  ANTHROPIC_API_KEY: set")
        else:
            print(
                "  WARNING: ANTHROPIC_API_KEY not set — reflect hook will be inactive"
            )
            print("  Set it in your shell profile: export ANTHROPIC_API_KEY=sk-...")

    print("[claude] Done.")


def _install_kiro(url: str, mode: str = "api", path: str = "") -> None:
    """Install mem-mesh hooks for Kiro."""
    print("[kiro] Installing hook script...")

    stop_script = KIRO_HOOKS_DIR / "mem-mesh-stop.sh"
    if mode == "local":
        _write_script(
            stop_script, _render_local_template(LOCAL_STOP_HOOK_TEMPLATE, path)
        )
    else:
        _write_script(
            stop_script,
            _render_template(
                KIRO_STOP_HOOK_TEMPLATE,
                url,
                source_tag="kiro-hook",
                ide_tag="kiro",
                client_tag="kiro",
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


def _install_cursor(
    url: str, mode: str = "api", path: str = "", profile: str = "standard"
) -> None:
    """Install mem-mesh hooks for Cursor."""
    print(f"[cursor] Installing hook scripts (profile: {profile})...")

    session_start_script = CURSOR_HOOKS_DIR / "mem-mesh-session-start.sh"
    track_script = CURSOR_HOOKS_DIR / "mem-mesh-track.sh"
    stop_script = CURSOR_HOOKS_DIR / "mem-mesh-stop.sh"
    before_submit_prompt_script = CURSOR_HOOKS_DIR / "mem-mesh-before-submit-prompt.sh"
    precompact_script = CURSOR_HOOKS_DIR / "mem-mesh-precompact.sh"
    subagent_start_script = CURSOR_HOOKS_DIR / "mem-mesh-subagent-start.sh"
    subagent_stop_script = CURSOR_HOOKS_DIR / "mem-mesh-subagent-stop.sh"
    session_end_script = CURSOR_HOOKS_DIR / "mem-mesh-session-end.sh"

    if mode == "local":
        _write_script(
            session_start_script,
            _render_local_template(LOCAL_SESSION_START_HOOK_TEMPLATE, path),
        )
        _write_script(
            stop_script, _render_local_template(LOCAL_STOP_HOOK_TEMPLATE, path)
        )
        _write_script(
            session_end_script,
            _render_local_template(LOCAL_SESSION_END_HOOK_TEMPLATE, path),
        )
        _write_script(
            before_submit_prompt_script,
            adapt_cursor_before_submit_prompt(
                _render_local_template(LOCAL_USER_PROMPT_SUBMIT_HOOK_TEMPLATE, path)
            ),
        )
        _write_script(
            precompact_script,
            adapt_cursor_precompact(
                _render_local_template(LOCAL_PRECOMPACT_HOOK_TEMPLATE, path)
            ),
        )
        _write_script(
            subagent_start_script,
            adapt_cursor_subagent_start(
                _render_local_template(LOCAL_SUBAGENT_START_HOOK_TEMPLATE, path)
            ),
        )
        _write_script(
            subagent_stop_script,
            adapt_cursor_subagent_stop(
                _render_local_template(LOCAL_SUBAGENT_STOP_HOOK_TEMPLATE, path)
            ),
        )
    else:
        _write_script(
            session_start_script,
            _render_template(
                CURSOR_SESSION_START_TEMPLATE,
                url,
                source_tag="cursor-hook",
                ide_tag="cursor",
                client_tag="cursor",
            ),
        )
        _write_script(
            stop_script,
            _render_template(
                CURSOR_STOP_TEMPLATE,
                url,
                source_tag="cursor-hook",
                ide_tag="cursor",
                client_tag="cursor",
            ),
        )
        _write_script(
            session_end_script,
            _render_template(
                SESSION_END_HOOK_TEMPLATE,
                url,
                source_tag="cursor-hook",
                ide_tag="cursor",
                client_tag="cursor",
            ),
        )
        _write_script(
            before_submit_prompt_script,
            adapt_cursor_before_submit_prompt(
                _render_template(
                    USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
                    url,
                    source_tag="cursor-hook",
                    ide_tag="cursor",
                    client_tag="cursor",
                )
            ),
        )
        _write_script(
            precompact_script,
            adapt_cursor_precompact(
                _render_template(
                    PRECOMPACT_HOOK_TEMPLATE,
                    url,
                    source_tag="cursor-hook",
                    ide_tag="cursor",
                    client_tag="cursor",
                )
            ),
        )
        _write_script(
            subagent_start_script,
            adapt_cursor_subagent_start(
                _render_template(
                    SUBAGENT_START_HOOK_TEMPLATE,
                    url,
                    source_tag="cursor-hook",
                    ide_tag="cursor",
                    client_tag="cursor",
                )
            ),
        )
        _write_script(
            subagent_stop_script,
            adapt_cursor_subagent_stop(
                _render_template(
                    SUBAGENT_STOP_HOOK_TEMPLATE,
                    url,
                    source_tag="cursor-hook",
                    ide_tag="cursor",
                    client_tag="cursor",
                )
            ),
        )
    print(f"  -> {session_start_script}")
    print(f"  -> {stop_script}")
    print(f"  -> {session_end_script}")
    print(f"  -> {before_submit_prompt_script}")
    print(f"  -> {precompact_script}")
    print(f"  -> {subagent_start_script}")
    print(f"  -> {subagent_stop_script}")

    # Remove legacy track script if present
    if track_script.exists():
        track_script.unlink()
        print(f"  removed {track_script} (track hook deprecated)")

    print("[cursor] Updating hooks.json...")
    _merge_json_settings(
        CURSOR_SETTINGS, _build_cursor_hooks_settings(CURSOR_HOOKS_DIR, scope="global")
    )
    # Remove legacy postToolUse (track hook) from hooks.json
    _remove_hook_event(CURSOR_SETTINGS, "postToolUse")
    print(f"  -> {CURSOR_SETTINGS}")

    print("[cursor] Done.")


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
        "mem-mesh-before-submit-prompt.sh",
        "mem-mesh-precompact.sh",
        "mem-mesh-subagent-start.sh",
        "mem-mesh-subagent-stop.sh",
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


def _has_prompt_stop_hook(settings_path: Path) -> bool:
    """Check if settings.json has a prompt-based Stop hook configured."""
    if not settings_path.exists():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        stop_entries = data.get("hooks", {}).get("Stop", [])
        for entry in stop_entries:
            for hook in entry.get("hooks", []):
                if hook.get("type") == "prompt":
                    return True
    except (json.JSONDecodeError, OSError, TypeError):
        pass
    return False


def _detect_profile(hooks_dir: Path, settings_path: Optional[Path] = None) -> str:
    """Detect installed profile based on hook scripts and settings.

    Detection priority:
    1. mem-mesh-stop-enhanced.sh → "enhanced"
    2. mem-mesh-stop-decide.sh → "standard"
    3. settings.json has prompt stop hook → "standard (prompt)"
    4. mem-mesh-stop.sh → "minimal"
    5. mem-mesh-reflect.sh → "legacy"
    """
    has_session_start = (hooks_dir / "mem-mesh-session-start.sh").exists()
    has_enhanced_stop = (hooks_dir / "mem-mesh-stop-enhanced.sh").exists()
    has_stop_decide = (hooks_dir / "mem-mesh-stop-decide.sh").exists()
    has_reflect = (hooks_dir / "mem-mesh-reflect.sh").exists()
    has_stop = (hooks_dir / "mem-mesh-stop.sh").exists()
    has_prompt_stop = (
        _has_prompt_stop_hook(settings_path) if settings_path else False
    )

    if has_enhanced_stop:
        return "enhanced"
    if has_stop_decide:
        return "standard"
    if has_prompt_stop:
        return "standard (prompt)"
    if has_stop:
        return "minimal"
    if has_reflect:
        return "legacy"
    if has_session_start:
        return "standard (partial)"
    return "unknown"


def cmd_status() -> None:
    """Print installation status. Delegates to app.cli.hooks.status."""
    from app.cli.hooks.status import cmd_status as _cmd_status

    _cmd_status()


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


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


def cmd_install(
    target: str,
    url: str,
    mode: str = "api",
    path: str = "",
    profile: str = "standard",
) -> None:
    """Install hooks for the specified target."""
    if mode == "local":
        resolved = path or str(Path(__file__).resolve().parent.parent.parent)
        print(f"Installing mem-mesh hooks (mode: local, path: {resolved})")
    else:
        resolved = ""
        print(f"Installing mem-mesh hooks (mode: api, url: {url})")

    print(f"Prompt version: {PROMPT_VERSION} | Profile: {profile}\n")

    if target in ("claude", "all"):
        _install_claude(url, mode, resolved, profile)
        print()
    if target in ("kiro", "all"):
        _install_kiro(url, mode, resolved)
        print()
    if target in ("cursor", "all"):
        _install_cursor(url, mode, resolved, profile)
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
    raise RuntimeError("unreachable")


def cmd_interactive() -> None:
    """Interactive hook installation wizard."""
    print("=" * 44)
    print("  mem-mesh hooks installer (interactive)")
    print("=" * 44)
    print()

    # Step 1: target
    print("[1/4] Select target IDE:")
    targets = ["Claude Code", "Kiro", "Cursor", "All"]
    target_keys = ["claude", "kiro", "cursor", "all"]
    idx = _prompt_choice("", targets, default=3)
    target = target_keys[idx]
    print()

    # Step 2: hook profile
    print("[2/4] Select hook profile:")
    profile_options = [
        f"Standard — {HOOK_PROFILES['standard']['description']}",
        f"Enhanced — {HOOK_PROFILES['enhanced']['description']}",
        f"Minimal  — {HOOK_PROFILES['minimal']['description']}",
    ]
    profile_keys = ["standard", "enhanced", "minimal"]
    profile_idx = _prompt_choice("", profile_options, default=0)
    profile = profile_keys[profile_idx]
    print()

    if profile == "enhanced":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("  NOTE: Enhanced profile requires ANTHROPIC_API_KEY.")
            print("  The reflect hook will be inactive until the key is set.")
            print("  Set it with: export ANTHROPIC_API_KEY=sk-ant-...")
            print()

    # Step 3: storage mode
    print("[3/4] Select storage mode:")
    modes = [
        f"API  — Send to remote server ({DEFAULT_URL})",
        "Local — Save directly to local SQLite",
    ]
    mode_idx = _prompt_choice("", modes, default=0)
    mode = "api" if mode_idx == 0 else "local"
    print()

    # Step 4: mode-specific config
    url = DEFAULT_URL
    mem_path = ""
    if mode == "api":
        print(f"[4/4] API URL [{DEFAULT_URL}]:")
        raw = input("  > ").strip()
        if raw:
            url = raw
    else:
        default_path = str(Path(__file__).resolve().parent.parent.parent)
        print(f"[4/4] mem-mesh project path [{default_path}]:")
        raw = input("  > ").strip()
        mem_path = raw if raw else default_path
    print()

    cmd_install(target, url, mode, mem_path, profile)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point for mem-mesh-hooks."""
    parser = argparse.ArgumentParser(
        prog="mem-mesh-hooks",
        description="Install/uninstall mem-mesh hooks for Claude Code, Kiro, and Cursor.",
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
        "--profile",
        choices=["standard", "enhanced", "minimal"],
        default="standard",
        help="Hook profile: standard (prompt hook, hybrid save), enhanced (+reflect), minimal (command, no LLM)",
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

    # doctor
    subparsers.add_parser("doctor", help="Run diagnostics and connectivity checks")

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
        cmd_install(args.target, args.url, args.mode, args.path, args.profile)
    elif args.command == "uninstall":
        cmd_uninstall(args.target)
    elif args.command == "status":
        cmd_status()
    elif args.command == "doctor":
        from app.cli.hooks.doctor import cmd_doctor

        cmd_doctor()
    elif args.command == "sync-project":
        cmd_sync_project(args.target, args.project_id)


if __name__ == "__main__":
    main()
