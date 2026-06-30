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

from app.cli.codex_config import CODEX_HOOKS_DIR, CODEX_HOOKS_FILE
from app.cli.hooks.colors import dim, err, header, info, ok, warn
from app.cli.hooks.constants import (
    AGY_HOOKS_DIR,
    AGY_HOOKS_FILE,
    ANTIGRAVITY_HOOKS_DIR,
    ANTIGRAVITY_HOOKS_FILE,
    CLAUDE_HOOKS_DIR,
    CLAUDE_SETTINGS,
    CURSOR_HOOKS_DIR,
    CURSOR_SETTINGS,
    KIRO_HOOKS_DIR,
    KIRO_SCRIPTS_DIR,
    KIRO_SETTINGS,
)
from app.cli.hooks.diagnostics import (
    collect_claude_overrides,
    collect_mcp_status,
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
            f"  {dim('→ ensure the token file exists + tools carry it: mem-mesh mcp config --auth, or check your reverse proxy auth.')}"
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
    """[Hook Token]: env-first operator token + materialized fallback state.

    ``MEM_MESH_HOOK_TOKEN`` is the operator SSOT. ``~/.mem-mesh/hook_token`` is
    the CLI-managed materialized cache/fallback used by hooks and MCP config
    generation. The server's data-dir token is shown only as server-private
    fallback state; it is not the MCP/client SSOT.
    """
    from app.core.redaction import mask_secret

    print(header("[Hook Token]"))
    env_tok = _env_hook_token()
    file_tok = _materialized_hook_token()
    data_tok = _server_private_hook_token()

    if env_tok:
        print(
            f"  Source: {ok('MEM_MESH_HOOK_TOKEN env (SSOT)')}  {info(mask_secret(env_tok))}"
        )
        if file_tok == env_tok:
            print(f"          {ok('~/.mem-mesh/hook_token in sync')}")
        elif file_tok:
            print(
                f"          {warn('~/.mem-mesh/hook_token stale — run: mem-mesh mcp config --auth')}"
            )
        else:
            print(
                f"          {warn('~/.mem-mesh/hook_token missing — run: mem-mesh mcp config --auth')}"
            )
    elif file_tok:
        print(
            f"  Source: {warn('~/.mem-mesh/hook_token fallback')}  {info(mask_secret(file_tok))}"
        )
        print(
            f"          {dim('Set MEM_MESH_HOOK_TOKEN to make the operator SSOT explicit.')}"
        )
    elif data_tok:
        print(
            f"  Source: {warn('server-private data-dir fallback only')}  {info(mask_secret(data_tok))}"
        )
        print(
            f"          {dim('Not used as MCP/client SSOT — set MEM_MESH_HOOK_TOKEN or run setup.')}"
        )
    else:
        print(f"  Source: {dim('not set')}")
        print(f"          {dim('Run: mem-mesh mcp config --auth or mem-mesh install')}")
    print()


def _entry_has_auth_header(entry: Optional[dict]) -> bool:
    """True if an http MCP entry carries an Authorization header."""
    if not entry:
        return False
    headers = entry.get("headers") or {}
    return bool(headers.get("Authorization"))


def _env_hook_token() -> Optional[str]:
    token = (os.environ.get("MEM_MESH_HOOK_TOKEN") or "").strip()
    return token or None


def _materialized_hook_token() -> Optional[str]:
    from app.core.config import HOOK_TOKEN_FILE, _read_token_file

    return _read_token_file(HOOK_TOKEN_FILE)


def _server_private_hook_token() -> Optional[str]:
    from app.core.config import _data_dir_hook_token_file, _read_token_file

    return _read_token_file(_data_dir_hook_token_file())


def _server_private_hook_token_source() -> str:
    from app.core.config import _data_dir_hook_token_file

    return str(_data_dir_hook_token_file())


def _effective_hook_token() -> Optional[str]:
    return _env_hook_token() or _materialized_hook_token()


def _effective_hook_token_source() -> Optional[str]:
    if _env_hook_token():
        return "MEM_MESH_HOOK_TOKEN env"
    if _materialized_hook_token():
        from app.core.config import HOOK_TOKEN_FILE

        return str(HOOK_TOKEN_FILE)
    return None


def _entry_literal_token(entry: Optional[dict]) -> Optional[str]:
    """The literal bearer token stamped into an http entry's Authorization
    header, or None when it is absent or still a ``${ENV}`` reference."""
    if not entry:
        return None
    auth = (entry.get("headers") or {}).get("Authorization") or ""
    if not auth.startswith("Bearer "):
        return None
    tok = auth[len("Bearer ") :].strip()
    if not tok or "${" in tok or "$" in tok:
        return None
    return tok


def _entry_references_token_env(entry: Optional[dict]) -> bool:
    """True if an http entry's Authorization header carries a ``${...}`` env
    reference instead of an inline literal token.

    mem-mesh generated config stamps the effective token as a literal because
    GUI-launched clients do not reliably inherit shell env. An env reference is
    therefore stale generated config; re-run ``mem-mesh mcp config --auth``.
    """
    if not entry:
        return False
    auth = (entry.get("headers") or {}).get("Authorization") or ""
    return "${" in auth


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

    expected_token = _effective_hook_token()
    expected_token_source = _effective_hook_token_source() or "effective hook token"
    for t in installed:
        literal_token = _entry_literal_token(t.entry)
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
        # --- auth header health (option 2: a literal token must be stamped) ---
        # 1) Server enforces MCP auth but this http entry has no token header.
        if (
            mcp_auth_required
            and t.mode == "http"
            and not _entry_has_auth_header(t.entry)
        ):
            issues.append(
                f"MCP for {t.name}: server requires auth but entry has no token"
            )
            print(
                f"     {warn('!')} {dim('no token — stamp the literal token: mem-mesh mcp config --auth')}"
            )
        # 2) Header references ${...}: mem-mesh generated config now stamps a
        # literal effective token so GUI-launched clients authenticate too.
        elif t.mode == "http" and _entry_references_token_env(t.entry):
            issues.append(
                f"MCP for {t.name}: Authorization header references a ${{...}} "
                f"env var — re-stamp the effective token as a literal header"
            )
            print(
                f"     {warn('!')} {dim('re-stamp the literal: mem-mesh mcp config --auth, then restart the client')}"
            )
        # 3) Literal token present but stale (differs from env-first effective token).
        elif (
            t.mode == "http"
            and literal_token
            and expected_token
            and literal_token != expected_token
        ):
            issues.append(
                f"MCP for {t.name}: stamped token is stale "
                f"(differs from {expected_token_source}) — re-stamp"
            )
            print(
                f"     {warn('!')} {dim('stale token literal — re-stamp: mem-mesh mcp config --auth')}"
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
            f"     {dim('→ align both: mem-mesh mcp config --url <url> (materializes ~/.mem-mesh/api_url too)')}"
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
    """[SSOT]: env is canonical; files are materialized fallback/cache.

    ``MEM_MESH_API_URL`` and ``MEM_MESH_HOOK_TOKEN`` are the operator SSOT.
    ``~/.mem-mesh`` files are generated/synced by the CLI so hooks and MCP
    config generation have a stable local fallback. Server data-dir token state
    is not a client/MCP source of truth.
    """
    from app.core.redaction import mask_secret

    print(
        header("[SSOT]")
        + dim("  env is canonical — ~/.mem-mesh is the materialized fallback/cache")
    )

    env_url = (os.environ.get("MEM_MESH_API_URL") or "").strip()
    legacy_env_url = (os.environ.get("API_URL") or "").strip()
    file_url = (_read_config_file_url() or "").strip()
    effective_url = env_url or legacy_env_url or file_url

    if env_url:
        print(f"  api_url      {info(env_url)}  {ok('(MEM_MESH_API_URL env SSOT)')}")
    elif legacy_env_url:
        print(f"  api_url      {warn(legacy_env_url)}  {warn('(API_URL legacy env)')}")
    elif file_url:
        print(f"  api_url      {warn(file_url)}  {warn('(~/.mem-mesh fallback)')}")
        print(
            f"               {dim('Set MEM_MESH_API_URL to make the operator SSOT explicit.')}"
        )
    else:
        print(
            f"  api_url      {dim('not set')} "
            f"{dim('— run: mem-mesh mcp config --url <url>')}"
        )

    if env_url or legacy_env_url:
        if file_url:
            if file_url == effective_url:
                print(f"               {ok('~/.mem-mesh/api_url in sync')}")
            else:
                print(
                    f"               {warn('~/.mem-mesh/api_url stale — run: mem-mesh mcp config --url <url>')}"
                )
        else:
            print(
                f"               {warn('~/.mem-mesh/api_url missing — run: mem-mesh mcp config --url <url>')}"
            )

    env_tok = _env_hook_token()
    file_tok = _materialized_hook_token()
    data_tok = _server_private_hook_token()
    effective_tok = env_tok or file_tok

    if env_tok:
        print(
            f"  hook_token   {info(mask_secret(env_tok))}  {ok('(MEM_MESH_HOOK_TOKEN env SSOT)')}"
        )
    elif file_tok:
        print(
            f"  hook_token   {warn(mask_secret(file_tok))}  {warn('(~/.mem-mesh fallback)')}"
        )
        print(
            f"               {dim('Set MEM_MESH_HOOK_TOKEN to make the operator SSOT explicit.')}"
        )
    else:
        print(
            f"  hook_token   {dim('not set')} "
            f"{dim('— run: mem-mesh mcp config --auth')}"
        )

    if env_tok:
        if file_tok:
            if file_tok == env_tok:
                print(f"               {ok('~/.mem-mesh/hook_token in sync')}")
            else:
                print(
                    f"               {warn('~/.mem-mesh/hook_token stale — run: mem-mesh mcp config --auth')}"
                )
        else:
            print(
                f"               {warn('~/.mem-mesh/hook_token missing — run: mem-mesh mcp config --auth')}"
            )

    if data_tok and data_tok != effective_tok:
        print(
            f"               {dim(f'server-private fallback differs: {_server_private_hook_token_source()}')}"
        )
    print()


def _render_conflicts(url: str, issues: List[str]) -> None:
    """[Config Conflicts]: env/file materialization drift and stale tool literals.

    Real drift is a generated MCP config that no longer matches the env-first
    effective URL/token, or a materialized ``~/.mem-mesh`` file that is out of
    sync with env. Server-private data-dir token differences are not MCP drift.
    """
    print(header("[Config Conflicts]"))
    drift: List[str] = []

    env_url = (os.environ.get("MEM_MESH_API_URL") or "").rstrip("/")
    legacy_env_url = (os.environ.get("API_URL") or "").rstrip("/")
    file_url = (_read_config_file_url() or "").rstrip("/")
    effective_url = (env_url or legacy_env_url or file_url or url).rstrip("/")
    effective_tok = _effective_hook_token()
    effective_tok_source = _effective_hook_token_source() or "effective hook token"

    if legacy_env_url and not env_url:
        drift.append("API_URL legacy env is set — prefer MEM_MESH_API_URL")
    if env_url and file_url and env_url != file_url:
        drift.append(
            "MEM_MESH_API_URL differs from ~/.mem-mesh/api_url — materialize with "
            "mem-mesh mcp config --url <url>"
        )
    if env_url and not file_url:
        drift.append(
            "~/.mem-mesh/api_url missing while MEM_MESH_API_URL is set — materialize with "
            "mem-mesh mcp config --url <url>"
        )

    env_tok = _env_hook_token()
    file_tok = _materialized_hook_token()
    if env_tok and file_tok and env_tok != file_tok:
        drift.append(
            "MEM_MESH_HOOK_TOKEN differs from ~/.mem-mesh/hook_token — materialize with "
            "mem-mesh mcp config --auth"
        )
    if env_tok and not file_tok:
        drift.append(
            "~/.mem-mesh/hook_token missing while MEM_MESH_HOOK_TOKEN is set — materialize with "
            "mem-mesh mcp config --auth"
        )

    # --- per-tool: generated config vs env-first effective config ---
    for t in collect_mcp_status(url):
        if not (t.configured and t.mode == "http" and t.entry):
            continue
        entry_url = (t.entry.get("url") or "").rsplit("/mcp/sse", 1)[0].rstrip("/")
        if effective_url and entry_url and entry_url != effective_url:
            drift.append(
                f"{t.name}: configured url {entry_url} differs from "
                f"effective url {effective_url}"
            )
        if _entry_references_token_env(t.entry):
            drift.append(
                f"{t.name}: Authorization references a ${{...}} env var — "
                f"re-stamp the effective token as a literal header"
            )
        else:
            literal = _entry_literal_token(t.entry)
            if literal and effective_tok and literal != effective_tok:
                drift.append(
                    f"{t.name}: stamped token is stale (differs from "
                    f"{effective_tok_source}) — re-stamp"
                )

    if drift:
        for d in drift:
            print(f"  {warn('drift:')} {d}")
        print(
            f"  {dim('→ materialize/re-stamp: mem-mesh mcp config --auth (add --url/--token when changing values), ')}"
            f"{dim('then restart clients.')}"
        )
        issues.append(f"{len(drift)} config drift — see Config Conflicts")
    else:
        print(f"  {ok('generated configs match the env-first effective config')}")
    print()


def _render_hooks_summary(issues: List[str]) -> None:
    """[Hooks]: compact per-tool summary; defer the deep checks to `hooks doctor`."""
    print(header("[Hooks]"))
    # The stop-hook profile (minimal/standard/enhanced) only applies to
    # Claude/Codex, which install profile-specific stop scripts (stop /
    # stop-decide / stop-enhanced). Kiro and Cursor use their OWN native stop
    # hook (both written as mem-mesh-stop.sh), so the filename-based detector
    # would mislabel them "minimal" — show "native stop hook" instead.
    for label, hooks_dir, settings_path, has_profile in [
        ("Claude Code", CLAUDE_HOOKS_DIR, CLAUDE_SETTINGS, True),
        ("Kiro", KIRO_SCRIPTS_DIR, KIRO_SETTINGS, False),
        ("Cursor", CURSOR_HOOKS_DIR, CURSOR_SETTINGS, False),
        ("Codex", CODEX_HOOKS_DIR, None, True),
        (
            "Antigravity IDE",
            ANTIGRAVITY_HOOKS_DIR,
            ANTIGRAVITY_HOOKS_FILE,
            False,
        ),
        ("agy CLI", AGY_HOOKS_DIR, AGY_HOOKS_FILE, False),
    ]:
        if not hooks_dir.exists():
            print(f"  {label:12s}  {dim('no hooks installed')}")
            continue
        count = len(list(hooks_dir.glob("mem-mesh-*.sh")))
        if count == 0:
            print(f"  {label:12s}  {dim('no hooks installed')}")
            continue
        if has_profile:
            profile = _detect_profile(hooks_dir, settings_path)
            note = f"({profile} profile)"
        else:
            note = "(native stop hook)"
        if label == "Codex":
            from app.cli.hooks.doctor import _check_codex_hooks_json

            codex_issues = _check_codex_hooks_json(CODEX_HOOKS_FILE, CODEX_HOOKS_DIR)
            if codex_issues:
                print(
                    f"  {label:12s}  {err(f'{count} scripts, inactive config')} {dim(note)}"
                )
                issues.extend(codex_issues)
                continue
        elif label == "Kiro":
            from app.cli.hooks.doctor import _check_kiro_native_hook

            kiro_issues = _check_kiro_native_hook(KIRO_HOOKS_DIR, KIRO_SCRIPTS_DIR)
            if kiro_issues:
                print(
                    f"  {label:12s}  {err(f'{count} scripts, inactive config')} {dim(note)}"
                )
                issues.extend(kiro_issues)
                continue
        elif label in ("Antigravity IDE", "agy CLI"):
            from app.cli.hooks.doctor import _check_antigravity_hooks_json

            ag_issues = _check_antigravity_hooks_json(
                settings_path or ANTIGRAVITY_HOOKS_FILE,
                hooks_dir,
                label=label,
            )
            if ag_issues:
                print(
                    f"  {label:12s}  {err(f'{count} scripts, inactive config')} {dim(note)}"
                )
                issues.extend(ag_issues)
                continue
        print(f"  {label:12s}  {ok(f'{count} hooks')} {dim(note)}")
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
    _render_conflicts(url, issues)
    _render_hooks_summary(issues)

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
