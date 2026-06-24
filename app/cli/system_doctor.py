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
from app.cli.codex_config import CODEX_HOOKS_DIR
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
    """[Hook Token]: source + masked preview.

    Under option 2 the ``~/.mem-mesh/hook_token`` file (or the data-dir token) is
    canonical — hooks read it directly and each tool config carries the stamped
    literal. A ``MEM_MESH_HOOK_TOKEN`` env var is now residual and only shadows
    the file; it is shown here but the issue is counted once under
    [Config Conflicts].
    """
    print(header("[Hook Token]"))
    token = collect_token_status()
    if token.source in ("data_file", "legacy_file"):
        print(
            f"  Source: {ok('file SSOT (<data dir>/hook_token | ~/.mem-mesh/hook_token)')}"
            f"  {info(token.masked)}"
        )
        print(
            f"  {dim('Canonical — hooks read this file, tools carry the stamped literal.')}"
        )
    elif token.source == "env":
        print(
            f"  Source: {warn('MEM_MESH_HOOK_TOKEN env (residual)')}  {info(token.masked)}"
        )
        print(
            f"  {dim('Option 2 removed env reliance — unset it; the ~/.mem-mesh file is canonical.')}"
        )
    else:
        print(f"  Source: {dim('not set')}")
        print(
            f"  {dim('The server bootstraps one at startup (<data dir>/hook_token).')}"
        )
    print()


def _entry_has_auth_header(entry: Optional[dict]) -> bool:
    """True if an http MCP entry carries an Authorization header."""
    if not entry:
        return False
    headers = entry.get("headers") or {}
    return bool(headers.get("Authorization"))


def _file_canonical_token() -> Optional[str]:
    """The canonical hook token from the file SSOT, ignoring the env.

    Option 2 makes the on-disk token (``<data dir>/hook_token`` →
    ``~/.mem-mesh/hook_token``) the source of truth. ``resolve_hook_token()``
    can't be used for the canonical comparison because it consults the env
    first, so a residual ``MEM_MESH_HOOK_TOKEN`` would shadow the file value and
    poison the "is the stamped literal stale?" check.
    """
    from app.core.config import (
        HOOK_TOKEN_FILE,
        _data_dir_hook_token_file,
        _read_token_file,
    )

    return _read_token_file(_data_dir_hook_token_file()) or _read_token_file(
        HOOK_TOKEN_FILE
    )


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

    Option 2 removed all env reliance, so any ``${...}`` reference in the header
    is *always* a defect: there is no env to substitute, the MCP client sends an
    empty token, and the server 401s. The header must carry the literal token
    (re-stamp it with ``mem-mesh mcp config --auth``). The name is kept for
    call-site stability; the meaning is now "uses an env reference", which is
    unconditionally a fault.
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
        # 2) Header references ${...}: option 2 removed the env, so the client
        # substitutes an empty value and the server 401s. Always a defect now,
        # independent of whether the server is currently enforcing auth.
        elif t.mode == "http" and _entry_references_token_env(t.entry):
            issues.append(
                f"MCP for {t.name}: Authorization header references a ${{...}} "
                f"env var — env reliance was removed, so an empty token is sent "
                f"and the server will 401; it must carry the literal token"
            )
            print(
                f"     {warn('!')} {dim('re-stamp the literal: mem-mesh mcp config --auth, then restart the client')}"
            )
        # 3) Literal token present but stale (differs from the file SSOT).
        elif (
            t.mode == "http"
            and _entry_literal_token(t.entry)
            and _file_canonical_token()
            and _entry_literal_token(t.entry) != _file_canonical_token()
        ):
            issues.append(
                f"MCP for {t.name}: stamped token is stale "
                f"(differs from ~/.mem-mesh/hook_token) — re-stamp"
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
    """[SSOT]: the ~/.mem-mesh files are canonical; tools carry stamped literals.

    Under option 2 there is no env source of truth: ``~/.mem-mesh/api_url`` and
    ``~/.mem-mesh/hook_token`` (or the data-dir token) are canonical. Hooks read
    those files directly and each tool config carries the stamped literal token.
    Any ``MEM_MESH_*`` env var is residual and only shadows the file — shown here
    but counted once under [Config Conflicts].
    """
    from app.core.redaction import mask_secret

    print(
        header("[SSOT]")
        + dim("  ~/.mem-mesh files are canonical — tools carry the stamped literals")
    )

    # api_url — the file is canonical; .sh hooks read it directly.
    file_url = _read_config_file_url()
    if file_url:
        print(f"  api_url      {info(file_url)}  {ok('(~/.mem-mesh/api_url)')}")
    else:
        print(
            f"  api_url      {dim('not set')} "
            f"{dim('— run: mem-mesh mcp config --url <url>')}"
        )
    env_url = (
        os.environ.get("MEM_MESH_API_URL") or os.environ.get("API_URL") or ""
    ).strip()
    if env_url:
        print(f"               {warn('! MEM_MESH_API_URL env is residual — unset it')}")

    # hook_token — the file is canonical; tools carry the stamped literal.
    token_value = _file_canonical_token()
    if token_value:
        print(f"  hook_token   {info(mask_secret(token_value))}  {ok('(file SSOT)')}")
    else:
        print(
            f"  hook_token   {dim('not set')} "
            f"{dim('— server bootstraps at startup')}"
        )
    env_tok = (os.environ.get("MEM_MESH_HOOK_TOKEN") or "").strip()
    if env_tok and env_tok != token_value:
        print(
            f"               {warn('! MEM_MESH_HOOK_TOKEN env is residual, shadows the file')}"
        )
    print()


def _render_conflicts(url: str, issues: List[str]) -> None:
    """[Config Conflicts]: the ~/.mem-mesh files are canonical; flag stale tool
    literals and residual env vars.

    Option 2 makes ``~/.mem-mesh/{api_url,hook_token}`` the source of truth and
    bakes a literal token into each tool config. Real drift is therefore a
    *stale stamped literal* — a rotated token or a moved URL that a tool config
    still carries the old value of — or a ``${...}`` env reference that can no
    longer resolve. ``MEM_MESH_*`` env vars are residual under option 2 and only
    shadow the files, so they are flagged here too, and counted *once* here so
    [Hook Token]/[SSOT] can show their warnings without inflating the total.
    """
    print(header("[Config Conflicts]"))
    drift: List[str] = []

    file_url = (_read_config_file_url() or "").rstrip("/")
    file_tok = _file_canonical_token()

    # --- per-tool: stamped literal vs the ~/.mem-mesh SSOT ---
    for t in collect_mcp_status(url):
        if not (t.configured and t.mode == "http" and t.entry):
            continue
        entry_url = (t.entry.get("url") or "").rsplit("/mcp/sse", 1)[0].rstrip("/")
        if file_url and entry_url and entry_url != file_url:
            drift.append(
                f"{t.name}: configured url {entry_url} differs from "
                f"~/.mem-mesh/api_url={file_url}"
            )
        if _entry_references_token_env(t.entry):
            drift.append(
                f"{t.name}: Authorization references a ${{...}} env var — env "
                f"reliance was removed; re-stamp the literal token"
            )
        else:
            literal = _entry_literal_token(t.entry)
            if literal and file_tok and literal != file_tok:
                drift.append(
                    f"{t.name}: stamped token is stale (differs from "
                    f"~/.mem-mesh/hook_token) — a rotated token isn't carried"
                )

    # --- residual MEM_MESH_* env vars (no longer a source under option 2) ---
    for var in ("MEM_MESH_API_URL", "API_URL", "MEM_MESH_HOOK_TOKEN"):
        if (os.environ.get(var) or "").strip():
            drift.append(f"{var} env is residual under option 2 — unset it")

    if drift:
        for d in drift:
            print(f"  {warn('drift:')} {d}")
        print(
            f"  {dim('→ re-stamp: mem-mesh mcp config (add --url/--token to move the SSOT), ')}"
            f"{dim('then restart clients.')}"
        )
        issues.append(f"{len(drift)} config drift — see Config Conflicts")
    else:
        print(f"  {ok('tool literals match the ~/.mem-mesh SSOT')}")
    print()


def _render_hooks_summary() -> None:
    """[Hooks]: compact per-tool summary; defer the deep checks to `hooks doctor`."""
    print(header("[Hooks]"))
    # The stop-hook profile (minimal/standard/enhanced) only applies to
    # Claude/Codex, which install profile-specific stop scripts (stop /
    # stop-decide / stop-enhanced). Kiro and Cursor use their OWN native stop
    # hook (both written as mem-mesh-stop.sh), so the filename-based detector
    # would mislabel them "minimal" — show "native stop hook" instead.
    for label, hooks_dir, settings_path, has_profile in [
        ("Claude Code", CLAUDE_HOOKS_DIR, CLAUDE_SETTINGS, True),
        ("Kiro", KIRO_HOOKS_DIR, KIRO_SETTINGS, False),
        ("Cursor", CURSOR_HOOKS_DIR, CURSOR_SETTINGS, False),
        ("Codex", CODEX_HOOKS_DIR, None, True),
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
