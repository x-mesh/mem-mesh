"""Onboarding wizard for mem-mesh.

Performs 3-step setup:
1. API server setup (check connectivity, or install via Docker/source)
2. Hook installation
3. MCP configuration check
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from app.cli.hooks.colors import bold, dim, err, header, info, ok, warn
from app.cli.hooks.constants import CLAUDE_HOOKS_DIR, DEFAULT_URL
from app.cli.hooks.status import (
    check_connectivity,
    probe_api,
    resolve_api_url,
)

TARGET_LABELS = {
    "claude": "Claude Code",
    "kiro": "Kiro",
    "cursor": "Cursor",
    "codex": "Codex",
    "antigravity": "Antigravity IDE",
    "agy": "agy CLI",
}

TARGET_ORDER = ["claude", "kiro", "cursor", "codex", "antigravity", "agy"]

# How many times the interactive installer re-prompts for the hook token after a
# 401 before giving up and skipping hook install (fail-fast on a wrong token).
AUTH_TOKEN_RETRIES = 5


def _client_effective_hook_token() -> Tuple[Optional[str], str]:
    """Return the env-first client token and its source.

    The onboarding wizard uses this for prompts and JSON status. It intentionally
    ignores the server-private data-dir token: MCP configs and shell hooks must
    be stamped from the operator env token or the materialized ~/.mem-mesh file.
    """
    import os

    env_token = (os.environ.get("MEM_MESH_HOOK_TOKEN") or "").strip()
    if env_token:
        return env_token, "env"
    try:
        from app.core.config import HOOK_TOKEN_FILE, _read_token_file

        file_token = _read_token_file(HOOK_TOKEN_FILE)
        if file_token:
            return file_token, "file"
    except Exception:
        pass
    return None, "none"


def _detect_targets() -> list[str]:
    """Auto-detect which tools to install hooks for."""
    targets = []
    if CLAUDE_HOOKS_DIR.parent.exists():
        targets.append("claude")
    kiro_dir = Path.home() / ".kiro"
    if kiro_dir.exists():
        targets.append("kiro")
    cursor_dir = Path.home() / ".cursor"
    if cursor_dir.exists():
        targets.append("cursor")
    codex_dir = Path.home() / ".codex"
    if codex_dir.exists():
        targets.append("codex")
    antigravity_dirs = [
        Path.home() / ".gemini" / "antigravity",
        Path.home() / ".antigravity",
        Path("/Applications/Antigravity.app"),
        Path("/Applications/Antigravity IDE.app"),
    ]
    if any(path.exists() for path in antigravity_dirs):
        targets.append("antigravity")
    agy_dir = Path.home() / ".gemini" / "antigravity-cli"
    if agy_dir.exists() or shutil.which("agy"):
        targets.append("agy")

    return targets


def _detect_target() -> str:
    """Backward-compatible single target detector."""
    targets = _detect_targets()
    if not targets:
        return "claude"
    return targets[0] if len(targets) == 1 else "all"


def _format_targets(targets: Union[list[str], str]) -> str:
    if isinstance(targets, str):
        if targets == "all":
            return "all supported tools"
        return TARGET_LABELS.get(targets, targets)
    if not targets:
        return "none"
    return ", ".join(TARGET_LABELS.get(target, target) for target in targets)


def _resolve_hook_targets(target: str, yes: bool) -> tuple[list[str], str]:
    """Resolve the CLI target into concrete hook install targets and a label."""
    if target != "auto":
        if target == "all":
            return TARGET_ORDER.copy(), "all supported tools"
        return [target], _format_targets(target)

    detected = _detect_targets()
    if not detected:
        return ["claude"], "Claude Code (fallback; no supported tool dirs detected)"
    if len(detected) == 1 or yes:
        return detected, _format_targets(detected)

    print(f"  Detected tools: {info(_format_targets(detected))}")
    print()
    options = [
        f"All detected ({_format_targets(detected)})",
        *[TARGET_LABELS.get(target_key, target_key) for target_key in detected],
        "All supported tools",
    ]
    chosen = _prompt_choice("Install hooks for [1]:", options, default=options[0])
    if chosen == options[0]:
        return detected, _format_targets(detected)
    if chosen == options[-1]:
        return TARGET_ORDER.copy(), "all supported tools"
    selected = detected[options.index(chosen) - 1]
    return [selected], _format_targets(selected)


def _has_docker() -> bool:
    """Check if docker and docker-compose are available."""
    return shutil.which("docker") is not None


def _has_uvx() -> bool:
    """Check if uvx (from astral-sh/uv) is available."""
    return shutil.which("uvx") is not None


def _warm_uvx_cache() -> bool:
    """Pre-download mem-mesh[server] into uv cache so first MCP spawn is fast.

    Returns True if warm-up succeeded.
    """
    print(
        f"  {dim('Warming uv cache (downloads mem-mesh[server] — can take a minute on first run)...')}"
    )
    try:
        result = subprocess.run(
            ["uvx", "--from", "mem-mesh[server]", "mem-mesh", "--help"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode == 0:
            print(
                f"  {ok('uv cache warmed — MCP tools will spawn mem-mesh instantly.')}"
            )
            return True
        print(
            f"  {warn('uv cache warm-up returned non-zero; first MCP call may be slow.')}"
        )
        for line in result.stderr.strip().splitlines()[-3:]:
            print(f"    {dim(line)}")
        return False
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"  {warn(f'uv cache warm-up skipped: {exc}')}")
        return False


def _find_compose_file() -> Optional[Path]:
    """Find docker-compose.yml in current working directory."""
    candidates = [
        Path.cwd() / "docker-compose.yml",
        Path.cwd() / "docker-compose.mem-mesh.yml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _prompt_choice(prompt: str, options: list[str], default: str = "") -> str:
    """Simple numbered choice prompt."""
    for i, opt in enumerate(options, 1):
        print(f"    {bold(str(i))}. {opt}")
    while True:
        raw = input(f"  {prompt} ").strip()
        if not raw and default:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print(f"    Enter 1-{len(options)}")


# Embedding model choices for onboarding (first entry is the default)
EMBEDDING_MODELS = [
    (
        "dragonkue/snowflake-arctic-embed-l-v2.0-ko",
        1024,
        "Recommended. Korean retrieval SOTA (MTEB-ko #1, NDCG@10 0.740), ~2.2GB",
    ),
    (
        "nlpai-lab/KURE-v1",
        1024,
        "Korean retrieval (BGE-M3 fine-tune), ~2.2GB",
    ),
    (
        "intfloat/multilingual-e5-large",
        1024,
        "Balanced multilingual, ~1.1GB",
    ),
    (
        "intfloat/multilingual-e5-base",
        768,
        "Lighter multilingual, ~470MB",
    ),
    (
        "intfloat/multilingual-e5-small",
        384,
        "Fastest multilingual, ~118MB",
    ),
    (
        "all-MiniLM-L6-v2",
        384,
        "English-only, lightweight, ~80MB",
    ),
]


def _prompt_value(prompt: str, default: str) -> str:
    """Prompt for a value with a default."""
    raw = input(f"  {prompt} [{bold(default)}]: ").strip()
    return raw if raw else default


def _prompt_token(current: Optional[str]) -> Optional[str]:
    """Prompt for the hook token, showing the current one masked as the default.

    Enter keeps the current value (still displayed, masked, so the operator sees
    what is in effect); a pasted value replaces it. The secret itself is never
    echoed in full.
    """
    from app.core.redaction import mask_secret

    shown = mask_secret(current) if current else "none"
    raw = input(f"  Hook token [{bold(shown)}]: ").strip()
    return raw if raw else current


def _auth_probe(url: str, token: Optional[str]) -> Optional[int]:
    """POST the hook endpoint with an explicit token; return the HTTP status.

    Returns the status code (200 = token accepted, 401 = rejected/mismatch) or
    ``None`` when the server is unreachable. Tests the *given* token directly so
    the interactive retry loop does not depend on resolution order/env shadowing.
    """
    from app.cli.hooks.doctor import _http

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    code, _ = _http(
        "POST",
        f"{url.rstrip('/')}/api/hooks/claude/session-start",
        headers=headers,
        data=b"{}",
    )
    return code


def _prompt_docker_options() -> dict:
    """Interactive Docker configuration prompts."""
    print()
    print(f"  {header('Docker Configuration')}")
    print()

    # --- Port ---
    port = _prompt_value("Port", "8000")
    try:
        port = int(port)
    except ValueError:
        port = 8000
    print()

    # --- Embedding model ---
    print(f"  {bold('Embedding Model')}")
    print(f"  {dim('Determines search quality and resource usage.')}")
    print()
    model_options = []
    for name, dim_size, desc in EMBEDDING_MODELS:
        model_options.append(f"{name} {dim(f'({desc}, dim={dim_size})')}")
    chosen_model_opt = _prompt_choice(
        "Choose [1]: ", model_options, default=model_options[0]
    )
    model_idx = model_options.index(chosen_model_opt)
    model_name, embedding_dim, _ = EMBEDDING_MODELS[model_idx]
    print()

    # --- Volume type ---
    print(f"  {bold('Data Storage')}")
    print(f"  {dim('Where to store the SQLite database and model cache.')}")
    print()
    volume_options = [
        f"Docker volume {dim('(managed by Docker, portable)')}",
        f"Local directory {dim('(./mem-mesh-data in current dir)')}",
    ]
    chosen_volume = _prompt_choice(
        "Choose [1]: ", volume_options, default=volume_options[0]
    )
    use_local_volume = volume_options.index(chosen_volume) == 1
    print()

    return {
        "port": port,
        "model_name": model_name,
        "embedding_dim": embedding_dim,
        "use_local_volume": use_local_volume,
    }


def _generate_compose_file(
    port: int = 8000,
    model_name: str = "dragonkue/snowflake-arctic-embed-l-v2.0-ko",
    embedding_dim: int = 1024,
    use_local_volume: bool = False,
) -> Path:
    """Generate a docker-compose.yml in the current directory."""
    if use_local_volume:
        volume_line = "      - ./mem-mesh-data:/app/data"
        volumes_section = ""
    else:
        volume_line = "      - mem-mesh-data:/app/data"
        volumes_section = "\nvolumes:\n  mem-mesh-data:\n"

    content = f"""\
# Generated by: mem-mesh install
# mem-mesh API server (Docker)
services:
  mem-mesh:
    image: xmesh/mem-mesh:latest
    container_name: mem-mesh
    ports:
      - "{port}:8000"
    volumes:
{volume_line}
    environment:
      - MEM_MESH_DATABASE_PATH=/app/data/memories.db
      - MEM_MESH_EMBEDDING_MODEL={model_name}
      - MEM_MESH_EMBEDDING_DIM={embedding_dim}
      - MEM_MESH_LOG_LEVEL=INFO
      - MEM_MESH_SERVER_HOST=0.0.0.0
      - MEM_MESH_SERVER_PORT=8000
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
{volumes_section}"""

    compose_path = Path.cwd() / "docker-compose.mem-mesh.yml"
    compose_path.write_text(content, encoding="utf-8")
    return compose_path


def _setup_server_docker(url: str) -> tuple[bool, str]:
    """Set up server via Docker."""
    import time

    compose_file = _find_compose_file()

    if not compose_file:
        docker_opts = _prompt_docker_options()

        print(f"  {dim('Generating docker-compose.mem-mesh.yml...')}")
        compose_file = _generate_compose_file(**docker_opts)
        print(f"  Created: {ok(str(compose_file))}")

        # Update URL if port changed
        port = docker_opts["port"]
        if port != 8000:
            url = f"http://localhost:{port}"

    print(f"  Compose file: {info(str(compose_file))}")
    print(f"  {dim('Running: docker compose up -d')}")

    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "up", "-d"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  {err('Docker startup failed')}")
        for line in result.stderr.strip().splitlines()[-3:]:
            print(f"    {dim(line)}")
        return False, url

    print(f"  {ok('Docker containers started')}")

    print(f"  {dim('Waiting for server to be ready...')}")
    for _attempt in range(5):
        time.sleep(2)
        reachable, msg = check_connectivity(url)
        if reachable:
            print(f"  {ok(f'Server ready ({msg})')}")
            return True, url
    print(f"  {warn('Server started but not yet reachable. It may need more time.')}")
    return False, url


def _setup_server_source() -> tuple[bool, str]:
    """Set up server via pip install mem-mesh[server]."""
    print(f"  {dim('Running: pip install mem-mesh[server]')}")

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "mem-mesh[server]"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  {err('Installation failed')}")
        for line in result.stderr.strip().splitlines()[-3:]:
            print(f"    {dim(line)}")
        return False, DEFAULT_URL

    print(f"  {ok('Server package installed')}")
    print()
    print(f"  {bold('To start the server:')}")
    print(f"    {info('mem-mesh serve')}")
    print(f"    {dim('or: mem-mesh serve --reload  (development mode)')}")
    return False, DEFAULT_URL  # Not running yet, user must start manually


class _OnboardingAbort(Exception):
    """Raised by ``_fail`` under json mode so the JSON result is still emitted.

    In human mode ``_fail`` keeps the historical ``sys.exit(1)`` behavior; in
    json mode it raises this instead, letting ``cmd_onboarding`` catch it and
    still print the structured result before exiting non-zero.
    """


def _fail(message: str, force: bool, json_mode: bool = False) -> None:
    """Print error and exit unless --force is set."""
    print(f"  {err(message)}")
    if force:
        print(f"  {dim('--force: continuing despite error')}")
        return
    if json_mode:
        raise _OnboardingAbort(message)
    print(f"  {dim('Use --force to continue despite errors.')}")
    sys.exit(1)


def _pkg_version() -> str:
    """Best-effort installed package version for json output."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("mem-mesh")
        except PackageNotFoundError:
            return "unknown"
    except Exception:
        return "unknown"


def _hook_token_status() -> Dict[str, Any]:
    """Detect the hook auth token for onboarding display/JSON (no secret leaked).

    Env is the operator SSOT. ``~/.mem-mesh/hook_token`` is the materialized
    fallback/cache used by shell hooks and MCP config stamping. Server-private
    data-dir state is not reported here as client-ready auth.
    """
    _, source = _client_effective_hook_token()
    return {"status": source}


def _build_next_actions(result: Dict[str, Any]) -> None:
    """Populate result['next_actions'] mirroring _print_summary hints."""
    actions = result["next_actions"]
    server = result["steps"]["server"]
    serve_cmd = 'uvx --from "mem-mesh[server]" mem-mesh serve'
    if server.get("mcp_mode") == "uvx":
        actions.append(
            "Restart your MCP client (Codex / Cursor / Claude Desktop / Kiro). "
            "First MCP call downloads mem-mesh[server] from the uv cache."
        )
        actions.append(f"Run `{serve_cmd}` to enable the dashboard + hooks.")
    elif not server.get("reachable"):
        actions.append(f"Start the server: `{serve_cmd}` (or `docker compose up -d`).")
    # The file token is baked into every tool config as a literal bearer header
    # at install time, so a "file" status is fully configured — no extra action.
    actions.append("Run `mem-mesh status` for a full system check.")
    actions.append("Run `mem-mesh hooks doctor` for hook diagnostics.")


def cmd_onboarding(
    url: Optional[str] = None,
    target: str = "auto",
    profile: str = "standard",
    yes: bool = False,
    force: bool = False,
    json_mode: bool = False,
) -> None:
    """Run the onboarding wizard.

    With ``json_mode`` the wizard runs non-interactively (implies ``yes``),
    suppresses the human-readable progress, and emits a single JSON document
    describing each step's outcome — the machine entry point for LLM agents
    (``mem-mesh --json`` / ``mem-mesh install --json``).
    """
    if json_mode:
        yes = True

    result: Dict[str, Any] = {
        "tool": "mem-mesh",
        "command": "onboarding",
        "version": _pkg_version(),
        "ok": True,
        "interactive": not yes,
        "steps": {
            "server": {
                "status": "unknown",
                "url": None,
                "url_source": None,
                "reachable": False,
                "mcp_mode": None,
                "message": None,
            },
            "hooks": {
                "status": "skipped",
                "targets": [],
                "target_label": None,
                "profile": profile,
                "installed": False,
                "error": None,
            },
            "mcp": {"status": "skipped"},
        },
        "hook_token": {"status": "none"},
        "next_actions": [],
        "errors": [],
    }

    # In json mode, swallow the human-readable progress so stdout stays a clean
    # single JSON document, but always emit the result (even on a fatal step
    # error, surfaced as _OnboardingAbort) via the post-try block below.
    sink = io.StringIO()
    ctx: Any = (
        contextlib.redirect_stdout(sink) if json_mode else contextlib.nullcontext()
    )
    aborted = False
    try:
        with ctx:
            _onboarding_steps(url, target, profile, yes, force, json_mode, result)
    except _OnboardingAbort:
        aborted = True

    if json_mode:
        result["ok"] = (not aborted) and not result["errors"]
        _build_next_actions(result)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["ok"] else 1)


def _onboarding_steps(
    url: Optional[str],
    target: str,
    profile: str,
    yes: bool,
    force: bool,
    json_mode: bool,
    result: Dict[str, Any],
) -> None:
    """Run the 3 onboarding steps, recording outcomes into ``result``."""
    print()
    print(header("=== mem-mesh setup ==="))
    print()

    # --- Step 1: Server setup ---
    print(bold("[1/3] API Server"))
    server = result["steps"]["server"]

    if url:
        resolved_url = url.rstrip("/")
        source = "command line"
    else:
        resolved_url, source = resolve_api_url()

    # Interactive URL: pre-fill the current value as the default so Enter keeps
    # it (and still shows it). An explicit --url or --yes skips the prompt.
    if not yes and not url:
        print(f"  {dim(f'current: {resolved_url} (from {source})')}")
        resolved_url = _prompt_value("API server URL", resolved_url).rstrip("/")
        source = "entered"

    # Materialize the chosen URL now so hooks + MCP resolve the same server. Local
    # mode renders a path, not a URL, so skip it.
    from app.cli.install_hooks import _ensure_api_url

    _ensure_api_url(resolved_url)

    server["url"] = resolved_url
    server["url_source"] = source
    print(f"  URL: {info(resolved_url)} {dim(f'(from {source})')}")

    probe = probe_api(resolved_url)
    reachable = probe.ok
    message = probe.message
    preferred_mcp_mode: Optional[str] = None
    server["message"] = message

    if probe.ok:
        server["status"] = "reachable"
        server["reachable"] = True
        print(f"  Status: {ok(message)}")
    elif probe.auth_required:
        # The server is UP but gated by auth (e.g. behind a reverse proxy that
        # also guards /health). Treating this as "no server" used to push the
        # wizard into reinstall/uvx fallbacks and silently flip a working HTTP
        # MCP entry to a local uvx one. Instead: keep going against this server.
        server["status"] = "auth_required"
        print(f"  Status: {warn(message)}")
        print(
            f"  {dim('Server is up — set the hook token in the dashboard (Security & Tokens), then re-run install, or check your proxy auth.')}"
        )
    else:
        server["status"] = "unreachable"
        print(f"  Status: {err(message)}")
        print()

        if yes:
            server["status"] = "skipped"
            if _has_uvx():
                print(dim("  (--yes: using uvx for MCP; skipping API server setup)"))
                # Skip the (up to 600s) cache warm-up under json mode so agent
                # calls stay fast; the first real MCP call will download it.
                if not json_mode:
                    _warm_uvx_cache()
                preferred_mcp_mode = "uvx"
            else:
                print(dim("  (--yes: skipping server setup)"))
        else:
            # Ask how to set up the server
            print(
                f"  {warn('No running server detected. How would you like to set it up?')}"
            )
            print()

            has_uvx = _has_uvx()
            has_docker = _has_docker()
            compose_exists = _find_compose_file() is not None

            options = []
            option_keys = []

            if has_uvx:
                options.append(
                    f"uvx {dim('(recommended — MCP clients auto-spawn mem-mesh, no server to manage)')}"
                )
                option_keys.append("uvx")

            if has_docker and compose_exists:
                options.append(f"Docker {dim('(docker compose up -d)')}")
                option_keys.append("docker")
            elif has_docker:
                options.append(f"Docker {dim('(docker-compose.yml not found in cwd)')}")
                option_keys.append("docker")

            options.append(f"Source install {dim('(pip install mem-mesh[server])')}")
            option_keys.append("source")

            options.append(f"Skip {dim('(set up server later)')}")
            option_keys.append("skip")

            chosen = _prompt_choice(
                f"Choose [{1}]: ",
                options,
                default=options[0],
            )
            chosen_key = option_keys[options.index(chosen)]

            print()
            if chosen_key == "uvx":
                _warm_uvx_cache()
                preferred_mcp_mode = "uvx"
                server["status"] = "skipped"
                # uvx mode does not require a standing server for MCP,
                # but hooks + dashboard still do. Reachable stays False.
            elif chosen_key == "docker":
                reachable, resolved_url = _setup_server_docker(resolved_url)
                if reachable:
                    server["status"] = "installed"
                    server["reachable"] = True
                    server["url"] = resolved_url
                else:
                    result["errors"].append("Server setup failed.")
                    _fail("Server setup failed.", force, json_mode)
            elif chosen_key == "source":
                reachable, resolved_url = _setup_server_source()
                server["status"] = "installed"
                # Source install doesn't start server, not a failure
            else:
                server["status"] = "skipped"

    server["mcp_mode"] = preferred_mcp_mode

    # Auth token: prompt interactively (pre-filled masked), persist to the
    # materialized ~/.mem-mesh cache, then verify against the server. On a 401
    # mismatch, re-prompt up to
    # AUTH_TOKEN_RETRIES times; if it never authenticates, block hook install so
    # we never leave installed-but-401 hooks behind (fail fast — the trap this
    # whole flow fixes).
    from app.cli.install_hooks import _write_hook_token

    auth_blocked = False
    current_token, current_token_source = _client_effective_hook_token()

    if not yes:
        chosen = _prompt_token(current_token)
        if chosen and chosen != current_token:
            _write_hook_token(chosen)
            # Keep the accepted interactive value authoritative for this
            # process, even if the parent shell exported a stale env token.
            os.environ["MEM_MESH_HOOK_TOKEN"] = chosen
            current_token_source = "env"
        current_token = chosen
    elif current_token and current_token_source == "env":
        # Non-interactive first setup still materializes the operator env token so
        # shell hooks and future MCP re-stamps have the same local fallback.
        _write_hook_token(current_token)

    # Verify only when the server is actually up (reachable or auth-gated).
    # Probe the hook endpoint with the exact client token that hooks/MCP will
    # carry. Source does not matter: env and materialized file tokens can both be
    # stale after rotation.
    if probe.ok or probe.auth_required:
        for attempt in range(AUTH_TOKEN_RETRIES):
            code = _auth_probe(resolved_url, current_token)
            if code is None:
                print(f"  Auth test: {dim('server unreachable — skipped')}")
                break
            if code == 200:
                if current_token:
                    print(f"  Auth test: {ok('200 — token accepted')}")
                else:
                    print(f"  Auth test: {ok('200 — no token required')}")
                break
            if code == 401:
                if current_token:
                    print(f"  Auth test: {err('401 — token rejected by server')}")
                else:
                    print(f"  Auth test: {err('401 — hook token required')}")
                if yes or attempt == AUTH_TOKEN_RETRIES - 1:
                    auth_blocked = True
                    break
                retry = _prompt_token(current_token)
                if retry and retry != current_token:
                    _write_hook_token(retry)
                    os.environ["MEM_MESH_HOOK_TOKEN"] = retry
                    current_token_source = "env"
                current_token = retry
                continue
            print(f"  Auth test: {dim(f'HTTP {code}')}")
            break

    if auth_blocked:
        print(
            f"  {warn('Token never authenticated — hooks will be skipped (they would 401).')}"
        )
        print(
            f"  {dim('Fix the token (remote dashboard → Security & Tokens), then re-run install.')}"
        )

    token_info = _hook_token_status()
    result["hook_token"] = token_info
    if token_info["status"] in ("env", "file"):
        print(
            f"  Auth token: {ok('hook token ready')} "
            f"{dim('(baked into tool configs)')}"
        )
    else:
        print(
            f"  Auth token: {dim('not set')} "
            f"{dim('(only needed for an authenticated server)')}"
        )
    print()

    # --- Step 2: MCP config ---
    # MCP is the primary integration (the memory tools) and can work via uvx
    # without a running server, so it is configured before the optional hooks.
    from app.cli.mcp_config import run_mcp_setup

    mcp_summary = (
        run_mcp_setup(
            url=resolved_url,
            yes=yes,
            preferred_mode=preferred_mcp_mode,
            server_reachable=probe.ok or probe.auth_required,
            with_auth=bool(current_token) and not auth_blocked,
            token=current_token if current_token and not auth_blocked else "",
            step_label="[2/3]",
        )
        or {}
    )
    result["steps"]["mcp"] = mcp_summary

    # HTTP-mode MCP/hooks authenticate with the env-first effective token baked
    # into their config as a literal bearer header. No shell rc bridge is written;
    # re-running install materializes/re-stamps a rotated token.

    # --- Step 3: Hook installation ---
    print(bold("[3/3] Hook Installation"))
    hooks = result["steps"]["hooks"]

    hook_targets, hook_target_label = _resolve_hook_targets(target, yes)
    hooks["targets"] = hook_targets
    hooks["target_label"] = hook_target_label
    print(f"  Target:       {info(hook_target_label)}")

    # Stop-hook profile — how Claude/Codex decide what to save when a turn ends.
    # (Kiro/Cursor use their own native stop hooks and ignore this.) Ask the user
    # interactively; default standard. --yes keeps the passed-in profile.
    if not yes and not auth_blocked:
        print(
            f"  {bold('Stop-hook profile')} "
            f"{dim('— what Claude/Codex save when a turn ends:')}"
        )
        profile_opts = [
            f"standard {dim('— server decides by keyword/rules (balanced, no LLM cost)')}",
            f"minimal  {dim('— save every turn, no decision (lightest)')}",
            f"enhanced {dim('— Haiku LLM decides save/skip + structure (needs ANTHROPIC_API_KEY)')}",
        ]
        profile_keys = ["standard", "minimal", "enhanced"]
        chosen = _prompt_choice("  Choose [1]: ", profile_opts, default=profile_opts[0])
        profile = profile_keys[profile_opts.index(chosen)]
    print(f"  Profile:      {info(profile)}")

    hook_default = "n" if preferred_mcp_mode == "uvx" else "Y"
    if preferred_mcp_mode == "uvx":
        print(f"  {dim('Hooks require a running API server (hook scripts use curl).')}")
        print(
            f"  {dim('With uvx, MCP works without a server but hooks do not. Skip unless you will run the server separately.')}"
        )

    skip_hooks = yes and hook_default == "n"
    if skip_hooks:
        print(
            dim("  (--yes: skipping hooks because uvx mode has no running API server)")
        )

    # Auth gate: a token that never authenticated (Step 1) means HTTP/auth hooks
    # would 401 on every call — skip install rather than leave broken hooks.
    if auth_blocked:
        skip_hooks = True
        print(dim("  Skipping hooks: token failed authentication (see above)."))

    if not yes and not auth_blocked:
        prompt_label = (
            f"  Install hooks for {hook_target_label}? [{hook_default}/n] "
            if hook_default == "Y"
            else f"  Install hooks for {hook_target_label}? [y/{hook_default}] "
        )
        raw = input(prompt_label).strip().lower()
        if hook_default == "Y":
            skip_hooks = raw in ("n", "no")
        else:
            skip_hooks = raw not in ("y", "yes")

    hooks_installed = False
    if skip_hooks:
        print(dim("  Skipping hook installation."))
        print()
        hooks["status"] = "skipped"
    else:
        install_url = resolved_url if resolved_url else DEFAULT_URL
        try:
            from app.cli.install_hooks import cmd_install

            for hook_target in hook_targets:
                if current_token and not auth_blocked:
                    _write_hook_token(current_token)
                cmd_install(hook_target, install_url, "api", "", profile)
            hooks_installed = True
            hooks["installed"] = True
            hooks["status"] = "installed"
            print(f"  {ok('Hooks installed successfully.')}")
        except Exception as e:
            hooks["status"] = "failed"
            hooks["error"] = str(e)
            result["errors"].append(f"Hook installation failed: {e}")
            _fail(f"Hook installation failed: {e}", force, json_mode)
        print()

    # --- Summary (human mode only; json mode emits the result dict instead) ---
    if not json_mode:
        _print_summary(
            resolved_url,
            reachable,
            hooks_installed,
            hook_target_label,
            preferred_mcp_mode,
            token_status=token_info.get("status"),
        )


def _print_summary(
    url: str,
    server_ok: bool,
    hooks_ok: bool,
    target: str,
    mcp_mode: Optional[str] = None,
    token_status: Optional[str] = None,
) -> None:
    """Print onboarding summary."""
    print(header("=== Setup Complete ==="))
    print()

    if mcp_mode == "uvx":
        print(f"  MCP:         {ok('uvx (auto-spawned by each tool)')}")
        # Built outside the f-string: the command contains double quotes, which
        # cannot be backslash-escaped inside an f-string expression on Python 3.9.
        serve_cmd = 'uvx --from "mem-mesh[server]" mem-mesh serve'
        serve_hint = f"run `{serve_cmd}` to enable"
        print(f"  Dashboard:   {dim(serve_hint)}")
    else:
        print(
            f"  API server:  {ok(url) if server_ok else warn(url + ' (not running)')}"
        )
        print(
            f"  Dashboard:   {info(url + '/dashboard') if server_ok else dim('unavailable')}"
        )
    print(
        f"  Hooks:       {ok(f'installed ({target})') if hooks_ok else warn('not installed')}"
    )
    token_label = {
        "env": ok("hook token ready (baked into tool configs)"),
        "file": ok("hook token ready (baked into tool configs)"),
        "none": dim("not set"),
    }.get(token_status or "none")
    print(f"  Auth token:  {token_label}")
    print()
    if mcp_mode == "uvx":
        print(
            f"  {bold('Next step:')} restart your MCP client (Codex / Cursor / Claude Desktop / Kiro)."
        )
        print(dim("             First MCP call spawns mem-mesh from the uv cache."))
    elif not server_ok:
        print(f"  {bold('Next step:')} Start the server with {info('mem-mesh serve')}")
        print(dim("             Or: docker compose up -d"))
    print(dim("  Run 'mem-mesh status' for full system check."))
    print(dim("  Run 'mem-mesh hooks doctor' for hook diagnostics."))
    print()
