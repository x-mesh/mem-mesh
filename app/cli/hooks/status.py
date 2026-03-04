"""Hook installation status checking and profile detection."""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from app.cli.prompts.behaviors import PROMPT_VERSION
from app.cli.prompts.renderers import extract_prompt_version
from app.cli.hooks.colors import bold, dim, err, header, info, ok, warn
from app.cli.hooks.constants import (
    CLAUDE_HOOKS_DIR,
    CLAUDE_SETTINGS,
    CURSOR_HOOKS_DIR,
    CURSOR_SETTINGS,
    DEFAULT_URL,
    KIRO_HOOKS_DIR,
    KIRO_SETTINGS,
)
from app.cli.hooks.json_ops import _count_mem_mesh_hook_entries


def _colorize_status(status: str) -> str:
    """Apply color to a status string based on its content."""
    if "not installed" in status or "not found" in status or "not configured" in status:
        return err(status)
    if "NOT executable" in status:
        return err(status)
    if "parse error" in status:
        return err(status)
    if "outdated" in status:
        return warn(status)
    if "not set" in status:
        return warn(status)
    if "installed" in status or "configured" in status or "available" in status:
        return ok(status)
    if status == "set":
        return ok(status)
    return status


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
        hooks = data.get("hooks", {})
        if not isinstance(hooks, dict):
            return False
        stop_entries = hooks.get("Stop", [])
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
    1. mem-mesh-stop-enhanced.sh -> "enhanced"
    2. mem-mesh-stop-decide.sh -> "standard"
    3. settings.json has prompt stop hook -> "standard (prompt)"
    4. mem-mesh-stop.sh -> "minimal"
    5. mem-mesh-reflect.sh -> "legacy"
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


def resolve_api_url(baked_url: Optional[str] = None) -> Tuple[str, str]:
    """Resolve the API URL from environment or baked value.

    Returns (url, source) where source describes where the URL came from.
    Priority: MEM_MESH_API_URL env > API_URL env > baked URL > DEFAULT_URL.
    """
    env_url = os.environ.get("MEM_MESH_API_URL")
    if env_url:
        return env_url.rstrip("/"), "MEM_MESH_API_URL env"

    env_url = os.environ.get("API_URL")
    if env_url:
        return env_url.rstrip("/"), "API_URL env"

    if baked_url:
        return baked_url.rstrip("/"), "installed script"

    return DEFAULT_URL.rstrip("/"), "default"


def check_connectivity(url: str, timeout: int = 5) -> Tuple[bool, str]:
    """Check API connectivity by hitting /health endpoint.

    Returns (reachable, message).
    """
    health_url = f"{url.rstrip('/')}/health"
    try:
        start = time.monotonic()
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return True, f"reachable ({resp.status}, {elapsed_ms}ms)"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        reason = str(e.reason) if hasattr(e, "reason") else str(e)
        return False, f"unreachable: {reason}"
    except Exception as e:
        return False, f"error: {e}"


def cmd_status() -> None:
    """Print installation status with color output."""
    from app.cli.hooks.sync import _find_project_root

    print(header("=== mem-mesh hooks status ==="))
    print(f"Prompt version: {bold(str(PROMPT_VERSION))} (current)\n")

    # Claude Code
    print(header("[Claude Code]"))
    session_start = CLAUDE_HOOKS_DIR / "mem-mesh-session-start.sh"
    stop = CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh"
    stop_decide = CLAUDE_HOOKS_DIR / "mem-mesh-stop-decide.sh"
    enhanced_stop = CLAUDE_HOOKS_DIR / "mem-mesh-stop-enhanced.sh"
    reflect = CLAUDE_HOOKS_DIR / "mem-mesh-reflect.sh"
    print(f"  session hook:   {_colorize_status(_check_script_version(session_start))}")
    if enhanced_stop.exists():
        print(f"  stop hook:      {_colorize_status(_check_script_version(enhanced_stop))} {dim('(enhanced)')}")
    elif stop_decide.exists():
        print(f"  stop hook:      {_colorize_status(_check_script_version(stop_decide))} {dim('(standard)')}")
    elif _has_prompt_stop_hook(CLAUDE_SETTINGS):
        print(f"  stop hook:      {ok(f'native prompt (v{PROMPT_VERSION})')}")
    else:
        print(f"  stop hook:      {_colorize_status(_check_script_version(stop))}")
    session_end = CLAUDE_HOOKS_DIR / "mem-mesh-session-end.sh"
    precompact = CLAUDE_HOOKS_DIR / "mem-mesh-precompact.sh"
    user_prompt_submit = CLAUDE_HOOKS_DIR / "mem-mesh-user-prompt-submit.sh"
    subagent_start = CLAUDE_HOOKS_DIR / "mem-mesh-subagent-start.sh"
    subagent_stop = CLAUDE_HOOKS_DIR / "mem-mesh-subagent-stop.sh"
    task_completed = CLAUDE_HOOKS_DIR / "mem-mesh-task-completed.sh"
    print(f"  session-end:    {_colorize_status(_check_script_version(session_end))}")
    print(f"  precompact:     {_colorize_status(_check_script_version(precompact))}")
    print(f"  prompt-submit:  {_colorize_status(_check_script_version(user_prompt_submit))}")
    print(f"  subagent-start: {_colorize_status(_check_script_version(subagent_start))}")
    print(f"  subagent-stop:  {_colorize_status(_check_script_version(subagent_stop))}")
    print(f"  task-completed: {_colorize_status(_check_script_version(task_completed))}")
    print(f"  reflect hook:   {_colorize_status(_check_script_version(reflect))} {dim('(legacy)')}")

    detected = _detect_profile(CLAUDE_HOOKS_DIR, CLAUDE_SETTINGS)
    print(f"  profile:        {bold(detected)}")

    baked_url = (
        _extract_url_from_script(session_start)
        or _extract_url_from_script(stop)
    )
    if baked_url:
        print(f"  target URL:     {info(baked_url)}")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    print(f"  ANTHROPIC_API_KEY: {_colorize_status('set' if api_key else 'not set')}")

    if CLAUDE_SETTINGS.exists():
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
            has_hooks = "hooks" in settings
            status_text = "configured" if has_hooks else "not configured"
            print(f"  settings.json hooks: {_colorize_status(status_text)}")
        except (json.JSONDecodeError, OSError):
            print(f"  settings.json: {err('parse error')}")
    else:
        print(f"  settings.json: {err('not found')}")

    print()

    # Kiro
    print(header("[Kiro]"))
    kiro_stop = KIRO_HOOKS_DIR / "mem-mesh-stop.sh"
    print(f"  stop hook:   {_colorize_status(_check_script_version(kiro_stop))}")

    kiro_url = _extract_url_from_script(kiro_stop)
    if kiro_url:
        print(f"  target URL:  {info(kiro_url)}")

    if KIRO_SETTINGS.exists():
        try:
            data = json.loads(KIRO_SETTINGS.read_text(encoding="utf-8"))
            mem_hooks = [
                h
                for h in data.get("hooks", [])
                if h.get("name", "").startswith("mem-mesh:")
            ]
            print(f"  hooks.json:  {ok(f'{len(mem_hooks)} mem-mesh hook(s) registered')}")
        except (json.JSONDecodeError, OSError):
            print(f"  hooks.json: {err('parse error')}")
    else:
        print(f"  hooks.json: {dim('not found')}")

    print()

    # Cursor
    print(header("[Cursor]"))
    cursor_session = CURSOR_HOOKS_DIR / "mem-mesh-session-start.sh"
    cursor_stop = CURSOR_HOOKS_DIR / "mem-mesh-stop.sh"
    cursor_session_end = CURSOR_HOOKS_DIR / "mem-mesh-session-end.sh"
    print(f"  session hook: {_colorize_status(_check_script_version(cursor_session))}")
    print(f"  stop hook:    {_colorize_status(_check_script_version(cursor_stop))}")
    print(f"  session-end:  {_colorize_status(_check_script_version(cursor_session_end))}")

    cursor_url = _extract_url_from_script(cursor_session) or _extract_url_from_script(
        cursor_stop
    )
    if cursor_url:
        print(f"  target URL:   {info(cursor_url)}")

    if CURSOR_SETTINGS.exists():
        try:
            settings = json.loads(CURSOR_SETTINGS.read_text(encoding="utf-8"))
            has_hooks = "hooks" in settings
            status_text = "configured" if has_hooks else "not configured"
            print(f"  hooks.json:   {_colorize_status(status_text)}")
        except (json.JSONDecodeError, OSError):
            print(f"  hooks.json:   {err('parse error')}")
    else:
        print(f"  hooks.json:   {dim('not found')}")

    # Project-local hooks
    project_root = _find_project_root()
    if project_root:
        print()
        print(header("[Project Local]"))

        # Kiro hooks
        kiro_dir = project_root / ".kiro" / "hooks"
        for name in (
            "auto-save-conversations",
            "auto-create-pin-on-task",
            "load-project-context",
        ):
            hook_file = kiro_dir / f"{name}.kiro.hook"
            print(f"  {name}: {_colorize_status(_check_kiro_hook_version(hook_file))}")

        # Cursor hooks
        cursor_dir = project_root / ".cursor" / "hooks"
        for name in (
            "mem-mesh-session-start.sh",
            "mem-mesh-session-end.sh",
            "mem-mesh-auto-save.sh",
        ):
            script = cursor_dir / name
            print(f"  {name}: {_colorize_status(_check_script_version(script))}")
        cursor_settings = project_root / ".cursor" / "hooks.json"
        cursor_template = project_root / ".cursor" / "hooks.mem-mesh.example.json"
        if cursor_settings.exists():
            count = _count_mem_mesh_hook_entries(cursor_settings)
            print(f"  hooks.json: {ok(f'configured (mem-mesh entries: {count})')}")
        else:
            print(f"  hooks.json: {dim('not found')}")
        if cursor_template.exists():
            print(f"  hooks.mem-mesh.example.json: {ok('available')}")
        else:
            print(f"  hooks.mem-mesh.example.json: {dim('not found')}")

    # Connectivity check
    print()
    print(header("[Connectivity]"))
    url, source = resolve_api_url(baked_url)
    print(f"  API URL:        {info(url)} {dim(f'(from {source})')}")
    reachable, message = check_connectivity(url)
    if reachable:
        print(f"  Health check:   {ok(message)}")
    else:
        print(f"  Health check:   {err(message)}")

    print()
    print(dim("Run 'mem-mesh-hooks install --target all' to update global hooks."))
    print(dim("Run 'mem-mesh-hooks sync-project' to update project-local hooks."))
    print(dim("Run 'mem-mesh-hooks doctor' for full diagnostics."))
