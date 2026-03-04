"""Hook diagnostics and health checks."""

import json
import os
from pathlib import Path
from typing import List

from app.cli.hooks.colors import bold, dim, err, header, ok, warn
from app.cli.hooks.constants import (
    CLAUDE_HOOKS_DIR,
    CLAUDE_SETTINGS,
    CURSOR_HOOKS_DIR,
    CURSOR_SETTINGS,
    KIRO_HOOKS_DIR,
    KIRO_SETTINGS,
)
from app.cli.hooks.status import (
    _detect_profile,
    _extract_url_from_script,
    check_connectivity,
    cmd_status,
    resolve_api_url,
)


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
        # Claude/Cursor: {"EventName": [{"hooks": [{"command": "..."}]}]}
        for _event, entries in hooks.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                hook_list = entry.get("hooks", []) if isinstance(entry, dict) else []
                for hook in hook_list:
                    cmd = hook.get("command", "")
                    if "mem-mesh" in cmd:
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

    return issues


def _check_env_vars(profile: str) -> List[str]:
    """Check required environment variables."""
    issues: List[str] = []
    if profile == "enhanced" and not os.environ.get("ANTHROPIC_API_KEY"):
        issues.append("ANTHROPIC_API_KEY not set (required for enhanced profile)")
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
        ("Kiro", KIRO_HOOKS_DIR),
        ("Cursor", CURSOR_HOOKS_DIR),
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
        ("Kiro", KIRO_SETTINGS),
        ("Cursor", CURSOR_SETTINGS),
    ]:
        json_issues = _check_settings_json(settings_path, label)
        if not settings_path.exists():
            print(f"  {label}: {dim('settings file not found')}")
        elif json_issues:
            for issue in json_issues:
                print(f"  {err(issue)}")
            issues.extend(json_issues)
        else:
            print(f"  {label}: {ok('valid')}")
    print()

    # 3. Environment variables
    print(header("[Environment]"))
    profile = _detect_profile(CLAUDE_HOOKS_DIR, CLAUDE_SETTINGS)

    mem_mesh_url = os.environ.get("MEM_MESH_API_URL")
    api_url_env = os.environ.get("API_URL")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    print(f"  MEM_MESH_API_URL:  {ok(mem_mesh_url) if mem_mesh_url else dim('not set')}")
    print(f"  API_URL:           {ok(api_url_env) if api_url_env else dim('not set')}")
    print(f"  ANTHROPIC_API_KEY: {ok('set') if anthropic_key else warn('not set')}")
    print(f"  Detected profile:  {bold(profile)}")

    env_issues = _check_env_vars(profile)
    issues.extend(env_issues)
    for issue in env_issues:
        print(f"  {err(issue)}")
    print()

    # 4. Connectivity (already shown in status, but repeat for doctor summary)
    print(header("[Connectivity Detail]"))
    baked_url = (
        _extract_url_from_script(CLAUDE_HOOKS_DIR / "mem-mesh-session-start.sh")
        or _extract_url_from_script(CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh")
    )
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

    # Summary
    print(header("[Summary]"))
    if issues:
        print(f"  Issues found: {err(str(len(issues)))}")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print(f"  {ok('No issues found')}")
    print()
