"""Opt-in hook logging (MEM_MESH_HOOK_LOG) — render + execution tests.

Covers the ``__HOOK_LOG__`` block injected by the renderer: the ``mem_mesh_log``
shell function must (a) be present and fully substituted in rendered hooks,
(b) append a per-stage line to ~/.mem-mesh/hooks.log when MEM_MESH_HOOK_LOG is
truthy, and (c) be a complete no-op (no file, no output) when it is unset/0 so
installed hooks keep their current zero-overhead behavior.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from app.cli.hooks.hook_log import HOOK_LOG_BLOCK
from app.cli.hooks.renderer import _render_template
from app.cli.hooks.templates import (
    SESSION_START_HOOK_TEMPLATE,
    STOP_DECIDE_HOOK_TEMPLATE,
    STOP_HOOK_TEMPLATE,
    USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
)

HAS_BASH = shutil.which("bash") is not None
HAS_JQ = shutil.which("jq") is not None
FAKE_URL = "http://localhost:1"  # nothing listens here → curl fails fast

pytestmark = pytest.mark.skipif(not HAS_BASH, reason="bash not installed")


def _write_block_harness(tmp_path: Path, *calls: str) -> Path:
    """Write a minimal script that loads the logging block then runs calls.

    The raw block carries the unresolved ``__CLIENT_TAG__`` placeholder (the
    renderer substitutes it per-install); stand in a fixed "test" client so log
    lines read ``[test/<hook>]``.
    """
    block = HOOK_LOG_BLOCK.replace("__CLIENT_TAG__", "test")
    body = "\n".join(["#!/bin/bash", "set -euo pipefail", block, *calls, ""])
    path = tmp_path / "harness.sh"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _base_env(home: Path) -> dict:
    """A hermetic env for a hook run: temp HOME, with any inherited mem-mesh
    control vars dropped so each case sets them explicitly.

    The rendered hook reads its URL and token only from
    ``~/.mem-mesh/{api_url,hook_token}`` (no env fallback), so a fresh temp HOME
    pins both: with neither file present the hook falls back to the baked URL
    (FAKE_URL, since the templates here render with it) and reports auth=absent,
    independent of the host's real config. The control vars are popped so a
    stray host value can never shadow the file lookup.
    """
    env = {**os.environ, "HOME": str(home)}
    env.pop("MEM_MESH_HOOK_LOG", None)
    env.pop("MEM_MESH_HOOK_TOKEN", None)
    env.pop("MEM_MESH_API_URL", None)
    return env


def _run(
    path: Path, *, home: Path, log_env: dict | None = None
) -> subprocess.CompletedProcess:
    env = _base_env(home)
    if log_env:
        env.update(log_env)
    return subprocess.run(
        ["bash", str(path)],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


# ---------------------------------------------------------------------------
# Render-time: the block is injected and fully resolved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template",
    [STOP_HOOK_TEMPLATE, SESSION_START_HOOK_TEMPLATE, USER_PROMPT_SUBMIT_HOOK_TEMPLATE],
)
def test_render_injects_logging_block(template: str) -> None:
    rendered = _render_template(template, FAKE_URL, project_id="test-project")
    assert "mem_mesh_log" in rendered
    assert "MEM_MESH_HOOK_LOG" in rendered
    assert 'mem_mesh_log "' in rendered  # at least one call site
    # No unresolved placeholders survived the substitution.
    leftover = re.findall(r"__[A-Z0-9_]+__", rendered)
    assert leftover == [], f"unresolved placeholders: {leftover}"


# ---------------------------------------------------------------------------
# Block behavior: on writes a line, off is a no-op
# ---------------------------------------------------------------------------


def test_logging_writes_line_when_enabled(tmp_path: Path) -> None:
    harness = _write_block_harness(
        tmp_path, 'mem_mesh_log "stop" "sent" "http=200 project=demo"'
    )
    result = _run(harness, home=tmp_path, log_env={"MEM_MESH_HOOK_LOG": "1"})
    assert result.stderr == ""  # first run: no log yet, and no shell noise
    assert result.returncode == 0

    log_file = tmp_path / ".mem-mesh" / "hooks.log"
    assert log_file.exists(), "log file should be created when enabled"
    line = log_file.read_text(encoding="utf-8").strip()
    assert "[test/stop]" in line  # client tag stamped on every line
    assert "sent" in line
    assert "http=200 project=demo" in line
    assert "pid=" in line


@pytest.mark.parametrize("toggle", [None, "0", "false", "off", "no", ""])
def test_logging_silent_when_disabled(tmp_path: Path, toggle) -> None:
    harness = _write_block_harness(tmp_path, 'mem_mesh_log "stop" "fired" "x"')
    log_env = None if toggle is None else {"MEM_MESH_HOOK_LOG": toggle}
    result = _run(harness, home=tmp_path, log_env=log_env)
    assert result.returncode == 0
    assert result.stdout == ""  # logging never pollutes stdout
    log_file = tmp_path / ".mem-mesh" / "hooks.log"
    assert not log_file.exists(), f"no log expected for toggle={toggle!r}"


def test_logging_accumulates_multiple_stages(tmp_path: Path) -> None:
    harness = _write_block_harness(
        tmp_path,
        'mem_mesh_log "stop" "fired" "cwd=/x"',
        'mem_mesh_log "stop" "sent" "http=401"',
    )
    result = _run(harness, home=tmp_path, log_env={"MEM_MESH_HOOK_LOG": "1"})
    assert result.stderr == ""  # "fired" with no log yet must not print shell noise
    assert result.returncode == 0
    lines = (tmp_path / ".mem-mesh" / "hooks.log").read_text().strip().splitlines()
    assert len(lines) == 2
    assert "fired" in lines[0]
    assert "sent" in lines[1] and "http=401" in lines[1]


# ---------------------------------------------------------------------------
# Verbose channel: mem_mesh_logv emits only at level >= 2 (debug)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", ["2", "debug", "verbose"])
def test_verbose_emits_config_at_level_2(tmp_path: Path, level) -> None:
    harness = _write_block_harness(
        tmp_path,
        'mem_mesh_log "stop" "sent" "http=200"',
        'mem_mesh_logv "stop" "config" "url=http://x auth=present curl_exit=0"',
    )
    result = _run(harness, home=tmp_path, log_env={"MEM_MESH_HOOK_LOG": level})
    assert result.returncode == 0
    lines = (tmp_path / ".mem-mesh" / "hooks.log").read_text().strip().splitlines()
    assert len(lines) == 2, f"level={level} should log both stages"
    assert "config" in lines[1]
    assert "auth=present" in lines[1]


def test_verbose_suppressed_at_level_1(tmp_path: Path) -> None:
    """At the concise level, mem_mesh_logv is a no-op — only mem_mesh_log writes."""
    harness = _write_block_harness(
        tmp_path,
        'mem_mesh_log "stop" "sent" "http=200"',
        'mem_mesh_logv "stop" "config" "url=http://x auth=present"',
    )
    result = _run(harness, home=tmp_path, log_env={"MEM_MESH_HOOK_LOG": "1"})
    assert result.returncode == 0
    log = (tmp_path / ".mem-mesh" / "hooks.log").read_text()
    assert "sent" in log
    assert "config" not in log  # verbose line withheld at level 1


@pytest.mark.skipif(not HAS_JQ, reason="jq not installed")
def test_rendered_stop_hook_verbose_adds_config_line(tmp_path: Path) -> None:
    """Level 2 adds a metadata config line (url/auth/curl_exit) to a real hook."""
    script = tmp_path / "stop.sh"
    script.write_text(_render_template(STOP_HOOK_TEMPLATE, FAKE_URL), encoding="utf-8")
    script.chmod(0o755)
    result = subprocess.run(
        ["bash", str(script)],
        input='{"stop_hook_active": false, "last_assistant_message": "hi"}',
        capture_output=True,
        text=True,
        timeout=10,
        env={**_base_env(tmp_path), "MEM_MESH_HOOK_LOG": "2"},
    )
    assert result.returncode == 0
    log = (tmp_path / ".mem-mesh" / "hooks.log").read_text(encoding="utf-8")
    assert "config" in log
    assert f"url={FAKE_URL}" in log
    assert "auth=absent" in log  # no token file under the temp HOME
    assert "key=none" in log  # masked key tail — "none" when no token
    assert "curl_exit=" in log


# ---------------------------------------------------------------------------
# End-to-end: a rendered forwarder traces fired → sent, and stays silent off
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_JQ, reason="jq not installed")
def test_rendered_stop_hook_traces_offline(tmp_path: Path) -> None:
    """With logging on and no server, stop.sh logs fired + sent http=000."""
    script = tmp_path / "stop.sh"
    script.write_text(_render_template(STOP_HOOK_TEMPLATE, FAKE_URL), encoding="utf-8")
    script.chmod(0o755)

    result = subprocess.run(
        ["bash", str(script)],
        input='{"stop_hook_active": false, "last_assistant_message": "hi"}',
        capture_output=True,
        text=True,
        timeout=10,
        env={**_base_env(tmp_path), "MEM_MESH_HOOK_LOG": "1"},
    )
    assert result.returncode == 0
    log = (tmp_path / ".mem-mesh" / "hooks.log").read_text(encoding="utf-8")
    assert "[claude_code/stop] " in log  # default client_tag on a rendered hook
    assert "fired" in log
    # Unreachable server → curl fails → status normalized to 000.
    assert "sent http=000" in log


@pytest.mark.skipif(not HAS_JQ, reason="jq not installed")
def test_rendered_stop_hook_silent_when_logging_off(tmp_path: Path) -> None:
    """Default (no MEM_MESH_HOOK_LOG) must not create the log file."""
    script = tmp_path / "stop.sh"
    script.write_text(_render_template(STOP_HOOK_TEMPLATE, FAKE_URL), encoding="utf-8")
    script.chmod(0o755)

    result = subprocess.run(
        ["bash", str(script)],
        input='{"stop_hook_active": false, "last_assistant_message": "hi"}',
        capture_output=True,
        text=True,
        timeout=10,
        env=_base_env(tmp_path),
    )
    assert result.returncode == 0
    assert not (tmp_path / ".mem-mesh" / "hooks.log").exists()


# ---------------------------------------------------------------------------
# Key masking + per-client tagging
# ---------------------------------------------------------------------------


def test_keytail_masks_token(tmp_path: Path) -> None:
    """mem_mesh_keytail emits only the last 4 chars, never the full secret."""
    harness = _write_block_harness(
        tmp_path,
        'mem_mesh_logv "stop" "config" "key=$(mem_mesh_keytail "supersecretWXYZ")"',
    )
    result = _run(harness, home=tmp_path, log_env={"MEM_MESH_HOOK_LOG": "2"})
    assert result.returncode == 0
    log = (tmp_path / ".mem-mesh" / "hooks.log").read_text(encoding="utf-8")
    assert "key=...WXYZ" in log
    assert "supersecret" not in log  # full token must never be written


def test_keytail_none_when_empty(tmp_path: Path) -> None:
    harness = _write_block_harness(
        tmp_path, 'mem_mesh_logv "stop" "config" "key=$(mem_mesh_keytail "")"'
    )
    result = _run(harness, home=tmp_path, log_env={"MEM_MESH_HOOK_LOG": "2"})
    assert result.returncode == 0
    log = (tmp_path / ".mem-mesh" / "hooks.log").read_text(encoding="utf-8")
    assert "key=none" in log


@pytest.mark.skipif(not HAS_JQ, reason="jq not installed")
def test_rendered_cursor_stop_tags_client(tmp_path: Path) -> None:
    """A cursor-rendered hook stamps [cursor/...] so logs distinguish clients."""
    from app.cli.hooks.templates import CURSOR_STOP_TEMPLATE

    script = tmp_path / "cursor-stop.sh"
    script.write_text(
        _render_template(CURSOR_STOP_TEMPLATE, FAKE_URL, client_tag="cursor"),
        encoding="utf-8",
    )
    script.chmod(0o755)
    result = subprocess.run(
        ["bash", str(script)],
        input='{"stop_hook_active": false, "lastAssistantMessage": "hi"}',
        capture_output=True,
        text=True,
        timeout=10,
        env={**_base_env(tmp_path), "MEM_MESH_HOOK_LOG": "1"},
    )
    assert result.returncode == 0
    log = (tmp_path / ".mem-mesh" / "hooks.log").read_text(encoding="utf-8")
    assert "[cursor/stop]" in log  # client tag, not [claude_code/...]


# ---------------------------------------------------------------------------
# Rotation: hooks.log rolls over to hooks.log.1 once past 10 MB (at "fired")
# ---------------------------------------------------------------------------

_ROTATE_LIMIT_BYTES = 10 * 1024 * 1024


def test_log_rotates_once_over_limit(tmp_path: Path) -> None:
    """A log past 10 MB is moved to hooks.log.1 at the next "fired" stage."""
    log_dir = tmp_path / ".mem-mesh"
    log_dir.mkdir()
    current = log_dir / "hooks.log"
    with current.open("wb") as fh:
        fh.write(b"OLD-GENERATION\n")
        fh.truncate(_ROTATE_LIMIT_BYTES + 1)  # sparse: the size without the bytes
    harness = _write_block_harness(tmp_path, 'mem_mesh_log "stop" "fired" "x"')
    result = _run(harness, home=tmp_path, log_env={"MEM_MESH_HOOK_LOG": "1"})
    assert result.returncode == 0
    rotated = log_dir / "hooks.log.1"
    assert rotated.exists()
    assert rotated.read_bytes().startswith(b"OLD-GENERATION\n")
    fresh = current.read_text(encoding="utf-8").strip().splitlines()
    assert len(fresh) == 1 and "fired" in fresh[0]


def test_log_appends_under_limit(tmp_path: Path) -> None:
    """Under the limit the file is appended to, never rotated."""
    log_dir = tmp_path / ".mem-mesh"
    log_dir.mkdir()
    (log_dir / "hooks.log").write_text("PREVIOUS\n", encoding="utf-8")
    harness = _write_block_harness(tmp_path, 'mem_mesh_log "stop" "fired" "x"')
    result = _run(harness, home=tmp_path, log_env={"MEM_MESH_HOOK_LOG": "1"})
    assert result.returncode == 0
    assert not (log_dir / "hooks.log.1").exists()
    lines = (log_dir / "hooks.log").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "PREVIOUS" and "fired" in lines[1]


# ---------------------------------------------------------------------------
# 4xx summary: loc/msg/type of a FastAPI validation error, never its input
# ---------------------------------------------------------------------------

_VALIDATION_422 = json.dumps(
    {
        "detail": [
            {
                "type": "string_type",
                "loc": ["body", "last_assistant_message"],
                "msg": "Input should be a valid string",
                "input": {"secret": "TURN-CONTENT-MUST-NOT-LEAK"},
            }
        ]
    }
)


@pytest.mark.skipif(not HAS_JQ, reason="jq not installed")
def test_http_error_summary_logs_loc_not_input(tmp_path: Path) -> None:
    harness = _write_block_harness(
        tmp_path, f'mem_mesh_log_http_error "stop" "422" \'{_VALIDATION_422}\''
    )
    result = _run(harness, home=tmp_path, log_env={"MEM_MESH_HOOK_LOG": "2"})
    assert result.returncode == 0
    log = (tmp_path / ".mem-mesh" / "hooks.log").read_text(encoding="utf-8")
    assert "error http=422" in log
    assert "last_assistant_message" in log
    assert "string_type" in log
    assert "TURN-CONTENT-MUST-NOT-LEAK" not in log


@pytest.mark.skipif(not HAS_JQ, reason="jq not installed")
@pytest.mark.parametrize("level,code", [("1", "422"), ("2", "200"), ("2", "000")])
def test_http_error_summary_silent(tmp_path: Path, level: str, code: str) -> None:
    """Nothing below level 2, and nothing for a non-error status."""
    harness = _write_block_harness(
        tmp_path, f'mem_mesh_log_http_error "stop" "{code}" \'{_VALIDATION_422}\''
    )
    result = _run(harness, home=tmp_path, log_env={"MEM_MESH_HOOK_LOG": level})
    assert result.returncode == 0
    assert not (tmp_path / ".mem-mesh" / "hooks.log").exists()


@pytest.mark.skipif(not HAS_JQ, reason="jq not installed")
def test_http_error_summary_non_json_body(tmp_path: Path) -> None:
    harness = _write_block_harness(
        tmp_path, 'mem_mesh_log_http_error "stop" "502" "<html>bad gateway</html>"'
    )
    result = _run(harness, home=tmp_path, log_env={"MEM_MESH_HOOK_LOG": "2"})
    assert result.returncode == 0
    log = (tmp_path / ".mem-mesh" / "hooks.log").read_text(encoding="utf-8")
    assert "error http=502 non-json body bytes=" in log
    assert "bad gateway" not in log


class _Reply422(BaseHTTPRequestHandler):
    """Stand-in for the server: every POST is a FastAPI-shaped 422."""

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = _VALIDATION_422.encode("utf-8")
        self.send_response(422)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def server_422():
    httpd = HTTPServer(("127.0.0.1", 0), _Reply422)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.skipif(not HAS_JQ, reason="jq not installed")
def test_rendered_stop_decide_logs_422_summary(tmp_path: Path, server_422: str) -> None:
    """End to end: a 422 reply logs sent http=422 plus the error summary."""
    script = tmp_path / "stop-decide.sh"
    script.write_text(
        _render_template(STOP_DECIDE_HOOK_TEMPLATE, server_422), encoding="utf-8"
    )
    script.chmod(0o755)
    result = subprocess.run(
        ["bash", str(script)],
        input='{"stop_hook_active": false, "last_assistant_message": "hi"}',
        capture_output=True,
        text=True,
        timeout=10,
        env={**_base_env(tmp_path), "MEM_MESH_HOOK_LOG": "2"},
    )
    assert result.returncode == 0
    log = (tmp_path / ".mem-mesh" / "hooks.log").read_text(encoding="utf-8")
    assert "[claude_code/stop-decide] " in log
    assert "sent http=422" in log
    assert "error http=422" in log and "last_assistant_message" in log
    assert "TURN-CONTENT-MUST-NOT-LEAK" not in log


# ---------------------------------------------------------------------------
# Delivery over cancel: a forwarder shielded at "posting" survives a host TERM
# ---------------------------------------------------------------------------


class _SlowOk(BaseHTTPRequestHandler):
    """Stand-in server: answers each POST after a delay, counting arrivals."""

    received = 0
    delay_seconds = 1.0

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        type(self).received += 1
        time.sleep(self.delay_seconds)
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def slow_server():
    _SlowOk.received = 0
    httpd = HTTPServer(("127.0.0.1", 0), _SlowOk)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _wait_for_log(log_path: Path, needle: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log_path.exists() and needle in log_path.read_text(encoding="utf-8"):
            return
        time.sleep(0.02)
    pytest.fail(f"hook never logged {needle!r}")


@pytest.mark.skipif(not HAS_JQ, reason="jq not installed")
@pytest.mark.parametrize("shielded", [True, False], ids=["shielded", "control"])
def test_rendered_stop_decide_term_mid_post(
    tmp_path: Path, slow_server: str, shielded: bool
) -> None:
    """TERM to the hook's process group during the send: the shielded hook
    still logs sent http=200; the control (shield stubbed out) is killed at
    posting, which proves the signal reaches an unshielded hook."""
    rendered = _render_template(STOP_DECIDE_HOOK_TEMPLATE, slow_server)
    if not shielded:
        assert rendered.count("\nmem_mesh_post_shield\n") == 1
        rendered = rendered.replace("\nmem_mesh_post_shield\n", "\n:\n")
    script = tmp_path / "stop-decide.sh"
    script.write_text(rendered, encoding="utf-8")
    script.chmod(0o755)
    log_path = tmp_path / ".mem-mesh" / "hooks.log"

    proc = subprocess.Popen(
        ["bash", str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**_base_env(tmp_path), "MEM_MESH_HOOK_LOG": "2"},
        start_new_session=True,  # own process group, like a host-spawned hook
    )
    assert proc.stdin is not None
    proc.stdin.write('{"stop_hook_active": false, "last_assistant_message": "hi"}')
    proc.stdin.close()
    _wait_for_log(log_path, "posting")  # logged after the shield is armed
    os.killpg(proc.pid, signal.SIGTERM)
    proc.communicate(timeout=10)

    assert proc.returncode == 0
    log = log_path.read_text(encoding="utf-8")
    if shielded:
        assert _SlowOk.received == 1
        assert "sent http=200" in log
        assert "killed" not in log
    else:
        assert "killed signal=TERM last_stage=posting" in log
        assert "sent http=200" not in log
