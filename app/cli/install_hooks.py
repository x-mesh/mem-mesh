#!/usr/bin/env python3
"""mem-mesh-hooks: Install/uninstall mem-mesh hooks for AI coding tools.

Prompts and behavioral rules are defined in app.cli.prompts.behaviors (single
source of truth).  IDE-specific renderers in app.cli.prompts.renderers transform
those canonical definitions into each IDE's native format.

Bump PROMPT_VERSION in behaviors.py when rules change, then re-run:
    mem-mesh-hooks install --target all
    mem-mesh-hooks rules
    mem-mesh-hooks sync-project
"""

import argparse
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.cli.codex_config import (
    CODEX_CONFIG,
    CODEX_HOOKS_DIR,
    CODEX_HOOKS_FILE,
    build_codex_mcp_block,
    merge_codex_mcp_config,
    remove_codex_mcp_config,
)
from app.cli.hooks.cursor_adapters import (
    adapt_cursor_before_submit_prompt,
    adapt_cursor_precompact,
    adapt_cursor_subagent_start,
    adapt_cursor_subagent_stop,
)
from app.cli.hooks.hook_log import HOOK_LOG_BLOCK
from app.cli.hooks.json_ops import (
    MalformedSettingsError,
    _atomic_write_text,
    _load_settings_or_raise,
)
from app.cli.hooks.keywords import KEYWORD_MATCHER_BLOCK
from app.cli.hooks.netcheck import check_http_hook_url
from app.cli.hooks.renderer import (
    _safe_project_id,
    _shell_safe_local_path,
    _shell_safe_url,
)
from app.cli.hooks.templates import (
    CURSOR_PROJECT_AUTO_SAVE_TEMPLATE,
    CURSOR_PROJECT_SESSION_END_TEMPLATE,
    CURSOR_PROJECT_SESSION_START_TEMPLATE,
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
    POST_TOOL_USE_HOOK_TEMPLATE,
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
from app.cli.project_identity import SHELL_PROJECT_ID_RESOLVER
from app.cli.prompts.behaviors import PROMPT_VERSION, REFLECT_CONFIG
from app.cli.prompts.renderers import (
    VERSION_MARKER,
    extract_prompt_version,
    render_claude_project_rules,
    render_cursor_followup,
    render_enhanced_stop_prompt,
    render_kiro_auto_create_pin,
    render_kiro_auto_save,
    render_kiro_load_context,
    render_reflect_prompt,
    render_rules_text,
)
from app.core.config import HOOK_TOKEN_FILE

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
            "post-tool-use",
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
            "post-tool-use",
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


# Claude Code hook events that have a server-side HTTP endpoint
# (app/web/dashboard/route_modules/hooks.py). In mode="http" these become
# `{"type": "http"}` entries; events absent here have no endpoint yet and
# stay command hooks even in http mode.
_HTTP_HOOK_ENDPOINTS = {
    "SessionStart": "session-start",
    "Stop": "stop",
    "UserPromptSubmit": "user-prompt-submit",
    "PostToolUse": "post-tool-use",
    "SubagentStop": "subagent-stop",
    "TaskCompleted": "task-completed",
}

# PostToolUse fires for every tool; this matcher restricts the hook to file
# mutations so the write-signal recorder only runs on real edits. Claude Code
# matches the tool name against this regex (the server re-checks too).
_WRITE_TOOL_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"


# The operator-side env var name for the hook auth token. The CLI materializes
# this value into ~/.mem-mesh/hook_token and bakes it into HTTP hook / MCP
# configs as a literal bearer header.
HOOK_TOKEN_ENV_VAR = "MEM_MESH_HOOK_TOKEN"

# The on-disk materialized API URL, backing the MEM_MESH_API_URL env (the
# operator SSOT). Generated .sh hooks resolve the URL as
# ``${MEM_MESH_API_URL:-$(cat ~/.mem-mesh/api_url)}`` (see app/cli/hooks/shell/*):
# the env wins, and this file is the fallback/cache the hooks read when it is
# unset or unavailable.
API_URL_FILE = Path.home() / ".mem-mesh" / "api_url"


def _ensure_api_url(url: str) -> None:
    """Materialize the effective API URL into ``~/.mem-mesh/api_url``.

    ``MEM_MESH_API_URL`` is the operator SSOT, but Cursor/Kiro/Claude/Codex
    hooks need a local fallback/cache. Writing the effective value at install
    time keeps that materialized file in sync. Not a secret (0644). Idempotent:
    write only when missing or changed.
    """
    normalized = url.rstrip("/")
    try:
        current: Optional[str] = API_URL_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        current = None
    if current == normalized:
        return
    _atomic_write_text(API_URL_FILE, normalized + "\n", mode=0o644)


def _write_hook_token(token: str) -> None:
    """Write an explicit hook token to ``~/.mem-mesh/hook_token`` (0600 cache).

    This materializes a caller-supplied value — e.g. ``mcp config --token`` —
    so hooks and generated MCP configs can use the same credential. 0600 because
    it is a secret. Idempotent: no rewrite when the file already matches.
    """
    normalized = token.strip()
    if not normalized:
        return
    from app.core.config import _read_token_file

    if _read_token_file(HOOK_TOKEN_FILE) == normalized:
        return
    _atomic_write_text(HOOK_TOKEN_FILE, normalized + "\n", mode=0o600)


def _ensure_hook_token() -> str:
    """Return the effective hook auth token, materializing the cache if needed.

    Precedence is explicit operator policy: ``MEM_MESH_HOOK_TOKEN`` env wins,
    then ``~/.mem-mesh/hook_token``, then a generated token. The server's
    data-dir fallback is intentionally not consulted here: that file is
    server-private bootstrap state and must not become the client/MCP SSOT.
    """
    from app.core.config import _read_token_file

    env_token = (os.environ.get(HOOK_TOKEN_ENV_VAR) or "").strip()
    if env_token:
        if _read_token_file(HOOK_TOKEN_FILE) != env_token:
            _atomic_write_text(HOOK_TOKEN_FILE, env_token + "\n", mode=0o600)
        return env_token

    existing = _read_token_file(HOOK_TOKEN_FILE)
    if existing:
        return existing

    token = secrets.token_urlsafe(32)
    _atomic_write_text(HOOK_TOKEN_FILE, token + "\n", mode=0o600)
    return token


def _claude_hook_entry(
    event: str,
    command: str,
    timeout: int,
    *,
    mode: str,
    url: str,
    is_async: bool = False,
    matcher: Optional[str] = None,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one Claude Code hook entry.

    Returns an ``http``-type entry when ``mode == "http"`` and the event has a
    server endpoint; otherwise a ``command``-type entry. HTTP hooks are
    non-blocking by nature, so the ``async`` flag is only meaningful for
    command hooks. ``matcher`` (used by PostToolUse) scopes the entry to a
    tool-name regex; when set it is emitted alongside ``hooks`` so Claude Code
    only fires the hook for matching tools. ``token`` is the hook auth secret
    baked directly into the Authorization header as a literal (resolved from
    env-first materialized config at install time); when ``None`` the header is
    omitted (unauthenticated server).
    """
    if mode == "http" and event in _HTTP_HOOK_ENDPOINTS:
        endpoint = _HTTP_HOOK_ENDPOINTS[event]
        # Authenticate the native HTTP hook with a bearer token baked in as a
        # literal value (read from ~/.mem-mesh/hook_token at install time, see
        # _ensure_hook_token). No shell env interpolation: the token is stamped
        # straight into settings.json so GUI-launched clients authenticate
        # without a shell export. Re-run install to re-stamp a rotated token.
        hook: Dict[str, Any] = {
            "type": "http",
            "url": f"{url.rstrip('/')}/api/hooks/claude/{endpoint}",
            "timeout": timeout,
        }
        if token:
            hook["headers"] = {"Authorization": f"Bearer {token}"}
    else:
        hook = {"type": "command", "command": command, "timeout": timeout}
        if is_async:
            hook["async"] = True
    if matcher is not None:
        return {"matcher": matcher, "hooks": [hook]}
    return {"hooks": [hook]}


def _build_claude_hooks_settings(
    profile: str = "standard",
    mode: str = "api",
    url: str = DEFAULT_URL,
    hooks_prefix: str = "~/.claude/hooks",
    *,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """Build Claude Code hooks settings dynamically based on profile and mode.

    Profiles:
      - minimal: command-based stop hook (no LLM cost, simple truncation)
      - standard: native prompt-based stop hook (hybrid summarization via Haiku)
      - enhanced: prompt stop + async reflect command (structured analysis)

    Modes:
      - api/local: every hook is a `bash + curl` command script
      - http: events with a server endpoint (see ``_HTTP_HOOK_ENDPOINTS``)
        become native HTTP hooks pointing at ``{url}/api/hooks/claude/*``;
        the rest stay command hooks. The keyword/profile logic for the Stop
        hook runs server-side, so all profiles share the same ``/stop``
        endpoint in http mode.

    ``hooks_prefix`` controls the directory prefix used in ``command`` entries
    (api/local mode only — http mode uses ``url``).  Pass
    ``"$CLAUDE_PROJECT_DIR/.claude/hooks"`` for project-scoped installs so
    Claude Code resolves the path relative to the project root at runtime.
    The default ``"~/.claude/hooks"`` preserves the legacy global behaviour.
    """
    settings: Dict[str, Any] = {"hooks": {}}

    # SessionStart: inject session context (all profiles)
    settings["hooks"]["SessionStart"] = [
        _claude_hook_entry(
            "SessionStart",
            f"{hooks_prefix}/mem-mesh-session-start.sh",
            15,
            mode=mode,
            url=url,
            token=token,
        )
    ]

    # Stop: profile picks the command script; http mode collapses all
    # profiles onto the single server-side /stop endpoint.
    stop_command = {
        "standard": (f"{hooks_prefix}/mem-mesh-stop-decide.sh", 10),
        "enhanced": (f"{hooks_prefix}/mem-mesh-stop-enhanced.sh", 20),
        "minimal": (f"{hooks_prefix}/mem-mesh-stop.sh", 10),
    }
    stop_cmd, stop_timeout = stop_command.get(profile, stop_command["minimal"])
    settings["hooks"]["Stop"] = [
        _claude_hook_entry(
            "Stop",
            stop_cmd,
            stop_timeout,
            mode=mode,
            url=url,
            is_async=True,
            token=token,
        )
    ]

    # UserPromptSubmit: keyword-filtered context search (standard/enhanced only)
    if profile != "minimal":
        settings["hooks"]["UserPromptSubmit"] = [
            _claude_hook_entry(
                "UserPromptSubmit",
                f"{hooks_prefix}/mem-mesh-user-prompt-submit.sh",
                5,
                mode=mode,
                url=url,
                token=token,
            )
        ]

    # PostToolUse: record a write-signal so the pin/save reminders fire on real
    # edits, not on absence (standard/enhanced only). The matcher scopes it to
    # file-mutating tools; the hook is fire-and-forget (async) and never blocks.
    # Skipped in local mode — there the UserPromptSubmit hook derives the write
    # signal from the transcript directly, so no PostToolUse script is needed.
    if profile != "minimal" and mode != "local":
        settings["hooks"]["PostToolUse"] = [
            _claude_hook_entry(
                "PostToolUse",
                f"{hooks_prefix}/mem-mesh-post-tool-use.sh",
                5,
                mode=mode,
                url=url,
                is_async=True,
                matcher=_WRITE_TOOL_MATCHER,
                token=token,
            )
        ]

    # SubagentStart: inject project context (standard/enhanced only).
    # No HTTP endpoint yet — stays a command hook even in http mode.
    if profile != "minimal":
        settings["hooks"]["SubagentStart"] = [
            _claude_hook_entry(
                "SubagentStart",
                f"{hooks_prefix}/mem-mesh-subagent-start.sh",
                5,
                mode=mode,
                url=url,
                token=token,
            )
        ]

    # SubagentStop: auto-save important results (standard/enhanced only)
    if profile != "minimal":
        settings["hooks"]["SubagentStop"] = [
            _claude_hook_entry(
                "SubagentStop",
                f"{hooks_prefix}/mem-mesh-subagent-stop.sh",
                10,
                mode=mode,
                url=url,
                is_async=True,
                token=token,
            )
        ]

    # TaskCompleted: auto-save completed tasks (standard/enhanced only)
    if profile != "minimal":
        settings["hooks"]["TaskCompleted"] = [
            _claude_hook_entry(
                "TaskCompleted",
                f"{hooks_prefix}/mem-mesh-task-completed.sh",
                10,
                mode=mode,
                url=url,
                is_async=True,
                token=token,
            )
        ]

    # SessionEnd: auto-end session on exit (all profiles).
    # No HTTP endpoint yet — stays a command hook even in http mode.
    settings["hooks"]["SessionEnd"] = [
        _claude_hook_entry(
            "SessionEnd",
            f"{hooks_prefix}/mem-mesh-session-end.sh",
            10,
            mode=mode,
            url=url,
            token=token,
        )
    ]

    # PreCompact: auto-end session before context compaction (all profiles).
    # No HTTP endpoint yet — stays a command hook even in http mode.
    settings["hooks"]["PreCompact"] = [
        _claude_hook_entry(
            "PreCompact",
            f"{hooks_prefix}/mem-mesh-precompact.sh",
            10,
            mode=mode,
            url=url,
            token=token,
        )
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
    hook_output_mode: str = "full",
) -> str:
    """Replace all placeholders in a template string."""
    project_id = _safe_project_id(project_id)
    if hook_output_mode not in {"full", "compact", "quiet"}:
        raise ValueError("hook_output_mode must be one of: full, compact, quiet")
    result = template.replace("__DEFAULT_URL__", _shell_safe_url(url))
    result = result.replace("__VERSION_MARKER__", VERSION_MARKER)
    result = result.replace("__SOURCE_TAG__", source_tag)
    result = result.replace("__IDE_TAG__", ide_tag)
    # Opt-in hook logging block (single source of truth). Injected BEFORE
    # __CLIENT_TAG__ so the block's own __CLIENT_TAG__ placeholder (the client
    # tag stamped on every log line) is substituted along with the template's.
    result = result.replace("__HOOK_LOG__", HOOK_LOG_BLOCK)
    result = result.replace("__CLIENT_TAG__", client_tag)
    result = result.replace("__HOOK_OUTPUT_MODE__", hook_output_mode)
    result = result.replace("__PROJECT_ID_RESOLVER__", SHELL_PROJECT_ID_RESOLVER)
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
    hook_output_mode: str = "full",
) -> str:
    """Replace placeholders for local mode templates."""
    project_id = _safe_project_id(project_id)
    if hook_output_mode not in {"full", "compact", "quiet"}:
        raise ValueError("hook_output_mode must be one of: full, compact, quiet")
    result = template.replace(
        "__MEM_MESH_PATH__", _shell_safe_local_path(mem_mesh_path)
    )
    result = result.replace("__VERSION_MARKER__", VERSION_MARKER)
    result = result.replace("__HOOK_OUTPUT_MODE__", hook_output_mode)
    result = result.replace("__PROJECT_ID_RESOLVER__", SHELL_PROJECT_ID_RESOLVER)
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
    # Opt-in hook logging block (single source of truth)
    result = result.replace("__HOOK_LOG__", HOOK_LOG_BLOCK)
    # Local-mode hooks carry no client_tag; resolve the block's tag so no
    # placeholder leaks if a local template ever opts into __HOOK_LOG__.
    result = result.replace("__CLIENT_TAG__", "local")
    return result


def _file_unchanged(path: Path, content: str) -> bool:
    """True when ``path`` already holds exactly ``content``.

    The rendered artifacts embed the prompt version (VERSION_MARKER / the
    CLAUDE.md ``BEGIN vN`` marker), so identical content implies same version
    AND same url/mode/profile — a strictly safer skip condition than comparing
    version numbers alone (same version with a changed URL must still rewrite).
    """
    try:
        return path.exists() and path.read_text(encoding="utf-8") == content
    except OSError:
        return False


def _write_script(path: Path, content: str) -> bool:
    """Write a shell script and make it executable (atomically).

    Returns False without touching the file when it already holds exactly this
    content and is executable — so a repeated ``mem-mesh hooks install`` /
    ``sync-project`` of the same prompt version is a no-op instead of churning
    every hook file on each run.
    """
    unresolved = re.findall(r"__[A-Z0-9_]+__", content)
    if unresolved:
        tokens = ", ".join(sorted(set(unresolved)))
        raise ValueError(f"Unresolved template tokens in {path}: {tokens}")
    if _file_unchanged(path, content) and os.access(path, os.X_OK):
        return False
    _atomic_write_text(
        path,
        content,
        mode=stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
    )
    return True


def _is_mem_mesh_hook(hook: Dict[str, Any]) -> bool:
    """Return True if a hook definition belongs to mem-mesh."""
    hook_type = str(hook.get("type", ""))
    command = str(hook.get("command", ""))
    prompt = str(hook.get("prompt", ""))
    url = str(hook.get("url", ""))
    if "mem-mesh-" in command:
        return True
    # http mode: native HTTP hooks point at the mem-mesh hook endpoints.
    if hook_type == "http" and "/api/hooks/claude/" in url:
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


def _merge_json_settings(
    path: Path, patch: Dict[str, Any], *, force: bool = False
) -> None:
    """Merge patch into an existing JSON file, preserving other keys.

    If the existing file is malformed it is backed up to ``<path>.bak`` and a
    :class:`MalformedSettingsError` is raised (unless ``force=True``), instead
    of silently discarding the user's settings. The write itself is atomic.
    """
    existing: Dict[str, Any] = _load_settings_or_raise(path, force=force)

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
                if isinstance(current_entries, list) and isinstance(
                    patch_entries, list
                ):
                    merged_hooks[event_name] = _merge_hook_entries(
                        current_entries, patch_entries
                    )
                else:
                    merged_hooks[event_name] = patch_entries
            existing[key] = merged_hooks
        else:
            existing[key] = value

    _atomic_write_text(
        path,
        json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
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
        _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


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
        _atomic_write_text(
            path,
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
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
        _atomic_write_text(
            path,
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
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
    hooks: List[Dict[str, Any]] = data.get("hooks", [])
    data["hooks"] = [h for h in hooks if not h.get("name", "").startswith("mem-mesh:")]
    _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _remove_kiro_cli_agent_hook(path: Path) -> None:
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


# ---------------------------------------------------------------------------
# Install / Uninstall commands
# ---------------------------------------------------------------------------

HOME = Path.home()

CLAUDE_HOOKS_DIR = HOME / ".claude" / "hooks"
CLAUDE_SETTINGS = HOME / ".claude" / "settings.json"

KIRO_HOOKS_DIR = HOME / ".kiro" / "hooks"
KIRO_SCRIPTS_DIR = HOME / ".kiro" / "mem-mesh-hooks"
KIRO_SETTINGS = HOME / ".kiro" / "settings" / "hooks.json"
KIRO_CLI_AGENTS_DIR = HOME / ".kiro" / "agents"
KIRO_CLI_AGENT = KIRO_CLI_AGENTS_DIR / "mem-mesh.json"

CURSOR_HOOKS_DIR = HOME / ".cursor" / "hooks"
CURSOR_SETTINGS = HOME / ".cursor" / "hooks.json"

ANTIGRAVITY_CONFIG_DIR = HOME / ".gemini" / "antigravity"
ANTIGRAVITY_HOOKS_DIR = ANTIGRAVITY_CONFIG_DIR / "hooks"
ANTIGRAVITY_HOOKS_FILE = ANTIGRAVITY_CONFIG_DIR / "hooks.json"

AGY_CONFIG_DIR = HOME / ".gemini" / "antigravity-cli"
AGY_HOOKS_DIR = AGY_CONFIG_DIR / "hooks"
AGY_HOOKS_FILE = HOME / ".gemini" / "config" / "hooks.json"


def _build_codex_hooks_settings(
    hooks_dir: Path, profile: str = "standard", mode: str = "api"
) -> Dict[str, Any]:
    """Build Codex hooks.json using only command hooks.

    Codex currently parses but skips ``async: true`` command hooks and does not
    run native ``type: http`` hook handlers, so this is intentionally separate
    from the Claude Code settings builder.
    """
    stop_script = {
        "standard": (
            hooks_dir / "mem-mesh-stop.sh"
            if mode == "local"
            else hooks_dir / "mem-mesh-stop-decide.sh"
        ),
        "enhanced": hooks_dir / "mem-mesh-stop-enhanced.sh",
        "minimal": hooks_dir / "mem-mesh-stop.sh",
    }.get(profile, hooks_dir / "mem-mesh-stop-decide.sh")

    hooks: Dict[str, Any] = {
        "SessionStart": [
            {
                "matcher": "startup|resume|clear|compact",
                "hooks": [
                    {
                        "type": "command",
                        "command": str(hooks_dir / "mem-mesh-session-start.sh"),
                        "timeout": 15,
                        "statusMessage": "Loading mem-mesh context",
                    }
                ],
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": str(stop_script),
                        "timeout": 20 if profile == "enhanced" else 10,
                        "statusMessage": "Saving mem-mesh checkpoint",
                    }
                ]
            }
        ],
        "PreCompact": [
            {
                "matcher": "manual|auto",
                "hooks": [
                    {
                        "type": "command",
                        "command": str(hooks_dir / "mem-mesh-precompact.sh"),
                        "timeout": 10,
                        "statusMessage": "Checking mem-mesh checkpoint",
                    }
                ],
            }
        ],
    }

    if profile != "minimal":
        hooks["UserPromptSubmit"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": str(hooks_dir / "mem-mesh-user-prompt-submit.sh"),
                        "timeout": 5,
                        "statusMessage": "Searching mem-mesh context",
                    }
                ]
            }
        ]
        if mode != "local":
            hooks["PostToolUse"] = [
                {
                    "matcher": "Edit|Write|MultiEdit|NotebookEdit|apply_patch",
                    "hooks": [
                        {
                            "type": "command",
                            "command": str(hooks_dir / "mem-mesh-post-tool-use.sh"),
                            "timeout": 5,
                            "statusMessage": "Recording mem-mesh write signal",
                        }
                    ],
                }
            ]
        hooks["SubagentStart"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": str(hooks_dir / "mem-mesh-subagent-start.sh"),
                        "timeout": 5,
                        "statusMessage": "Loading mem-mesh subagent context",
                    }
                ]
            }
        ]
        hooks["SubagentStop"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": str(hooks_dir / "mem-mesh-subagent-stop.sh"),
                        "timeout": 10,
                        "statusMessage": "Saving mem-mesh subagent result",
                    }
                ]
            }
        ]

    return {"hooks": hooks}


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


def _build_kiro_agent_stop_hook(script_path: Path) -> Dict[str, Any]:
    """Build Kiro's native `.kiro.hook` file for response persistence."""
    return {
        "name": "mem-mesh: Save Response",
        "version": "1.0.0",
        "description": "Save useful agent responses to mem-mesh.",
        "when": {"type": "agentStop"},
        "then": {
            "type": "runCommand",
            "command": str(script_path),
        },
    }


def _kiro_cli_stop_entry(script_path: Path) -> Dict[str, Any]:
    """Build a Kiro CLI custom-agent stop hook entry."""
    return {
        "command": str(script_path),
        "timeout_ms": 30000,
        "max_output_size": 1024,
    }


def _write_kiro_cli_agent(agent_path: Path, script_path: Path) -> None:
    """Write/update the Kiro CLI custom agent hook without clobbering user fields."""
    try:
        existing = json.loads(agent_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            existing = {}
    except (json.JSONDecodeError, OSError):
        existing = {}

    agent = dict(existing)
    agent.setdefault("name", "mem-mesh")
    agent.setdefault(
        "description", "Kiro CLI agent with mem-mesh response persistence."
    )
    agent.setdefault("prompt", "")
    agent.setdefault("tools", ["read", "write", "shell", "thinking", "todo"])
    agent.setdefault("allowedTools", [])
    agent.setdefault("includeMcpJson", True)

    hooks = agent.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    stop_hooks = hooks.get("stop")
    if not isinstance(stop_hooks, list):
        stop_hooks = []
    stop_hooks = [
        entry
        for entry in stop_hooks
        if not (
            isinstance(entry, dict)
            and "mem-mesh-stop.sh" in str(entry.get("command", ""))
        )
    ]
    stop_hooks.append(_kiro_cli_stop_entry(script_path))
    hooks["stop"] = stop_hooks
    agent["hooks"] = hooks

    _atomic_write_text(
        agent_path,
        json.dumps(agent, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )


def _build_antigravity_hooks_settings(hooks_dir: Path) -> Dict[str, Any]:
    """Build Antigravity-style hooks.json using absolute command hooks."""
    return {
        "mem-mesh": {
            "PreInvocation": None,
            "PostInvocation": None,
            "Stop": [
                {
                    "type": "command",
                    "command": str(hooks_dir / "mem-mesh-stop.sh"),
                    "timeout": 10,
                }
            ],
            "PreToolUse": None,
            "PostToolUse": [
                {
                    "matcher": (
                        "write_to_file|replace_file_content|"
                        "multi_replace_file_content|edit|write|run_command"
                    ),
                    "hooks": [
                        {
                            "type": "command",
                            "command": str(hooks_dir / "mem-mesh-post-tool-use.sh"),
                            "timeout": 5,
                        }
                    ],
                }
            ],
        }
    }


def _merge_antigravity_hooks_settings(
    settings_path: Path, patch: Dict[str, Any], *, force: bool = False
) -> None:
    """Merge Antigravity hook groups, preserving non-mem-mesh groups."""
    data = _load_settings_or_raise(settings_path, force=force)
    if not isinstance(data, dict):
        data = {}
    for key in list(data.keys()):
        if "mem-mesh" in str(key):
            data.pop(key, None)
    data.update(patch)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        settings_path,
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )


def _remove_antigravity_mem_mesh_hooks(path: Path) -> None:
    """Remove mem-mesh hook groups from Antigravity hooks.json."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(data, dict):
        return
    for key in list(data.keys()):
        if "mem-mesh" in str(key):
            data.pop(key, None)
    _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _install_claude(
    url: str,
    mode: str = "api",
    path: str = "",
    profile: str = "standard",
    *,
    force: bool = False,
    base_dir: Optional[Path] = None,
) -> None:
    """Install mem-mesh hooks for Claude Code.

    ``base_dir`` selects the install root: project scope writes under
    ``<base_dir>/.claude``, while global scope (``base_dir is None``) keeps
    the legacy module-level ``HOME/.claude`` paths.
    """
    if base_dir is not None:
        _claude_dir = base_dir / ".claude"
        hooks_dir = _claude_dir / "hooks"
        settings_path = _claude_dir / "settings.json"
    else:
        hooks_dir = CLAUDE_HOOKS_DIR
        settings_path = CLAUDE_SETTINGS
    profile_info = HOOK_PROFILES[profile]
    # http mode: events with a server endpoint are configured as native HTTP
    # hooks in settings.json — no shell script is written for them. Events
    # without an endpoint yet (SubagentStart/SessionEnd/PreCompact) still get
    # a command script, rendered exactly like api mode.
    _http = mode == "http"
    mode_label = "http" if _http else mode
    print(
        f"[claude] Installing hook scripts (profile: {profile}, mode: {mode_label})..."
    )

    session_start_script = hooks_dir / "mem-mesh-session-start.sh"
    track_script = hooks_dir / "mem-mesh-track.sh"
    stop_script = hooks_dir / "mem-mesh-stop.sh"
    enhanced_stop_script = hooks_dir / "mem-mesh-stop-enhanced.sh"
    reflect_script = hooks_dir / "mem-mesh-reflect.sh"
    decide_script = hooks_dir / "mem-mesh-stop-decide.sh"
    ups_script = hooks_dir / "mem-mesh-user-prompt-submit.sh"
    ptu_script = hooks_dir / "mem-mesh-post-tool-use.sh"

    # SessionStart hook (all profiles)
    if not _http:
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

    # Stop hook
    if not _http:
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
    if not _http and "user-prompt-submit" in profile_info["hooks"]:
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

    # PostToolUse hook (standard/enhanced only) — write-signal recorder.
    # api/local modes write a command script; http mode uses the server
    # endpoint (no script). local mode gates reminders from the transcript in
    # the UserPromptSubmit hook instead, so it needs no write-signal script.
    if not _http and mode != "local" and "post-tool-use" in profile_info["hooks"]:
        _write_script(
            ptu_script,
            _render_template(
                POST_TOOL_USE_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
            ),
        )
        print(f"  -> {ptu_script}")

    # SubagentStart hook (standard/enhanced only)
    if "subagent-start" in profile_info["hooks"]:
        sa_start_script = hooks_dir / "mem-mesh-subagent-start.sh"
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
    if not _http and "subagent-stop" in profile_info["hooks"]:
        sa_stop_script = hooks_dir / "mem-mesh-subagent-stop.sh"
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
    if not _http and "task-completed" in profile_info["hooks"]:
        tc_script = hooks_dir / "mem-mesh-task-completed.sh"
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
    session_end_script = hooks_dir / "mem-mesh-session-end.sh"
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
    precompact_script = hooks_dir / "mem-mesh-precompact.sh"
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

    # http mode: drop the shell scripts whose work moved to a server endpoint.
    if _http:
        for script in (
            session_start_script,
            decide_script,
            enhanced_stop_script,
            stop_script,
            ups_script,
            ptu_script,
            hooks_dir / "mem-mesh-subagent-stop.sh",
            hooks_dir / "mem-mesh-task-completed.sh",
        ):
            if script.exists():
                script.unlink()
                print(f"  removed {script} (replaced by HTTP hook)")

    # http hooks authenticate with a bearer token baked into settings.json as a
    # literal. Resolve it from env-first materialized config (generating the
    # ~/.mem-mesh cache if missing) and stamp it straight into each HTTP hook's
    # Authorization header so GUI-launched clients authenticate too.
    _hook_token: Optional[str] = None
    if _http:
        _hook_token = _ensure_hook_token()
        print(
            f"  hook auth: token at {HOOK_TOKEN_FILE} — baked into each tool"
            " config as a literal bearer header"
        )

    print("[claude] Updating settings.json...")
    # Project-scoped install: use $CLAUDE_PROJECT_DIR variable so Claude Code
    # resolves the hooks directory relative to the project root at runtime.
    # Global install: keep the legacy ~/.claude/hooks default.
    if base_dir is not None:
        _hooks_prefix = "$CLAUDE_PROJECT_DIR/.claude/hooks"
    else:
        _hooks_prefix = "~/.claude/hooks"
    hooks_settings = _build_claude_hooks_settings(
        profile, mode, url, _hooks_prefix, token=_hook_token
    )
    _merge_json_settings(settings_path, hooks_settings, force=force)
    # NOTE: mem-mesh now *owns* a PostToolUse hook (write-signal recorder), so
    # the legacy "remove all PostToolUse" cleanup is gone — _merge_json_settings
    # already replaces the old mem-mesh-track.sh entry while preserving any
    # user-defined PostToolUse hooks.
    print(f"  -> {settings_path}")

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


def _install_kiro(
    url: str,
    mode: str = "api",
    path: str = "",
    *,
    base_dir: Optional[Path] = None,
) -> None:
    """Install mem-mesh hooks for Kiro.

    ``base_dir`` selects the install root: project scope writes under
    ``<base_dir>/.kiro``. Kiro reads native ``.kiro.hook`` files from
    ``.kiro/hooks``; helper shell scripts live in a sibling directory so the
    hook directory contains only Kiro hook files.
    """
    print("[kiro] Installing hook script...")

    if base_dir is not None:
        _kiro_dir = base_dir / ".kiro"
        hooks_dir = _kiro_dir / "mem-mesh-hooks"
        legacy_script = _kiro_dir / "hooks" / "mem-mesh-stop.sh"
        hook_file = _kiro_dir / "hooks" / "mem-mesh-save-response.kiro.hook"
        settings_path = _kiro_dir / "settings" / "hooks.json"
        cli_agent_path: Optional[Path] = None
    else:
        hooks_dir = KIRO_SCRIPTS_DIR
        legacy_script = KIRO_HOOKS_DIR / "mem-mesh-stop.sh"
        hook_file = KIRO_HOOKS_DIR / "mem-mesh-save-response.kiro.hook"
        settings_path = KIRO_SETTINGS
        cli_agent_path: Optional[Path] = KIRO_CLI_AGENT

    stop_script = hooks_dir / "mem-mesh-stop.sh"
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

    print("[kiro] Writing native .kiro.hook file...")
    hook_file.parent.mkdir(parents=True, exist_ok=True)
    hook_file.write_text(
        json.dumps(
            _build_kiro_agent_stop_hook(stop_script),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"  -> {hook_file}")

    if base_dir is None and cli_agent_path is not None:
        print("[kiro] Writing Kiro CLI custom agent hook...")
        _write_kiro_cli_agent(cli_agent_path, stop_script)
        print(f"  -> {cli_agent_path}")
        print("  use: kiro-cli chat --agent mem-mesh")

    if legacy_script.exists():
        legacy_script.unlink()
        print(f"  removed legacy {legacy_script}")

    # Remove the legacy settings/hooks.json registration if it exists. Modern
    # Kiro reads `.kiro/hooks/*.kiro.hook`; the old settings entry is inert.
    _remove_kiro_mem_mesh_hooks(settings_path)
    if settings_path.exists():
        print(f"  cleaned legacy mem-mesh entries from {settings_path}")

    print("[kiro] Done.")


def _install_antigravity_like(
    label: str,
    hooks_dir: Path,
    settings_path: Path,
    url: str,
    mode: str = "api",
    path: str = "",
    *,
    force: bool = False,
    source_tag: str,
    ide_tag: str,
    client_tag: str,
) -> None:
    """Install mem-mesh hooks for Antigravity-style hooks.json clients."""
    print(f"[{label}] Installing hook scripts...")

    stop_script = hooks_dir / "mem-mesh-stop.sh"
    post_tool_script = hooks_dir / "mem-mesh-post-tool-use.sh"

    if mode == "local":
        _write_script(
            stop_script,
            _render_local_template(LOCAL_STOP_HOOK_TEMPLATE, path),
        )
        _write_script(
            post_tool_script,
            _render_local_template(LOCAL_TASK_COMPLETED_HOOK_TEMPLATE, path),
        )
    else:
        _write_script(
            stop_script,
            _render_template(
                KIRO_STOP_HOOK_TEMPLATE,
                url,
                source_tag=source_tag,
                ide_tag=ide_tag,
                client_tag=client_tag,
            ),
        )
        _write_script(
            post_tool_script,
            _render_template(
                POST_TOOL_USE_HOOK_TEMPLATE,
                url,
                source_tag=source_tag,
                ide_tag=ide_tag,
                client_tag=client_tag,
            ),
        )

    print(f"  -> {stop_script}")
    print(f"  -> {post_tool_script}")

    print(f"[{label}] Updating hooks.json...")
    _merge_antigravity_hooks_settings(
        settings_path,
        _build_antigravity_hooks_settings(hooks_dir),
        force=force,
    )
    print(f"  -> {settings_path}")

    print(f"[{label}] Done.")


def _install_antigravity(
    url: str,
    mode: str = "api",
    path: str = "",
    *,
    force: bool = False,
    base_dir: Optional[Path] = None,
) -> None:
    """Install mem-mesh hooks for Antigravity IDE."""
    if base_dir is not None:
        root = base_dir / ".agents"
        hooks_dir = root / "hooks"
        settings_path = root / "hooks.json"
    else:
        hooks_dir = ANTIGRAVITY_HOOKS_DIR
        settings_path = ANTIGRAVITY_HOOKS_FILE
    _install_antigravity_like(
        "antigravity",
        hooks_dir,
        settings_path,
        url,
        mode,
        path,
        force=force,
        source_tag="antigravity-hook",
        ide_tag="antigravity",
        client_tag="antigravity",
    )


def _install_agy(
    url: str,
    mode: str = "api",
    path: str = "",
    *,
    force: bool = False,
    base_dir: Optional[Path] = None,
) -> None:
    """Install mem-mesh hooks for Antigravity CLI (`agy`)."""
    if base_dir is not None:
        root = base_dir / ".agents"
        hooks_dir = root / "hooks"
        settings_path = root / "hooks.json"
    else:
        hooks_dir = AGY_HOOKS_DIR
        settings_path = AGY_HOOKS_FILE
    _install_antigravity_like(
        "agy",
        hooks_dir,
        settings_path,
        url,
        mode,
        path,
        force=force,
        source_tag="agy-hook",
        ide_tag="agy",
        client_tag="agy",
    )


def _install_cursor(
    url: str,
    mode: str = "api",
    path: str = "",
    profile: str = "standard",
    *,
    force: bool = False,
    base_dir: Optional[Path] = None,
) -> None:
    """Install mem-mesh hooks for Cursor.

    ``base_dir`` selects the install root: project scope writes under
    ``<base_dir>/.cursor``, while global scope (``base_dir is None``) keeps the
    legacy module-level ``HOME/.cursor`` paths.
    """
    print(f"[cursor] Installing hook scripts (profile: {profile})...")

    if base_dir is not None:
        _cursor_dir = base_dir / ".cursor"
        hooks_dir = _cursor_dir / "hooks"
        settings_path = _cursor_dir / "hooks.json"
    else:
        hooks_dir = CURSOR_HOOKS_DIR
        settings_path = CURSOR_SETTINGS

    session_start_script = hooks_dir / "mem-mesh-session-start.sh"
    track_script = hooks_dir / "mem-mesh-track.sh"
    stop_script = hooks_dir / "mem-mesh-stop.sh"
    before_submit_prompt_script = hooks_dir / "mem-mesh-before-submit-prompt.sh"
    precompact_script = hooks_dir / "mem-mesh-precompact.sh"
    subagent_start_script = hooks_dir / "mem-mesh-subagent-start.sh"
    subagent_stop_script = hooks_dir / "mem-mesh-subagent-stop.sh"
    session_end_script = hooks_dir / "mem-mesh-session-end.sh"

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
        settings_path,
        _build_cursor_hooks_settings(hooks_dir, scope="global"),
        force=force,
    )
    # Remove legacy postToolUse (track hook) from hooks.json
    _remove_hook_event(settings_path, "postToolUse")
    print(f"  -> {settings_path}")

    print("[cursor] Done.")


def _install_codex(
    url: str,
    mode: str = "api",
    path: str = "",
    profile: str = "standard",
    *,
    force: bool = False,
    base_dir: Optional[Path] = None,
) -> None:
    """Install mem-mesh hooks and MCP config for Codex.

    Codex does not run native HTTP hook handlers today; even when the installer
    mode is ``http``, lifecycle hooks are installed as command scripts. MCP
    still uses Streamable HTTP for ``api``/``http`` modes and stdio for
    ``local`` mode.
    """
    print(f"[codex] Installing hook scripts (profile: {profile})...")

    if base_dir is not None:
        codex_dir = base_dir / ".codex"
        hooks_dir = codex_dir / "hooks"
        hooks_path = codex_dir / "hooks.json"
        config_path = codex_dir / "config.toml"
    else:
        hooks_dir = CODEX_HOOKS_DIR
        hooks_path = CODEX_HOOKS_FILE
        config_path = CODEX_CONFIG

    script_mode = "api" if mode == "http" else mode

    scripts: Dict[str, str] = {}
    if script_mode == "local":
        scripts["mem-mesh-session-start.sh"] = _render_local_template(
            LOCAL_SESSION_START_HOOK_TEMPLATE, path, hook_output_mode="compact"
        )
        scripts["mem-mesh-precompact.sh"] = _render_local_template(
            LOCAL_PRECOMPACT_HOOK_TEMPLATE, path, hook_output_mode="compact"
        )
        if profile == "enhanced":
            scripts["mem-mesh-stop-enhanced.sh"] = _render_local_template(
                LOCAL_ENHANCED_STOP_HOOK_TEMPLATE, path
            )
        elif profile in ("minimal", "standard"):
            scripts["mem-mesh-stop.sh"] = _render_local_template(
                LOCAL_STOP_HOOK_TEMPLATE, path
            )
        if profile != "minimal":
            scripts["mem-mesh-user-prompt-submit.sh"] = _render_local_template(
                LOCAL_USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
                path,
                hook_output_mode="compact",
            )
            scripts["mem-mesh-subagent-start.sh"] = _render_local_template(
                LOCAL_SUBAGENT_START_HOOK_TEMPLATE,
                path,
                hook_output_mode="compact",
            )
            scripts["mem-mesh-subagent-stop.sh"] = _render_local_template(
                LOCAL_SUBAGENT_STOP_HOOK_TEMPLATE, path
            )
    else:
        scripts["mem-mesh-session-start.sh"] = _render_template(
            SESSION_START_HOOK_TEMPLATE,
            url,
            source_tag="codex-hook",
            ide_tag="codex",
            client_tag="codex",
            hook_output_mode="compact",
        )
        scripts["mem-mesh-precompact.sh"] = _render_template(
            PRECOMPACT_HOOK_TEMPLATE,
            url,
            source_tag="codex-hook",
            ide_tag="codex",
            client_tag="codex",
            hook_output_mode="compact",
        )
        if profile == "enhanced":
            scripts["mem-mesh-stop-enhanced.sh"] = _render_template(
                ENHANCED_STOP_HOOK_TEMPLATE,
                url,
                source_tag="codex-hook",
                ide_tag="codex",
                client_tag="codex",
            )
        elif profile == "minimal":
            scripts["mem-mesh-stop.sh"] = _render_template(
                STOP_HOOK_TEMPLATE,
                url,
                source_tag="codex-hook",
                ide_tag="codex",
                client_tag="codex",
            )
        else:
            scripts["mem-mesh-stop-decide.sh"] = _render_template(
                STOP_DECIDE_HOOK_TEMPLATE,
                url,
                source_tag="codex-hook",
                ide_tag="codex",
                client_tag="codex",
            )
        if profile != "minimal":
            scripts["mem-mesh-user-prompt-submit.sh"] = _render_template(
                USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
                url,
                source_tag="codex-hook",
                ide_tag="codex",
                client_tag="codex",
                hook_output_mode="compact",
            )
            scripts["mem-mesh-post-tool-use.sh"] = _render_template(
                POST_TOOL_USE_HOOK_TEMPLATE,
                url,
                source_tag="codex-hook",
                ide_tag="codex",
                client_tag="codex",
            )
            scripts["mem-mesh-subagent-start.sh"] = _render_template(
                SUBAGENT_START_HOOK_TEMPLATE,
                url,
                source_tag="codex-hook",
                ide_tag="codex",
                client_tag="codex",
                hook_output_mode="compact",
            )
            scripts["mem-mesh-subagent-stop.sh"] = _render_template(
                SUBAGENT_STOP_HOOK_TEMPLATE,
                url,
                source_tag="codex-hook",
                ide_tag="codex",
                client_tag="codex",
            )

    for name, content in scripts.items():
        script_path = hooks_dir / name
        _write_script(script_path, content)
        print(f"  -> {script_path}")

    stale_by_profile = {
        "standard": ["mem-mesh-stop.sh", "mem-mesh-stop-enhanced.sh"],
        "enhanced": ["mem-mesh-stop.sh", "mem-mesh-stop-decide.sh"],
        "minimal": [
            "mem-mesh-stop-decide.sh",
            "mem-mesh-stop-enhanced.sh",
            "mem-mesh-user-prompt-submit.sh",
            "mem-mesh-post-tool-use.sh",
            "mem-mesh-subagent-start.sh",
            "mem-mesh-subagent-stop.sh",
        ],
    }
    for name in stale_by_profile.get(profile, []):
        stale = hooks_dir / name
        if stale.exists() and name not in scripts:
            stale.unlink()
            print(f"  removed {stale} (not in {profile} profile)")

    print("[codex] Updating hooks.json...")
    _merge_json_settings(
        hooks_path,
        _build_codex_hooks_settings(hooks_dir, profile, mode=script_mode),
        force=force,
    )
    print(f"  -> {hooks_path}")

    print("[codex] Updating config.toml MCP server...")
    mcp_mode = "local" if mode == "local" else "http"
    mcp_path = path or str(Path(__file__).resolve().parent.parent.parent)
    # http mode bakes the literal hook token into config.toml's http_headers.
    # Use _ensure_hook_token() so the env-first effective token is materialized
    # before we stamp it; _ensure_hook_token is idempotent, so the later call is
    # a no-op.
    codex_token = _ensure_hook_token() if mcp_mode == "http" else None
    merge_codex_mcp_config(
        config_path,
        build_codex_mcp_block(mode=mcp_mode, url=url, path=mcp_path, token=codex_token),
    )
    print(f"  -> {config_path}")

    if mode != "local":
        _ensure_hook_token()
        print(
            f"  hook/MCP auth: token at {HOOK_TOKEN_FILE} — baked into the"
            " MCP config as a literal bearer header"
        )

    print("[codex] Done.")


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
        "mem-mesh-post-tool-use.sh",
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


def _uninstall_antigravity_from(
    label: str, hooks_dir: Path, settings_path: Path
) -> None:
    """Remove mem-mesh hooks from an Antigravity-style hooks.json client."""
    print(f"[{label}] Removing hook scripts...")
    for name in ("mem-mesh-stop.sh", "mem-mesh-post-tool-use.sh"):
        script = hooks_dir / name
        if script.exists():
            script.unlink()
            print(f"  removed {script}")

    print(f"[{label}] Removing mem-mesh hooks from hooks.json...")
    _remove_antigravity_mem_mesh_hooks(settings_path)

    print(f"[{label}] Done.")


def _uninstall_antigravity() -> None:
    """Remove mem-mesh hooks for Antigravity IDE."""
    _uninstall_antigravity_from(
        "antigravity", ANTIGRAVITY_HOOKS_DIR, ANTIGRAVITY_HOOKS_FILE
    )


def _uninstall_agy() -> None:
    """Remove mem-mesh hooks for Antigravity CLI (`agy`)."""
    _uninstall_antigravity_from("agy", AGY_HOOKS_DIR, AGY_HOOKS_FILE)


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

    print("[cursor] Removing mem-mesh hooks from hooks.json...")
    _remove_mem_mesh_hooks_from_json(CURSOR_SETTINGS)

    print("[cursor] Done.")


def _uninstall_codex() -> None:
    """Remove mem-mesh hooks and MCP config for Codex."""
    print("[codex] Removing hook scripts...")
    for name in (
        "mem-mesh-session-start.sh",
        "mem-mesh-stop.sh",
        "mem-mesh-stop-decide.sh",
        "mem-mesh-stop-enhanced.sh",
        "mem-mesh-user-prompt-submit.sh",
        "mem-mesh-post-tool-use.sh",
        "mem-mesh-subagent-start.sh",
        "mem-mesh-subagent-stop.sh",
        "mem-mesh-precompact.sh",
    ):
        script = CODEX_HOOKS_DIR / name
        if script.exists():
            script.unlink()
            print(f"  removed {script}")

    print("[codex] Removing mem-mesh hooks from hooks.json...")
    _remove_mem_mesh_hooks_from_json(CODEX_HOOKS_FILE)

    print("[codex] Removing mem-mesh MCP server from config.toml...")
    remove_codex_mcp_config(CODEX_CONFIG)

    print("[codex] Done.")


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
    has_prompt_stop = _has_prompt_stop_hook(settings_path) if settings_path else False

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

    if target in ("claude", "all"):
        _sync_claude_rules(project_root, project_id)

    if target in ("kiro", "all"):
        _sync_kiro_hooks(project_root, project_id)

    if target in ("cursor", "all"):
        _sync_cursor_hooks(project_root, project_id)

    print("\nSync complete.")


def cmd_rules(project_id: str = "mem-mesh", output_format: str = "plain") -> None:
    """Print hook rules to stdout without modifying files."""
    project_id = _safe_project_id(project_id)
    if output_format == "plain":
        print(render_rules_text(project_id))
        return
    if output_format == "claude":
        print(render_claude_project_rules(project_id))
        return
    raise ValueError(f"unknown rules format: {output_format}")


_CLAUDE_RULES_BEGIN_RE = re.compile(
    r"<!-- mem-mesh-hooks:BEGIN v\d+ -->.*?<!-- mem-mesh-hooks:END v\d+ -->",
    re.DOTALL,
)


def _sync_claude_rules(project_root: Path, project_id: str) -> None:
    """Create or refresh the managed mem-mesh block in project CLAUDE.md.

    Idempotent: when the managed block already renders identically (same
    prompt version, same project id), the file is left untouched — repeated
    ``sync-project`` runs (setup scripts, uvx one-liners) become no-ops.
    """
    claude_path = project_root / "CLAUDE.md"
    block = render_claude_project_rules(project_id)
    old_version: Optional[str] = None
    if claude_path.exists():
        existing = claude_path.read_text(encoding="utf-8")
        version_match = re.search(r"<!-- mem-mesh-hooks:BEGIN v(\d+) -->", existing)
        old_version = version_match.group(1) if version_match else None
        if _CLAUDE_RULES_BEGIN_RE.search(existing):
            content = _CLAUDE_RULES_BEGIN_RE.sub(block, existing)
        else:
            content = existing.rstrip() + "\n\n---\n\n" + block + "\n"
        if content == existing:
            print(
                f"[claude] CLAUDE.md managed rules already at v{PROMPT_VERSION}"
                " — skipped (no changes)"
            )
            return
    else:
        content = "# Claude Project Rules\n\n" + block + "\n"
    claude_path.write_text(content, encoding="utf-8")
    transition = (
        f"v{old_version} -> v{PROMPT_VERSION}"
        if old_version and old_version != str(PROMPT_VERSION)
        else f"v{PROMPT_VERSION}"
    )
    print(f"[claude] Regenerated project CLAUDE.md managed rules ({transition})")
    print(f"  -> {claude_path}")


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
        rendered = json.dumps(hook_data, indent=2, ensure_ascii=False) + "\n"
        if _file_unchanged(hook_file, rendered):
            print(f"  -> {hook_file} (unchanged, skipped)")
            continue
        hook_file.write_text(rendered, encoding="utf-8")
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
        _render_local_template(
            LOCAL_USER_PROMPT_SUBMIT_HOOK_TEMPLATE, str(project_root)
        )
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
        if _write_script(cursor_dir / name, content):
            print(f"  -> {cursor_dir / name}")
        else:
            print(f"  -> {cursor_dir / name} (unchanged, skipped)")

    template_path = project_root / ".cursor" / "hooks.mem-mesh.example.json"
    template_data = _build_cursor_hooks_settings(cursor_dir, scope="project")
    rendered_template = (
        json.dumps(template_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )
    if _file_unchanged(template_path, rendered_template):
        print(f"  -> {template_path} (unchanged, skipped)")
    else:
        template_path.write_text(rendered_template, encoding="utf-8")
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
    *,
    force: bool = False,
    scope: str = "global",
    dir_path: str = "",
) -> None:
    """Install hooks for the specified target.

    ``scope`` selects the install root. ``global`` (the default) installs under
    the user's home (``HOME/.claude`` etc.); ``project`` installs under a target
    project directory (``dir_path`` or the current working directory when empty).
    """
    # Project scope resolves a base directory the install helpers write under;
    # global scope leaves base_dir as None so the legacy HOME paths are used.
    base_dir: Optional[Path] = None
    if scope == "project":
        base_dir = Path(dir_path or os.getcwd()).expanduser().resolve()

    # Validate the API URL up front (local mode renders a path, not a URL).
    # An invalid/malicious URL would otherwise be interpolated into the hook
    # shell scripts; reject it here with a clear message instead of failing
    # deep inside template rendering.
    if mode != "local":
        try:
            _shell_safe_url(url)
        except ValueError as exc:
            print(f"ERROR: invalid --url: {exc}", file=sys.stderr)
            raise SystemExit(2)

    # http mode produces native HTTP hooks, which Claude Code refuses to call
    # when the URL resolves to a private/link-local/CGNAT address (e.g. a
    # Tailscale/VPN/LAN server). Detect that up front and downgrade to api
    # (command + curl hooks), which has no such restriction.
    if mode == "http":
        block_reason = check_http_hook_url(url)
        if block_reason:
            print(f"WARNING: http mode unavailable for this URL — {block_reason}")
            print("  Falling back to 'api' mode (command + curl hooks).\n")
            mode = "api"

    if mode == "local":
        resolved = path or str(Path(__file__).resolve().parent.parent.parent)
        print(f"Installing mem-mesh hooks (mode: local, path: {resolved})")
    else:
        # http mode shares api's url-based config; Claude Code gets native
        # HTTP hooks while Kiro/Cursor fall back to command hooks.
        resolved = ""
        print(f"Installing mem-mesh hooks (mode: {mode}, url: {url})")
        # Materialize the URL so every tool's hook has a shared
        # ~/.mem-mesh/api_url fallback/cache. Local mode renders a path, not a
        # URL, so it is skipped.
        _ensure_api_url(url)

        # Ensure the materialized token file exists when the server enforces
        # auth, so every client has a credential to present: .sh hooks
        # (Kiro/Cursor) fall back to ~/.mem-mesh/hook_token, and native HTTP
        # hooks/MCP get the token baked into their config as a literal bearer
        # header. Without this, installing only Kiro/Cursor — or any direct
        # cmd_install — against an auth-gated server leaves them 401.
        from app.cli.hooks.status import server_enforces_auth

        if server_enforces_auth(url):
            _ensure_hook_token()
            print(
                f"  hook auth: token at {HOOK_TOKEN_FILE} — baked into each"
                " tool config as a literal bearer header\n"
            )

    if base_dir is not None:
        print(f"Scope: project ({base_dir})")
    print(f"Prompt version: {PROMPT_VERSION} | Profile: {profile}\n")

    try:
        if target in ("claude", "all"):
            _install_claude(
                url, mode, resolved, profile, force=force, base_dir=base_dir
            )
            print()
        if target in ("kiro", "all"):
            _install_kiro(url, mode, resolved, base_dir=base_dir)
            print()
        if target in ("cursor", "all"):
            _install_cursor(
                url, mode, resolved, profile, force=force, base_dir=base_dir
            )
            print()
        if target in ("codex", "all"):
            _install_codex(url, mode, resolved, profile, force=force, base_dir=base_dir)
            print()
        if target in ("antigravity", "all"):
            _install_antigravity(url, mode, resolved, force=force, base_dir=base_dir)
            print()
        if target in ("agy", "all"):
            _install_agy(url, mode, resolved, force=force, base_dir=base_dir)
            print()
    except MalformedSettingsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
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
    if target in ("codex", "all"):
        _uninstall_codex()
        print()
    if target in ("antigravity", "all"):
        _uninstall_antigravity()
        print()
    if target in ("agy", "all"):
        _uninstall_agy()
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
    targets = [
        "Claude Code",
        "Kiro",
        "Cursor",
        "Codex",
        "Antigravity IDE",
        "agy CLI",
        "All",
    ]
    target_keys = ["claude", "kiro", "cursor", "codex", "antigravity", "agy", "all"]
    idx = _prompt_choice("", targets, default=6)
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
    from app.cli.hooks.status import resolve_api_url

    suggested_url, url_source = resolve_api_url()
    print("[3/4] Select storage mode:")
    modes = [
        f"HTTP — Streamable HTTP where supported; command hooks elsewhere ({suggested_url})",
        f"API  — Remote server via command+curl hooks ({suggested_url})",
        "Local — Save directly to local SQLite",
    ]
    mode_keys = ["http", "api", "local"]
    mode_idx = _prompt_choice("", modes, default=0)
    mode = mode_keys[mode_idx]
    print()

    # Step 4: mode-specific config
    url = suggested_url
    mem_path = ""
    if mode in ("api", "http"):
        source_hint = f" (from {url_source})" if url_source != "default" else ""
        print(f"[4/4] API URL [{suggested_url}]{source_hint}:")
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
        description=(
            "Install/uninstall mem-mesh hooks for Claude Code, Kiro, Cursor, "
            "Codex, Antigravity IDE, and agy CLI."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    target_choices = ["claude", "kiro", "cursor", "codex", "antigravity", "agy", "all"]

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
        choices=["api", "local", "http"],
        default="api",
        help=(
            "Storage mode: api (remote server, bash+curl hooks), "
            "local (SQLite direct), or http (native HTTP where supported; "
            "command hooks elsewhere)"
        ),
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
        "--scope",
        choices=["global", "project"],
        default="global",
        help=(
            "Install scope: global (user home — ~/.claude, ~/.kiro, ~/.cursor, "
            "~/.codex, ~/.gemini/antigravity, ~/.gemini/antigravity-cli; default) or project "
            "(<dir>/.claude, <dir>/.kiro, <dir>/.cursor, <dir>/.codex, "
            "<dir>/.agents)"
        ),
    )
    install_parser.add_argument(
        "--dir",
        default="",
        help=(
            "Target project directory for '--scope project' "
            "(default: current working directory)"
        ),
    )
    install_parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Run interactive installer wizard",
    )
    install_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite a malformed settings file instead of aborting "
            "(the original is still backed up to <path>.bak)"
        ),
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

    # rules
    rules_parser = subparsers.add_parser(
        "rules",
        help="Print hook rules to stdout for copy/paste",
    )
    rules_parser.add_argument(
        "--project-id",
        default="mem-mesh",
        help="Project ID to embed in the rendered rules (default: mem-mesh)",
    )
    rules_parser.add_argument(
        "--format",
        choices=["plain", "claude"],
        default="plain",
        help="Output format: plain rules or a CLAUDE.md managed block",
    )

    # sync-project
    sync_parser = subparsers.add_parser(
        "sync-project",
        help="Regenerate project-local hooks from shared prompts",
    )
    sync_parser.add_argument(
        "--target",
        choices=["claude", "kiro", "cursor", "all"],
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
        cmd_install(
            args.target,
            args.url,
            args.mode,
            args.path,
            args.profile,
            force=args.force,
            scope=args.scope,
            dir_path=args.dir,
        )
    elif args.command == "uninstall":
        cmd_uninstall(args.target)
    elif args.command == "status":
        cmd_status()
    elif args.command == "doctor":
        from app.cli.hooks.doctor import cmd_doctor

        cmd_doctor()
    elif args.command == "rules":
        cmd_rules(args.project_id, args.format)
    elif args.command == "sync-project":
        cmd_sync_project(args.target, args.project_id)


if __name__ == "__main__":
    main()
