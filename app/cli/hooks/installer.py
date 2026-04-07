"""IDE-specific hook installation logic."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from app.cli.hooks.constants import (
    CLAUDE_HOOKS_DIR,
    CLAUDE_SETTINGS,
    CURSOR_HOOKS_DIR,
    CURSOR_SETTINGS,
    HOOK_PROFILES,
    KIRO_HOOKS_DIR,
    KIRO_SETTINGS,
)
from app.cli.hooks.cursor_adapters import (
    adapt_cursor_before_submit_prompt,
    adapt_cursor_precompact,
    adapt_cursor_subagent_start,
    adapt_cursor_subagent_stop,
)
from app.cli.hooks.templates import (
    CURSOR_SESSION_START_TEMPLATE,
    CURSOR_STOP_TEMPLATE,
    ENHANCED_STOP_HOOK_TEMPLATE,
    KIRO_STOP_HOOK_TEMPLATE,
    LOCAL_ENHANCED_STOP_HOOK_TEMPLATE,
    LOCAL_PRECOMPACT_HOOK_TEMPLATE,
    LOCAL_SESSION_END_HOOK_TEMPLATE,
    LOCAL_SESSION_START_HOOK_TEMPLATE,
    LOCAL_STOP_HOOK_TEMPLATE,
    LOCAL_SUBAGENT_START_HOOK_TEMPLATE,
    LOCAL_SUBAGENT_STOP_HOOK_TEMPLATE,
    LOCAL_TASK_COMPLETED_HOOK_TEMPLATE,
    LOCAL_USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
    PRECOMPACT_HOOK_TEMPLATE,
    SESSION_END_HOOK_TEMPLATE,
    SESSION_START_HOOK_TEMPLATE,
    STOP_DECIDE_HOOK_TEMPLATE,
    STOP_HOOK_TEMPLATE,
    SUBAGENT_START_HOOK_TEMPLATE,
    SUBAGENT_STOP_HOOK_TEMPLATE,
    TASK_COMPLETED_HOOK_TEMPLATE,
    USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
)
from app.cli.hooks.renderer import _render_template, _render_local_template, _write_script
from app.cli.hooks.json_ops import _merge_json_settings, _remove_hook_event


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

    hooks: List[Dict[str, Any]] = existing.get("hooks", [])

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
