"""Hook installation status checking and profile detection."""

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from app.cli.codex_config import (
    CODEX_CONFIG,
    CODEX_HOOKS_DIR,
    CODEX_HOOKS_FILE,
    codex_config_has_mem_mesh,
)
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
from app.cli.prompts.behaviors import PROMPT_VERSION
from app.cli.prompts.renderers import extract_prompt_version


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
    """Extract the baked default URL from an installed script.

    Supports the current config-file (no-env) form plus the older
    env-fallback patterns so a partially-migrated install still reports:
      - Current: API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo https://example.com)"
      - Legacy:  ${MEM_MESH_API_URL:-https://example.com}
      - Legacy:  ${MEM_MESH_API_URL:-$(cat ~/.mem-mesh/api_url 2>/dev/null || echo https://example.com)}
    """
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        # Match the API_URL assignment (no-env form) or any legacy
        # env-default form. Gate on `|| echo ` / `MEM_MESH_API_URL:-`
        # rather than the env var name so the no-env render still parses.
        if not (
            stripped.startswith("API_URL=")
            or "MEM_MESH_API_URL:-" in line
        ):
            continue
        # Config-file form: extract the URL after the `|| echo ` fallback.
        echo_idx = line.find("|| echo ")
        if echo_idx >= 0:
            after = line[echo_idx + len("|| echo ") :]
            for delim in (")", "}", " ", '"'):
                idx = after.find(delim)
                if idx >= 0:
                    return after[:idx].strip()
            return after.strip()
        # Legacy env-default pattern: ${MEM_MESH_API_URL:-https://example.com}
        if "MEM_MESH_API_URL:-" in line:
            start = line.find(":-") + 2
            end = line.find("}", start)
            if start > 1 and end > start:
                return line[start:end].strip('"').strip("'")
    return None


def _read_config_file_url() -> Optional[str]:
    """Read API URL from ~/.mem-mesh/api_url config file."""
    try:
        path = Path.home() / ".mem-mesh" / "api_url"
        if path.is_file():
            url = path.read_text(encoding="utf-8").strip()
            return url or None
    except OSError:
        pass
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


def resolve_api_url(baked_url: Optional[str] = None) -> Tuple[str, str]:
    """Resolve the API URL from environment, config file, or baked value.

    Returns (url, source) where source describes where the URL came from.
    Priority: MEM_MESH_API_URL env > API_URL env > ~/.mem-mesh/api_url > baked URL > DEFAULT_URL.
    """
    env_url = os.environ.get("MEM_MESH_API_URL")
    if env_url:
        return env_url.rstrip("/"), "MEM_MESH_API_URL env"

    env_url = os.environ.get("API_URL")
    if env_url:
        return env_url.rstrip("/"), "API_URL env"

    file_url = _read_config_file_url()
    if file_url:
        return file_url.rstrip("/"), "~/.mem-mesh/api_url"

    if baked_url:
        return baked_url.rstrip("/"), "installed script"

    return DEFAULT_URL.rstrip("/"), "default"


@dataclass
class ApiProbe:
    """3-state result of probing the API ``/health`` endpoint.

    Distinguishes a server that *responded* with an auth challenge
    (``auth_required`` — e.g. behind a reverse proxy that gates ``/health``)
    from one that could not be reached at all (``unreachable`` — connection
    refused / DNS / timeout). The old 2-state ``check_connectivity`` collapsed
    both into "not reachable", which made an auth-gated but running deployment
    look like *no server* and pushed onboarding toward reinstall/uvx fallbacks.
    """

    state: str  # "ok" | "auth_required" | "unreachable"
    status: Optional[int]
    message: str
    latency_ms: Optional[int] = None

    @property
    def ok(self) -> bool:
        """True only for a 2xx /health response."""
        return self.state == "ok"

    @property
    def alive(self) -> bool:
        """True when the server responded at all (2xx or an auth challenge)."""
        return self.state in ("ok", "auth_required")

    @property
    def auth_required(self) -> bool:
        """True when /health answered with 401/403/407 (server up, auth gated)."""
        return self.state == "auth_required"


def probe_api(url: str, timeout: int = 5) -> ApiProbe:
    """Probe ``{url}/health`` and classify the outcome into 3 states.

    - 2xx  -> ``ok``           (reachable)
    - 401/403/407 -> ``auth_required`` (server alive, gated by auth — e.g. proxy)
    - connection failure / other HTTP status -> ``unreachable``
    """
    health_url = f"{url.rstrip('/')}/health"
    start = time.monotonic()
    try:
        # Some reverse proxies (e.g. Cloudflare) block the default urllib UA
        # ("Python-urllib") as a bot, making doctor falsely report 403 while the
        # real curl-based hooks pass. Send an explicit UA so the probe matches.
        req = urllib.request.Request(
            health_url, method="GET", headers={"User-Agent": "mem-mesh-cli"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return ApiProbe(
                "ok",
                resp.status,
                f"reachable ({resp.status}, {elapsed_ms}ms)",
                elapsed_ms,
            )
    except urllib.error.HTTPError as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        if e.code in (401, 403, 407):
            return ApiProbe(
                "auth_required",
                e.code,
                f"alive but authentication required (HTTP {e.code})",
                elapsed_ms,
            )
        # Any other HTTP status (404/5xx) means the server answered but /health
        # is misbehaving — treat as not usable, matching the old behavior.
        return ApiProbe("unreachable", e.code, f"HTTP {e.code}", elapsed_ms)
    except urllib.error.URLError as e:
        reason = str(e.reason) if hasattr(e, "reason") else str(e)
        return ApiProbe("unreachable", None, f"unreachable: {reason}")
    except Exception as e:
        return ApiProbe("unreachable", None, f"error: {e}")


def check_connectivity(url: str, timeout: int = 5) -> Tuple[bool, str]:
    """Check API connectivity by hitting /health endpoint.

    Returns (reachable, message). Thin wrapper over :func:`probe_api` that
    preserves the historical 2-state contract: ``reachable`` is True only for a
    2xx response, and the message keeps the legacy ``HTTP {code}`` /
    ``unreachable: ...`` wording so existing callers and tests are unaffected.
    """
    probe = probe_api(url, timeout=timeout)
    if probe.ok:
        return True, probe.message
    if probe.auth_required:
        # Legacy callers expect the bare "HTTP {code}" form here.
        return False, f"HTTP {probe.status}"
    return False, probe.message


def server_enforces_auth(url: str) -> bool:
    """Whether the server enforces MCP / OAuth auth, read authoritatively.

    Uses ``GET /api/security/overview`` (no auth gate, secrets never returned),
    which reports the *runtime* toggle even when ``/health`` is public — so a
    server with ``auth_enabled``/``mcp_auth_enabled`` on is detected, where
    :attr:`ApiProbe.auth_required` (which only fires on a gated /health) misses
    it. Returns ``False`` on any error or an older server without the endpoint.

    Shared by onboarding (MCP auth header + token bridge) and ``cmd_install``
    (token-file bootstrap) so both entry points gate on the same signal.
    """
    import json

    from app.cli.hooks.doctor import _http

    try:
        status, body = _http("GET", f"{url.rstrip('/')}/api/security/overview")
        if status != 200:
            return False
        data = json.loads(body or b"{}")
        mcp = data.get("mcp_auth") or {}
        return bool(mcp.get("mcp_auth_enabled") or mcp.get("oauth_auth_enabled"))
    except Exception:
        return False


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
        print(
            f"  stop hook:      {_colorize_status(_check_script_version(enhanced_stop))} {dim('(enhanced)')}"
        )
    elif stop_decide.exists():
        print(
            f"  stop hook:      {_colorize_status(_check_script_version(stop_decide))} {dim('(standard)')}"
        )
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
    print(
        f"  prompt-submit:  {_colorize_status(_check_script_version(user_prompt_submit))}"
    )
    print(
        f"  subagent-start: {_colorize_status(_check_script_version(subagent_start))}"
    )
    print(f"  subagent-stop:  {_colorize_status(_check_script_version(subagent_stop))}")
    print(
        f"  task-completed: {_colorize_status(_check_script_version(task_completed))}"
    )
    print(
        f"  reflect hook:   {_colorize_status(_check_script_version(reflect))} {dim('(legacy)')}"
    )

    detected = _detect_profile(CLAUDE_HOOKS_DIR, CLAUDE_SETTINGS)
    print(f"  profile:        {bold(detected)}")

    baked_url = _extract_url_from_script(session_start) or _extract_url_from_script(
        stop
    )
    if baked_url:
        print(f"  target URL:     {info(baked_url)}")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    print(f"  ANTHROPIC_API_KEY: {_colorize_status('set' if api_key else 'not set')}")

    # Hook auth token (Option 2). The token lives in ~/.mem-mesh/hook_token (file
    # canonical) and is baked as a literal Bearer header into each tool's MCP /
    # HTTP hook config at install time — no shell export is required — so we only
    # report present/absent. The raw value is never printed.
    try:
        from app.core.config import resolve_hook_token

        hook_token = resolve_hook_token()
    except Exception:
        hook_token = os.environ.get("MEM_MESH_HOOK_TOKEN")
    if hook_token:
        print(
            f"  hook token:        {ok('set')} "
            f"{dim('(baked as a literal bearer token into each tool config)')}"
        )
    else:
        print(f"  hook token:        {_colorize_status('not set')}")

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
            print(
                f"  hooks.json:  {ok(f'{len(mem_hooks)} mem-mesh hook(s) registered')}"
            )
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
    cursor_before_submit = CURSOR_HOOKS_DIR / "mem-mesh-before-submit-prompt.sh"
    cursor_precompact = CURSOR_HOOKS_DIR / "mem-mesh-precompact.sh"
    cursor_subagent_start = CURSOR_HOOKS_DIR / "mem-mesh-subagent-start.sh"
    cursor_subagent_stop = CURSOR_HOOKS_DIR / "mem-mesh-subagent-stop.sh"
    print(f"  session hook: {_colorize_status(_check_script_version(cursor_session))}")
    print(f"  stop hook:    {_colorize_status(_check_script_version(cursor_stop))}")
    print(
        f"  session-end:  {_colorize_status(_check_script_version(cursor_session_end))}"
    )
    print(
        f"  beforeSubmit: {_colorize_status(_check_script_version(cursor_before_submit))}"
    )
    print(
        f"  precompact:   {_colorize_status(_check_script_version(cursor_precompact))}"
    )
    print(
        f"  subagentStart:{_colorize_status(_check_script_version(cursor_subagent_start))}"
    )
    print(
        f"  subagentStop: {_colorize_status(_check_script_version(cursor_subagent_stop))}"
    )

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

    print()

    # Codex
    print(header("[Codex]"))
    codex_session = CODEX_HOOKS_DIR / "mem-mesh-session-start.sh"
    codex_stop = CODEX_HOOKS_DIR / "mem-mesh-stop-decide.sh"
    codex_stop_simple = CODEX_HOOKS_DIR / "mem-mesh-stop.sh"
    codex_precompact = CODEX_HOOKS_DIR / "mem-mesh-precompact.sh"
    print(f"  session hook: {_colorize_status(_check_script_version(codex_session))}")
    if codex_stop.exists():
        print(f"  stop hook:    {_colorize_status(_check_script_version(codex_stop))}")
    else:
        print(
            f"  stop hook:    {_colorize_status(_check_script_version(codex_stop_simple))}"
        )
    print(
        f"  precompact:   {_colorize_status(_check_script_version(codex_precompact))}"
    )
    if CODEX_HOOKS_FILE.exists():
        try:
            count = _count_mem_mesh_hook_entries(CODEX_HOOKS_FILE)
            print(f"  hooks.json:   {ok(f'configured (mem-mesh entries: {count})')}")
        except (json.JSONDecodeError, OSError):
            print(f"  hooks.json:   {err('parse error')}")
    else:
        print(f"  hooks.json:   {dim('not found')}")
    if codex_config_has_mem_mesh(CODEX_CONFIG):
        print(f"  MCP config:   {ok('configured')}")
    elif CODEX_CONFIG.exists():
        print(f"  MCP config:   {warn('config exists, mem-mesh missing')}")
    else:
        print(f"  MCP config:   {dim('not found')}")

    # Project-local hooks
    project_root = _find_project_root()
    if project_root:
        print()
        print(header("[Project Local]"))

        # Kiro hooks (self-contained .kiro.hook files — always active if present)
        kiro_dir = project_root / ".kiro" / "hooks"
        for name in (
            "auto-save-conversations",
            "auto-create-pin-on-task",
            "load-project-context",
        ):
            hook_file = kiro_dir / f"{name}.kiro.hook"
            print(f"  {name}: {_colorize_status(_check_kiro_hook_version(hook_file))}")

        # Claude Code project-local hooks
        claude_local_dir = project_root / ".claude" / "hooks"
        claude_local_settings = project_root / ".claude" / "settings.json"
        claude_local_registered = False
        if claude_local_settings.exists():
            try:
                data = json.loads(claude_local_settings.read_text(encoding="utf-8"))
                claude_local_registered = bool(data.get("hooks"))
            except (json.JSONDecodeError, OSError):
                pass
        if claude_local_dir.exists():
            claude_scripts = sorted(claude_local_dir.glob("mem-mesh-*.sh"))
            for script in claude_scripts:
                status_str = _check_script_version(script)
                inactive = (
                    ""
                    if claude_local_registered
                    else dim(" (inactive — not in .claude/settings.json)")
                )
                print(f"  {script.name}: {_colorize_status(status_str)}{inactive}")

        # Cursor project-local hooks
        cursor_dir = project_root / ".cursor" / "hooks"
        cursor_settings = project_root / ".cursor" / "hooks.json"
        cursor_registered = (
            cursor_settings.exists()
            and _count_mem_mesh_hook_entries(cursor_settings) > 0
        )
        for name in (
            "mem-mesh-session-start.sh",
            "mem-mesh-session-end.sh",
            "mem-mesh-auto-save.sh",
            "mem-mesh-before-submit-prompt.sh",
            "mem-mesh-precompact.sh",
            "mem-mesh-subagent-start.sh",
            "mem-mesh-subagent-stop.sh",
        ):
            script = cursor_dir / name
            status_str = _check_script_version(script)
            if script.exists() and not cursor_registered:
                print(
                    f"  {name}: {_colorize_status(status_str)}{dim(' (inactive — not in hooks.json)')}"
                )
            else:
                print(f"  {name}: {_colorize_status(status_str)}")
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
