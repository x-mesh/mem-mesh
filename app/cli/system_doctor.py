"""`mem-mesh doctor` — top-level full-system diagnostics.

A single command that verifies the whole stack — API reachability (clearly
separating an auth gate from a network failure), hook auth token, MCP config
across every dev tool, and the hook auth handshake — and prints an actionable
fix under each problem. ``status`` stays a quick summary; ``doctor`` is where
you go when something is wrong.

The deep hook-script checks live in ``app.cli.hooks.doctor``; this surface
reuses those helpers rather than duplicating them, and adds the cross-cutting
API/token/MCP view on top.
"""

import os
from typing import List, Optional

from app.cli.hooks.colors import dim, err, header, info, ok, warn
from app.cli.hooks.constants import (
    CLAUDE_HOOKS_DIR,
    CLAUDE_SETTINGS,
    CURSOR_HOOKS_DIR,
    CURSOR_SETTINGS,
    KIRO_HOOKS_DIR,
    KIRO_SETTINGS,
)
from app.cli.hooks.diagnostics import (
    collect_claude_overrides,
    collect_mcp_status,
    collect_token_status,
    entry_json,
)
from app.cli.hooks.render import render_entry_source, render_json_block
from app.cli.hooks.status import (
    _detect_profile,
    _extract_url_from_script,
    _read_config_file_url,
    probe_api,
    resolve_api_url,
)


def _render_api(url: str, source: str, issues: List[str]) -> None:
    """[API]: 3-state probe — distinguish an auth gate from a network failure."""
    print(header("[API]"))
    print(f"  URL:    {info(url)} {dim(f'(from {source})')}")
    probe = probe_api(url)
    if probe.ok:
        print(f"  Status: {ok(probe.message)}")
    elif probe.auth_required:
        # The server answered — this is NOT a network problem. Say so explicitly
        # so the operator does not start debugging connectivity or reinstalling.
        print(f"  Status: {warn(probe.message)}")
        print(
            f"  {dim('The server is UP — this is an auth gate, not a network error.')}"
        )
        print(
            f"  {dim('→ export the token: mem-mesh hooks setup-token, or check your reverse proxy auth.')}"
        )
        issues.append(f"API at {url} requires authentication (HTTP {probe.status})")
    else:
        print(f"  Status: {err(probe.message)}")
        print(
            f"  {dim('→ start the server: mem-mesh serve   (or: docker compose up -d)')}"
        )
        issues.append(f"API unreachable at {url}: {probe.message}")
    print()


def _render_token(issues: List[str]) -> None:
    """[Hook Token]: source + masked preview + remediation when file-only."""
    print(header("[Hook Token]"))
    token = collect_token_status()
    if token.source == "env":
        print(
            f"  Source: {ok('shell env (MEM_MESH_HOOK_TOKEN)')}  {info(token.masked)}"
        )
        print(f"  {dim('HTTP hooks / MCP are authenticated.')}")
    elif token.present:
        label = {
            "data_file": "data dir hook_token",
            "legacy_file": "~/.mem-mesh/hook_token",
        }.get(token.source, token.source)
        print(f"  Source: {warn(f'file only ({label})')}  {info(token.masked)}")
        print(
            f"  {dim('.sh hooks are covered, but HTTP hooks / MCP read the SHELL env only.')}"
        )
        print(f"  {dim('→ export it: mem-mesh hooks setup-token')}")
    else:
        print(f"  Source: {dim('not set')}")
        print(f"  {dim('Only required when the server enforces authentication.')}")
    print()


def _entry_has_auth_header(entry: Optional[dict]) -> bool:
    """True if an http MCP entry carries an Authorization header."""
    if not entry:
        return False
    headers = entry.get("headers") or {}
    return bool(headers.get("Authorization"))


def _render_mcp(
    url: str, verbose: bool, issues: List[str], mcp_auth_required: Optional[bool] = None
) -> None:
    """[MCP]: every detected dev tool, with the misconfigured ones flagged.

    When the server enforces MCP auth (``mcp_auth_required``), an http entry
    without an Authorization header is flagged — it will be rejected at call
    time even though the config itself looks valid.
    """
    print(header("[MCP]"))
    tools = collect_mcp_status(url)
    installed = [t for t in tools if t.installed]
    if not installed:
        print(f"  {dim('No supported dev tools detected.')}")
        print()
        return

    for t in installed:
        mode = t.mode or "-"
        if not t.configured:
            print(f"  {dim('·')} {t.name:<15} {dim('not configured')}")
            continue
        if t.verified:
            print(f"  {ok('✓')} {t.name:<15} {info(mode):<8} {dim(t.verify_message)}")
        else:
            print(f"  {err('✗')} {t.name:<15} {info(mode):<8} {err(t.verify_message)}")
            issues.append(f"MCP for {t.name}: {t.verify_message}")
            print(f"     {dim('→ re-run: mem-mesh mcp config')}")
        # Server requires MCP auth but this http entry sends no token header.
        if (
            mcp_auth_required
            and t.mode == "http"
            and not _entry_has_auth_header(t.entry)
        ):
            issues.append(
                f"MCP for {t.name}: server requires auth but entry has no token"
            )
            print(
                f"     {warn('!')} {dim('server enforces MCP auth — add token: mem-mesh mcp config --auth')}"
            )
        if verbose and t.configured:
            render_entry_source(t.config_path, t.entry_lines, entry_json(t.entry))

    # MCP↔hook URL divergence: a configured http entry pointing at a different
    # host than the hook [API] url means MCP and hooks talk to different servers
    # (the split-brain `mcp config --url` used to create). Surface it — the
    # per-tool "server reachable" line checks each entry's own url, so a healthy
    # MCP and a localhost [API] can otherwise look fine side by side.
    from urllib.parse import urlparse

    hook_host = urlparse(url).hostname
    mcp_hosts = sorted(
        {
            urlparse(t.entry["url"]).hostname
            for t in installed
            if t.configured and t.entry and t.entry.get("url")
        }
    )
    diverged = [h for h in mcp_hosts if h and h != hook_host]
    if diverged:
        print(
            f"  {warn('!')} URL split: MCP → {', '.join(diverged)} "
            f"but hooks/[API] → {hook_host}"
        )
        print(
            f"     {dim('→ align both: mem-mesh mcp config --url <url> (writes hook SSOT too)')}"
        )
        issues.append(
            f"MCP/hook URL split: MCP={','.join(diverged)} vs hooks={hook_host}"
        )
    print()


def _mcp_auth_required(url: str) -> Optional[bool]:
    """Whether the server enforces MCP auth, via /api/security/overview.

    Returns True/False, or None when the server is unreachable / the field is
    absent (so the caller can skip the check rather than warn spuriously).
    """
    from app.cli.hooks.doctor import _http

    status, body = _http("GET", f"{url.rstrip('/')}/api/security/overview")
    if status != 200 or not body:
        return None
    try:
        import json as _json

        data = _json.loads(body)
        return bool(data.get("mcp_auth", {}).get("mcp_auth_enabled"))
    except Exception:
        return None


def _render_overrides(verbose: bool, issues: List[str]) -> None:
    """[MCP Overrides]: per-project Claude Code entries that shadow the global one."""
    overrides = collect_claude_overrides()
    if not overrides:
        return
    print(header("[MCP Overrides] (Claude Code, per-project)"))
    import os

    home = os.path.expanduser("~")
    for ov in overrides:
        path = (
            ("~" + ov.project_path[len(home) :])
            if ov.project_path.startswith(home)
            else ov.project_path
        )
        if ov.differs:
            print(f"  {warn('!')} {path}")
            print(f"      {dim(ov.summary)}  {warn('differs from global')}")
            issues.append(f"Claude project override shadows global MCP: {path}")
        else:
            print(f"  {dim('·')} {path}  {dim('(matches global)')}")
        if verbose:
            render_json_block(entry_json(ov.entry))
    print(f"  {dim('→ remove stale shadows: mem-mesh mcp clean')}")
    print()


def _render_ssot(issues: List[str]) -> None:
    """[SSOT]: the ~/.mem-mesh files every tool's hooks read when env is unset.

    The point of the file SSOT is that GUI- and terminal-launched tools alike
    resolve config from here — so the canonical values belong on screen, not
    only the currently-effective (possibly env-overridden) ones. Each line shows
    the on-disk value (token masked) and whether it is the active source or
    shadowed by an env override.
    """
    from app.core.config import (
        HOOK_TOKEN_FILE,
        _data_dir_hook_token_file,
        _read_token_file,
    )
    from app.core.redaction import mask_secret

    print(
        header("[SSOT]")
        + dim(
            "  ~/.mem-mesh — the file source every tool's hooks read when env is unset"
        )
    )

    # api_url — ~/.mem-mesh/api_url
    file_url = _read_config_file_url()
    env_url = os.environ.get("MEM_MESH_API_URL") or os.environ.get("API_URL")
    if file_url:
        state = warn("(shadowed by env)") if env_url else ok("(active)")
        print(f"  api_url      {info(file_url)}  {state}")
    else:
        print(
            f"  api_url      {dim('not set')} "
            f"{dim('— hooks fall back to the baked/default URL')}"
        )

    # hook_token — prefer the server-resolved on-disk file (data dir, then legacy)
    token_value = None
    token_label = None
    for label, path in (
        ("data dir", _data_dir_hook_token_file()),
        ("~/.mem-mesh", HOOK_TOKEN_FILE),
    ):
        found = _read_token_file(path)
        if found:
            token_value, token_label = found, label
            break
    env_tok = (os.environ.get("MEM_MESH_HOOK_TOKEN") or "").strip()
    if token_value:
        state = warn("(shadowed by env)") if env_tok else ok("(active)")
        print(
            f"  hook_token   {info(mask_secret(token_value))} "
            f"{dim(f'({token_label})')}  {state}"
        )
    else:
        print(
            f"  hook_token   {dim('not set')} "
            f"{dim('— authenticated hooks will be rejected (401)')}"
        )
    print()


def _render_conflicts(issues: List[str]) -> None:
    """[Config Conflicts]: surface values shadowed in the resolution chain.

    URL resolves as ``MEM_MESH_API_URL env > API_URL env > ~/.mem-mesh/api_url``
    and the token as ``MEM_MESH_HOOK_TOKEN env > <data dir> > ~/.mem-mesh``. Each
    silently takes the first hit, so the active value comes from a higher layer
    than the file SSOT. Two shapes are reported:

    * ``conflict`` — a higher layer holds a *different* value, so effective
      config diverges from what a file/dotfile edit suggests (the 401 trap).
      Counted as an issue.
    * ``redundant`` — env shadows the file with the *same* value: harmless now,
      but the file is inactive (edits won't take effect) and a later divergence
      would silently win. Reported as info, not an issue — it explains why the
      [API]/[Hook Token] source reads "env" while the file looks authoritative.
    """
    print(header("[Config Conflicts]"))
    conflicts: List[str] = []
    redundant: List[str] = []

    # --- API URL chain ---
    env_url = (os.environ.get("MEM_MESH_API_URL") or "").rstrip("/")
    alt_env_url = (os.environ.get("API_URL") or "").rstrip("/")
    file_url = (_read_config_file_url() or "").rstrip("/")
    if env_url:
        if alt_env_url and alt_env_url != env_url:
            conflicts.append(
                f"API_URL={alt_env_url} ignored — MEM_MESH_API_URL={env_url} wins"
            )
        if file_url:
            if file_url != env_url:
                conflicts.append(
                    f"~/.mem-mesh/api_url={file_url} ignored — "
                    f"MEM_MESH_API_URL env={env_url} wins (edits to the file have no effect)"
                )
            else:
                redundant.append(
                    f"MEM_MESH_API_URL env shadows ~/.mem-mesh/api_url "
                    f"(same value {env_url}; file inactive — unset env to make it authoritative)"
                )
    elif alt_env_url and file_url and alt_env_url != file_url:
        conflicts.append(
            f"~/.mem-mesh/api_url={file_url} ignored — API_URL env={alt_env_url} wins"
        )

    # --- Hook token chain: env shadowing an on-disk token ---
    from app.core.config import (
        HOOK_TOKEN_FILE,
        _data_dir_hook_token_file,
        _read_token_file,
        hook_token_source,
    )

    if hook_token_source() == "env":
        env_tok = (os.environ.get("MEM_MESH_HOOK_TOKEN") or "").strip()
        for label, path in (
            ("<data dir>/hook_token", _data_dir_hook_token_file()),
            ("~/.mem-mesh/hook_token", HOOK_TOKEN_FILE),
        ):
            file_tok = _read_token_file(path)
            if not file_tok or not env_tok:
                continue
            if file_tok != env_tok:
                conflicts.append(
                    f"{label} differs from MEM_MESH_HOOK_TOKEN env — "
                    f"env wins (a rotated on-disk token is being overridden)"
                )
            else:
                redundant.append(
                    f"MEM_MESH_HOOK_TOKEN env shadows {label} "
                    f"(same value; file inactive — unset env to make it authoritative)"
                )

    if conflicts:
        for c in conflicts:
            print(f"  {warn('shadowed:')} {c}")
        issues.append(
            f"{len(conflicts)} shadowed config value(s) — see Config Conflicts"
        )
    for r in redundant:
        print(f"  {dim('redundant:')} {r}")
    if conflicts or redundant:
        print(
            f"  {dim('→ keep one source per key. SSOT: ~/.mem-mesh/{api_url,hook_token}; ')}"
            f"{dim('unset the env override unless you mean to override deliberately.')}"
        )
    else:
        print(f"  {ok('no shadowed config — single source per key')}")
    print()


def _render_hooks_summary() -> None:
    """[Hooks]: compact per-tool summary; defer the deep checks to `hooks doctor`."""
    print(header("[Hooks]"))
    for label, hooks_dir, settings_path in [
        ("Claude Code", CLAUDE_HOOKS_DIR, CLAUDE_SETTINGS),
        ("Kiro", KIRO_HOOKS_DIR, KIRO_SETTINGS),
        ("Cursor", CURSOR_HOOKS_DIR, CURSOR_SETTINGS),
    ]:
        if not hooks_dir.exists():
            print(f"  {label:12s}  {dim('no hooks installed')}")
            continue
        count = len(list(hooks_dir.glob("mem-mesh-*.sh")))
        if count == 0:
            print(f"  {label:12s}  {dim('no hooks installed')}")
            continue
        profile = _detect_profile(hooks_dir, settings_path)
        print(f"  {label:12s}  {ok(f'{count} hooks')} {dim(f'({profile} profile)')}")
    print(f"  {dim('→ deep hook diagnostics + live auth test: mem-mesh hooks doctor')}")
    print()


def cmd_system_doctor(verbose: bool = False) -> int:
    """Full-system diagnostics. Returns an exit code (0 = healthy, 1 = issues)."""
    print()
    print(header("=== mem-mesh doctor ==="))
    print()

    issues: List[str] = []

    baked_url = _extract_url_from_script(
        CLAUDE_HOOKS_DIR / "mem-mesh-session-start.sh"
    ) or _extract_url_from_script(CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh")
    url, source = resolve_api_url(baked_url)

    _render_api(url, source, issues)
    _render_token(issues)
    _render_ssot(issues)

    # Server-side auth config + live hook-endpoint auth test (401 vs network is
    # already differentiated inside these helpers).
    from app.cli.hooks.doctor import _check_authentication, _test_hook_auth

    issues.extend(_check_authentication(url))
    issues.extend(_test_hook_auth(url))

    _render_mcp(url, verbose, issues, mcp_auth_required=_mcp_auth_required(url))
    _render_overrides(verbose, issues)
    _render_conflicts(issues)
    _render_hooks_summary()

    # Summary — most important info last (clig.dev).
    print(header("[Summary]"))
    if issues:
        print(f"  {err(str(len(issues)))} issue(s) found:")
        for issue in issues:
            print(f"    {err('✗')} {issue}")
        print()
        return 1
    print(f"  {ok('All systems healthy.')}")
    print()
    return 0
