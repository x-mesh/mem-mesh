"""Opt-in hook logging (MEM_MESH_HOOK_LOG) — render + execution tests.

Covers the ``__HOOK_LOG__`` block injected by the renderer: the ``mem_mesh_log``
shell function must (a) be present and fully substituted in rendered hooks,
(b) append a per-stage line to ~/.mem-mesh/hooks.log when MEM_MESH_HOOK_LOG is
truthy, and (c) be a complete no-op (no file, no output) when it is unset/0 so
installed hooks keep their current zero-overhead behavior.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.cli.hooks.hook_log import HOOK_LOG_BLOCK
from app.cli.hooks.renderer import _render_template
from app.cli.hooks.templates import (
    SESSION_START_HOOK_TEMPLATE,
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
