"""Hook diagnostics and health checks."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.cli.codex_config import (
    CODEX_CONFIG,
    CODEX_HOOKS_DIR,
    CODEX_HOOKS_FILE,
    codex_config_has_mem_mesh,
)
from app.cli.hooks.colors import bold, dim, err, header, ok, warn
from app.cli.hooks.constants import (
    AGY_HOOKS_DIR,
    AGY_HOOKS_FILE,
    ANTIGRAVITY_HOOKS_DIR,
    ANTIGRAVITY_HOOKS_FILE,
    CLAUDE_HOOKS_DIR,
    CLAUDE_SETTINGS,
    CURSOR_HOOKS_DIR,
    CURSOR_SETTINGS,
    KIRO_CLI_AGENT,
    KIRO_HOOKS_DIR,
    KIRO_SCRIPTS_DIR,
    KIRO_SETTINGS,
)
from app.cli.hooks.json_ops import _is_mem_mesh_entry, _is_mem_mesh_hook
from app.cli.hooks.netcheck import check_http_hook_url
from app.cli.hooks.status import (
    _count_antigravity_mem_mesh_entries,
    _detect_profile,
    _extract_url_from_script,
    check_connectivity,
    cmd_status,
    resolve_api_url,
)

_RUNTIME_TRACE_STALE_SECONDS = 24 * 60 * 60


def _check_permissions(hooks_dir: Path) -> List[str]:
    """Check that all mem-mesh scripts are executable."""
    issues: List[str] = []
    if not hooks_dir.exists():
        return issues
    for script in sorted(hooks_dir.glob("mem-mesh-*.sh")):
        if not os.access(script, os.X_OK):
            issues.append(f"{script.name} is not executable")
    return issues


def _check_settings_json(settings_path: Path, label: str) -> List[str]:
    """Validate settings.json structure."""
    issues: List[str] = []
    if not settings_path.exists():
        return issues
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        issues.append(f"{label} settings.json: invalid JSON ({e})")
        return issues
    except OSError as e:
        issues.append(f"{label} settings.json: read error ({e})")
        return issues

    hooks = data.get("hooks", {})
    if not hooks:
        issues.append(f"{label} settings.json: no hooks section")
        return issues

    mem_mesh_count = 0
    if isinstance(hooks, dict):
        # Claude/Cursor:
        # - nested: {"EventName": [{"hooks": [{"command": "..."}]}]}
        # - flat:   {"eventName": [{"type":"command","command":"..."}]}
        for _event, entries in hooks.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict) and _is_mem_mesh_entry(entry):
                    mem_mesh_count += 1
    elif isinstance(hooks, list):
        # Kiro: [{"name": "...", "command": "..."}]
        for entry in hooks:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name", "")
            cmd = entry.get("command", "")
            if "mem-mesh" in name or "mem-mesh" in cmd:
                mem_mesh_count += 1
    if mem_mesh_count == 0:
        issues.append(f"{label}: no mem-mesh hooks registered")

    if label == "Cursor" and isinstance(hooks, dict):
        required_events = {
            "sessionStart",
            "beforeSubmitPrompt",
            "preCompact",
            "subagentStart",
            "subagentStop",
            "stop",
            "sessionEnd",
        }
        missing = sorted(required_events - set(hooks.keys()))
        if missing:
            issues.append(
                f"{label}: missing required hook events ({', '.join(missing)})"
            )

    return issues


def _codex_expected_events(hooks_dir: Path) -> List[str]:
    """Return Codex events that should be registered for installed scripts.

    Codex hook breakage often leaves scripts on disk while ``hooks.json`` is
    overwritten by another tool. Use the scripts as the install intent, then
    require matching active registrations.
    """
    expected = ["SessionStart", "Stop", "PreCompact"]
    if (hooks_dir / "mem-mesh-user-prompt-submit.sh").exists():
        expected.append("UserPromptSubmit")
    if (hooks_dir / "mem-mesh-post-tool-use.sh").exists():
        expected.append("PostToolUse")
    if (hooks_dir / "mem-mesh-subagent-start.sh").exists():
        expected.append("SubagentStart")
    if (hooks_dir / "mem-mesh-subagent-stop.sh").exists():
        expected.append("SubagentStop")
    return expected


def _codex_mem_mesh_events(hooks: object) -> List[str]:
    if not isinstance(hooks, dict):
        return []
    events: List[str] = []
    for event_name, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        if any(
            isinstance(entry, dict) and _is_mem_mesh_entry(entry) for entry in entries
        ):
            events.append(str(event_name))
    return sorted(events)


def _check_codex_hooks_json(settings_path: Path, hooks_dir: Path) -> List[str]:
    """Validate Codex has active mem-mesh hook entries for installed scripts."""
    issues: List[str] = []
    if not settings_path.exists():
        if any(hooks_dir.glob("mem-mesh-*.sh")):
            issues.append("Codex hooks.json: missing while mem-mesh scripts exist")
        return issues

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        issues.append(f"Codex hooks.json: invalid JSON ({e})")
        return issues
    except OSError as e:
        issues.append(f"Codex hooks.json: read error ({e})")
        return issues

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict) or not hooks:
        issues.append("Codex hooks.json: no hooks section")
        return issues

    registered_events = _codex_mem_mesh_events(hooks)
    if not registered_events:
        issues.append(
            "Codex: no mem-mesh hooks registered in hooks.json "
            "(scripts alone are inactive)"
        )
        return issues

    expected_events = _codex_expected_events(hooks_dir)
    missing = sorted(set(expected_events) - set(registered_events))
    if missing:
        issues.append(
            "Codex: missing mem-mesh hook registrations for " f"{', '.join(missing)}"
        )

    for event_name in registered_events:
        entries = hooks.get(event_name, [])
        count = 0
        missing_scripts: List[str] = []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks", []):
                if not isinstance(hook, dict) or not _is_mem_mesh_hook(hook):
                    continue
                count += 1
                command = str(hook.get("command", ""))
                if command.startswith("/") and "mem-mesh-" in command:
                    script_path = Path(command.split()[0])
                    if not script_path.exists():
                        missing_scripts.append(str(script_path))
        if count > 1:
            issues.append(f"Codex: duplicate mem-mesh hooks for {event_name}")
        if missing_scripts:
            issues.append(
                f"Codex: registered script path missing for {event_name}: "
                + ", ".join(sorted(set(missing_scripts)))
            )

    return issues


def _check_kiro_native_hook(hooks_dir: Path, scripts_dir: Path) -> List[str]:
    """Validate Kiro uses a native `.kiro.hook` file and no legacy script entry."""
    issues: List[str] = []
    script_path = scripts_dir / "mem-mesh-stop.sh"
    hook_file = hooks_dir / "mem-mesh-save-response.kiro.hook"
    legacy_script = hooks_dir / "mem-mesh-stop.sh"

    if legacy_script.exists():
        issues.append(
            "Kiro: legacy mem-mesh-stop.sh is inside .kiro/hooks; "
            "modern Kiro expects only .kiro.hook files there"
        )

    if script_path.exists() and not hook_file.exists():
        issues.append(
            "Kiro: mem-mesh script exists but native "
            "mem-mesh-save-response.kiro.hook is missing"
        )
        return issues
    if not hook_file.exists():
        return issues

    try:
        data = json.loads(hook_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        issues.append(f"Kiro .kiro.hook: invalid JSON ({e})")
        return issues
    except OSError as e:
        issues.append(f"Kiro .kiro.hook: read error ({e})")
        return issues

    when = data.get("when") if isinstance(data, dict) else None
    then = data.get("then") if isinstance(data, dict) else None
    if not isinstance(when, dict) or when.get("type") != "agentStop":
        issues.append("Kiro .kiro.hook: when.type must be agentStop")
    if not isinstance(then, dict) or then.get("type") != "runCommand":
        issues.append("Kiro .kiro.hook: then.type must be runCommand")
        return issues
    command = str(then.get("command", ""))
    if "mem-mesh-stop.sh" not in command:
        issues.append("Kiro .kiro.hook: command does not point at mem-mesh-stop.sh")
    elif command.startswith("/") and not Path(command.split()[0]).exists():
        issues.append(f"Kiro .kiro.hook: command script missing ({command})")

    return issues


def _check_kiro_cli_agent(agent_path: Path, scripts_dir: Path) -> List[str]:
    """Validate the Kiro CLI custom agent hook used by `kiro-cli chat --agent`."""
    issues: List[str] = []
    script_path = scripts_dir / "mem-mesh-stop.sh"

    if script_path.exists() and not agent_path.exists():
        issues.append(
            "Kiro CLI: mem-mesh script exists but ~/.kiro/agents/mem-mesh.json is missing"
        )
        return issues
    if not agent_path.exists():
        return issues

    try:
        data = json.loads(agent_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        issues.append(f"Kiro CLI agent: invalid JSON ({e})")
        return issues
    except OSError as e:
        issues.append(f"Kiro CLI agent: read error ({e})")
        return issues

    hooks = data.get("hooks") if isinstance(data, dict) else None
    stop_hooks = hooks.get("stop") if isinstance(hooks, dict) else None
    if not isinstance(stop_hooks, list):
        issues.append("Kiro CLI agent: hooks.stop missing")
        return issues
    if not any(
        isinstance(entry, dict) and "mem-mesh-stop.sh" in str(entry.get("command", ""))
        for entry in stop_hooks
    ):
        issues.append("Kiro CLI agent: hooks.stop does not point at mem-mesh-stop.sh")
    return issues


def _check_antigravity_hooks_json(
    settings_path: Path, hooks_dir: Path, *, label: str = "Antigravity"
) -> List[str]:
    """Validate an Antigravity-style client has active mem-mesh hook entries."""
    issues: List[str] = []
    if not settings_path.exists():
        if any(hooks_dir.glob("mem-mesh-*.sh")):
            issues.append(f"{label}: hooks.json missing while mem-mesh scripts exist")
        return issues
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        issues.append(f"{label} hooks.json: invalid JSON ({e})")
        return issues
    except OSError as e:
        issues.append(f"{label} hooks.json: read error ({e})")
        return issues

    if not isinstance(data, dict) or not data:
        issues.append(f"{label} hooks.json: no hook groups")
        return issues

    count = _count_antigravity_mem_mesh_entries(settings_path)
    if count == 0:
        issues.append(
            f"{label}: no mem-mesh hooks registered in hooks.json "
            "(scripts alone are inactive)"
        )
        return issues

    required_scripts = {
        hooks_dir / "mem-mesh-stop.sh",
        hooks_dir / "mem-mesh-post-tool-use.sh",
    }
    for script in sorted(required_scripts):
        if not script.exists():
            issues.append(f"{label}: registered script missing ({script})")

    return issues


def _latest_hook_trace_at(log_text: str, tag: str) -> Optional[datetime]:
    """Return the latest timestamp for a client tag in hooks.log."""
    marker = f"[{tag}/"
    latest: Optional[datetime] = None
    for line in log_text.splitlines():
        if marker not in line:
            continue
        raw_ts = line.split(" ", 1)[0]
        try:
            ts = datetime.strptime(raw_ts, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            continue
        if latest is None or ts > latest:
            latest = ts
    return latest


def _is_stale_hook_trace(
    latest: datetime, now: datetime, max_age_seconds: int = _RUNTIME_TRACE_STALE_SECONDS
) -> bool:
    """Whether a hook trace is too old to prove current hook firing."""
    return (now - latest).total_seconds() > max_age_seconds


def _check_hook_runtime_traces() -> List[str]:
    """Report installed hook clients with no observed hooks.log trace."""
    issues: List[str] = []
    log_path = Path.home() / ".mem-mesh" / "hooks.log"
    print(header("[Hook Runtime Trace]"))
    if not log_path.exists():
        print(f"  {dim('~/.mem-mesh/hooks.log not found')}")
        print(
            f"  {dim('Set MEM_MESH_HOOK_LOG=1 and restart GUI clients to collect traces.')}"
        )
        print()
        return issues

    try:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        issue = f"hooks.log read error ({e})"
        print(f"  {err(issue)}")
        print()
        return [issue]

    clients = [
        (
            "Claude Code",
            "claude_code",
            bool(list(CLAUDE_HOOKS_DIR.glob("mem-mesh-*.sh"))),
        ),
        (
            "Kiro",
            "kiro",
            (KIRO_SCRIPTS_DIR / "mem-mesh-stop.sh").exists()
            and not _check_kiro_native_hook(KIRO_HOOKS_DIR, KIRO_SCRIPTS_DIR),
        ),
        (
            "Cursor",
            "cursor",
            CURSOR_SETTINGS.exists()
            and bool(_check_settings_json(CURSOR_SETTINGS, "Cursor") == []),
        ),
        (
            "Codex",
            "codex",
            bool(list(CODEX_HOOKS_DIR.glob("mem-mesh-*.sh")))
            and not _check_codex_hooks_json(CODEX_HOOKS_FILE, CODEX_HOOKS_DIR),
        ),
        (
            "Antigravity IDE",
            "antigravity",
            bool(list(ANTIGRAVITY_HOOKS_DIR.glob("mem-mesh-*.sh")))
            and not _check_antigravity_hooks_json(
                ANTIGRAVITY_HOOKS_FILE,
                ANTIGRAVITY_HOOKS_DIR,
                label="Antigravity IDE",
            ),
        ),
        (
            "agy CLI",
            "agy",
            bool(list(AGY_HOOKS_DIR.glob("mem-mesh-*.sh")))
            and not _check_antigravity_hooks_json(
                AGY_HOOKS_FILE,
                AGY_HOOKS_DIR,
                label="agy CLI",
            ),
        ),
    ]

    for label, tag, active in clients:
        if not active:
            continue
        latest = _latest_hook_trace_at(log_text, tag)
        if latest is not None and not _is_stale_hook_trace(
            latest, datetime.now(latest.tzinfo)
        ):
            print(f"  {label}: {ok(f'trace observed ({latest.isoformat()})')}")
        elif latest is not None:
            issue = (
                f"{label}: latest runtime trace is stale "
                f"({latest.isoformat()}; older than 24h)"
            )
            print(f"  {warn(issue)}")
            issues.append(issue)
        else:
            issue = (
                f"{label}: no runtime trace observed in hooks.log "
                "(hook may not be firing, or the client did not inherit MEM_MESH_HOOK_LOG)"
            )
            print(f"  {warn(issue)}")
            issues.append(issue)
    if not issues:
        print(f"  {ok('active hook clients have runtime traces')}")
    print()
    return issues


def _check_http_hook_urls(settings_path: Path, label: str) -> List[str]:
    """Flag mem-mesh http-type hooks whose URL Claude Code will refuse to call.

    Native HTTP hooks pointed at a Tailscale/VPN/LAN server (private or CGNAT
    address) are silently blocked at runtime; re-installing with ``--mode api``
    is the fix.
    """
    issues: List[str] = []
    if not settings_path.exists():
        return issues
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return issues

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return issues

    seen: set = set()
    for _event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks", []):
                if not isinstance(hook, dict):
                    continue
                if hook.get("type") != "http":
                    continue
                url = str(hook.get("url", ""))
                if "/api/hooks/claude/" not in url or url in seen:
                    continue
                seen.add(url)
                reason = check_http_hook_url(url)
                if reason:
                    issues.append(
                        f"{label}: HTTP hook will be blocked by Claude Code — "
                        f"{reason} (re-install with --mode api)"
                    )
    return issues


def _check_codex_config(config_path: Path) -> List[str]:
    issues: List[str] = []
    if not config_path.exists():
        return issues
    if not codex_config_has_mem_mesh(config_path):
        issues.append("Codex config.toml: no mem-mesh MCP server configured")
    return issues


def _check_env_vars(profile: str) -> List[str]:
    """Check required environment variables."""
    issues: List[str] = []
    if profile == "enhanced" and not os.environ.get("ANTHROPIC_API_KEY"):
        issues.append("ANTHROPIC_API_KEY not set (required for enhanced profile)")
    return issues


# ── Authentication diagnostics ──────────────────────────────────────────


def _mask_token(token: str) -> str:
    """Mask a token for display. Delegates to the single core masker (tail-only)."""
    from app.core.redaction import mask_secret

    return mask_secret(token)


def _client_hook_token() -> str:
    """Token that generated shell hooks and MCP configs actually carry."""
    env_token = (os.environ.get("MEM_MESH_HOOK_TOKEN") or "").strip()
    if env_token:
        return env_token
    try:
        from app.core.config import HOOK_TOKEN_FILE, _read_token_file

        return _read_token_file(HOOK_TOKEN_FILE) or ""
    except Exception:
        return ""


def _http(method: str, url: str, headers=None, data=None, timeout: float = 5.0):
    """Minimal HTTP probe. Returns (status_code|None, body_bytes). None = no connection."""
    import urllib.error
    import urllib.request

    # Explicit UA — the default urllib agent ("Python-urllib") is blocked as a
    # bot by some reverse proxies (Cloudflare), which made these auth probes
    # falsely 403 while the real curl-based hooks passed.
    hdrs = {"User-Agent": "mem-mesh-cli"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception:
        return None, b""


def _check_authentication(url: str) -> List[str]:
    """[Authentication]: server hook token source + server auth config."""
    issues: List[str] = []
    print(header("[Authentication]"))

    # Server token — resolved the same way the server does (env > data-dir >
    # ~/.mem-mesh). Client-effective token sync is shown in top-level doctor.
    try:
        from app.core.config import hook_token_source, resolve_hook_token

        token = resolve_hook_token()
        source = hook_token_source()
        if token:
            print(f"  Server token: {ok(source)}  {dim(_mask_token(token))}")
        else:
            print(
                f"  Server token: {warn('not configured locally')} "
                f"{dim('(server auto-generates one at startup)')}"
            )
    except Exception as e:  # pragma: no cover - defensive
        print(f"  Server token: {err(f'resolve failed: {e}')}")

    # Server auth config via GET /api/security/overview.
    status, body = _http("GET", f"{url.rstrip('/')}/api/security/overview")
    if status == 200:
        try:
            d = json.loads(body)
            web = d.get("web_dashboard_auth", {})
            mcp = d.get("mcp_auth", {})
            bind = d.get("bind", {})
            ba = "enabled" if web.get("basic_auth_enabled") else "disabled"
            pwd = (
                "admin password set" if web.get("admin_password_set") else "no password"
            )
            print(f"  Basic Auth:  {ba} ({pwd})")
            print(
                f"  OAuth:       auth_enabled={mcp.get('oauth_auth_enabled')}  "
                f"mcp_auth={mcp.get('mcp_auth_enabled')}"
            )
            host = bind.get("effective_host", "")
            loop = bind.get("is_loopback")
            print(
                f"  Bind:        {host} {dim('(loopback)') if loop else warn('(exposed)')}"
            )
            if (
                not loop
                and not web.get("basic_auth_enabled")
                and not mcp.get("oauth_auth_enabled")
            ):
                msg = "server on a non-loopback bind with NO authentication"
                print(f"  {warn(msg)}")
                issues.append(msg)
        except Exception:
            print(f"  Server auth: {warn('overview response could not be parsed')}")
    elif status == 401:
        print(
            f"  Server auth: {ok('OAuth web auth enabled (overview requires a token)')}"
        )
    elif status is None:
        print(f"  Server auth: {dim('server unreachable — local checks only')}")
    else:
        print(f"  Server auth: {warn(f'overview returned HTTP {status}')}")
    print()
    return issues


def _test_hook_auth(url: str) -> List[str]:
    """[Auth Test]: POST the hook endpoint with/without the local token."""
    issues: List[str] = []
    print(header("[Auth Test]"))
    ep = f"{url.rstrip('/')}/api/hooks/claude/session-start"
    ct = {"Content-Type": "application/json"}

    s_no, _ = _http("POST", ep, headers=ct, data=b"{}")
    if s_no is None:
        print(f"  {dim('server unreachable — auth test skipped')}")
        print()
        return issues

    # Unauthenticated POST: 401 = guarded (good); 2xx = unauthenticated writes.
    if s_no == 401:
        print(f"  hook POST no-token  -> {ok('401 rejected')}")
    elif 200 <= s_no < 300:
        print(
            f"  hook POST no-token  -> {warn(f'{s_no} ACCEPTED — hook writes are unauthenticated')}"
        )
        issues.append(
            "hook endpoint accepts unauthenticated writes (no token configured server-side)"
        )
    else:
        print(f"  hook POST no-token  -> {dim(str(s_no))}")

    # Authenticated POST with the client-effective token carried by generated
    # hooks/MCP configs, not the server-private data-dir fallback.
    token = _client_hook_token()
    if not token:
        print(f"  hook POST w/ token  -> {dim('skipped (no local token)')}")
        print()
        return issues

    s_tok, _ = _http(
        "POST", ep, headers={**ct, "Authorization": f"Bearer {token}"}, data=b"{}"
    )
    if s_tok is None:
        print(f"  hook POST w/ token  -> {dim('no response')}")
    elif s_tok == 401:
        print(
            f"  hook POST w/ token  -> {err('401 — local token rejected (mismatch with server)')}"
        )
        issues.append("hook token mismatch: locally-resolved token rejected by server")
    else:
        print(f"  hook POST w/ token  -> {ok(f'{s_tok} accepted')}")
    print()
    return issues


def cmd_doctor() -> None:
    """Run full diagnostics: status + connectivity + permissions + env."""
    # Run status first
    cmd_status()

    print(header("=== Doctor Diagnostics ==="))
    print()

    issues: List[str] = []

    # 1. Script permissions
    print(header("[Permissions]"))
    for label, hooks_dir in [
        ("Claude", CLAUDE_HOOKS_DIR),
        ("Kiro", KIRO_SCRIPTS_DIR),
        ("Cursor", CURSOR_HOOKS_DIR),
        ("Codex", CODEX_HOOKS_DIR),
        ("Antigravity IDE", ANTIGRAVITY_HOOKS_DIR),
        ("agy CLI", AGY_HOOKS_DIR),
    ]:
        perm_issues = _check_permissions(hooks_dir)
        if not hooks_dir.exists():
            print(f"  {label}: {dim('hooks directory not found')}")
        elif perm_issues:
            for issue in perm_issues:
                print(f"  {label}: {err(issue)}")
            issues.extend(f"{label}: {i}" for i in perm_issues)
        else:
            scripts = list(hooks_dir.glob("mem-mesh-*.sh"))
            if scripts:
                print(f"  {label}: {ok(f'all {len(scripts)} script(s) executable')}")
            else:
                print(f"  {label}: {dim('no scripts found')}")
    print()

    # 2. Settings JSON integrity
    print(header("[Settings Integrity]"))
    for label, settings_path in [
        ("Claude", CLAUDE_SETTINGS),
        ("Cursor", CURSOR_SETTINGS),
    ]:
        json_issues = _check_settings_json(settings_path, label)
        json_issues.extend(_check_http_hook_urls(settings_path, label))
        if not settings_path.exists():
            print(f"  {label}: {dim('settings file not found')}")
        elif json_issues:
            for issue in json_issues:
                print(f"  {err(issue)}")
            issues.extend(json_issues)
        else:
            print(f"  {label}: {ok('valid')}")

    kiro_json_issues = _check_kiro_native_hook(KIRO_HOOKS_DIR, KIRO_SCRIPTS_DIR)
    if not (KIRO_HOOKS_DIR / "mem-mesh-save-response.kiro.hook").exists():
        print(f"  Kiro: {dim('native hook file not found')}")
    elif kiro_json_issues:
        for issue in kiro_json_issues:
            print(f"  {err(issue)}")
        issues.extend(kiro_json_issues)
    else:
        print(f"  Kiro: {ok('valid')}")
    kiro_cli_issues = _check_kiro_cli_agent(KIRO_CLI_AGENT, KIRO_SCRIPTS_DIR)
    if not KIRO_CLI_AGENT.exists():
        print(f"  Kiro CLI: {dim('custom agent not found')}")
    elif kiro_cli_issues:
        for issue in kiro_cli_issues:
            print(f"  {err(issue)}")
        issues.extend(kiro_cli_issues)
    else:
        print(f"  Kiro CLI: {ok('valid (--agent mem-mesh)')}")
    legacy_kiro_issues = _check_settings_json(KIRO_SETTINGS, "Kiro legacy")
    if KIRO_SETTINGS.exists() and legacy_kiro_issues:
        print(f"  {dim('Kiro legacy hooks.json ignored by modern Kiro hooks')}")

    codex_json_issues = _check_codex_hooks_json(CODEX_HOOKS_FILE, CODEX_HOOKS_DIR)
    if not CODEX_HOOKS_FILE.exists():
        print(f"  Codex: {dim('settings file not found')}")
    elif codex_json_issues:
        for issue in codex_json_issues:
            print(f"  {err(issue)}")
        issues.extend(codex_json_issues)
    else:
        print(f"  Codex: {ok('valid')}")

    codex_issues = _check_codex_config(CODEX_CONFIG)
    if CODEX_CONFIG.exists() and codex_issues:
        for issue in codex_issues:
            print(f"  {err(issue)}")
        issues.extend(codex_issues)
    elif CODEX_CONFIG.exists():
        print(f"  Codex config.toml: {ok('valid')}")

    for label, settings_path, hooks_dir in [
        ("Antigravity IDE", ANTIGRAVITY_HOOKS_FILE, ANTIGRAVITY_HOOKS_DIR),
        ("agy CLI", AGY_HOOKS_FILE, AGY_HOOKS_DIR),
    ]:
        antigravity_issues = _check_antigravity_hooks_json(
            settings_path, hooks_dir, label=label
        )
        if not settings_path.exists():
            print(f"  {label}: {dim('settings file not found')}")
        elif antigravity_issues:
            for issue in antigravity_issues:
                print(f"  {err(issue)}")
            issues.extend(antigravity_issues)
        else:
            print(f"  {label}: {ok('valid')}")
    print()

    issues.extend(_check_hook_runtime_traces())

    # 3. Environment variables
    print(header("[Environment]"))
    profile = _detect_profile(CLAUDE_HOOKS_DIR, CLAUDE_SETTINGS)

    mem_mesh_url = os.environ.get("MEM_MESH_API_URL")
    api_url_env = os.environ.get("API_URL")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    config_file = Path.home() / ".mem-mesh" / "api_url"
    config_file_url = None
    if config_file.is_file():
        try:
            config_file_url = config_file.read_text(encoding="utf-8").strip()
        except OSError:
            pass

    print(
        f"  MEM_MESH_API_URL:  {ok(mem_mesh_url) if mem_mesh_url else dim('not set')}"
    )
    print(f"  API_URL:           {ok(api_url_env) if api_url_env else dim('not set')}")
    print(
        f"  ~/.mem-mesh/api_url: {ok(config_file_url) if config_file_url else dim('not set')}"
    )
    print(f"  ANTHROPIC_API_KEY: {ok('set') if anthropic_key else warn('not set')}")
    print(f"  Detected profile:  {bold(profile)}")

    env_issues = _check_env_vars(profile)
    issues.extend(env_issues)
    for issue in env_issues:
        print(f"  {err(issue)}")
    print()

    # 4. Connectivity (already shown in status, but repeat for doctor summary)
    print(header("[Connectivity Detail]"))
    baked_url = _extract_url_from_script(
        CLAUDE_HOOKS_DIR / "mem-mesh-session-start.sh"
    ) or _extract_url_from_script(CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh")
    url, source = resolve_api_url(baked_url)
    print(f"  Resolved URL: {bold(url)} {dim(f'(from {source})')}")
    reachable, message = check_connectivity(url)
    if reachable:
        print(f"  Health:       {ok(message)}")
    else:
        print(f"  Health:       {err(message)}")
        issues.append(f"API unreachable at {url}: {message}")

    # If env var URL differs from baked URL, test both
    if baked_url and url != baked_url:
        print(f"  Baked URL:    {dim(baked_url)}")
        baked_ok, baked_msg = check_connectivity(baked_url)
        if baked_ok:
            print(f"  Baked health: {ok(baked_msg)}")
        else:
            print(f"  Baked health: {warn(baked_msg)}")
    print()

    # 5. Authentication config (hook token + server OAuth/Basic Auth state)
    issues.extend(_check_authentication(url))

    # 6. Live auth test (hook endpoint with/without the resolved token)
    issues.extend(_test_hook_auth(url))

    # Summary
    print(header("[Summary]"))
    if issues:
        print(f"  Issues found: {err(str(len(issues)))}")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print(f"  {ok('No issues found')}")
    print()
