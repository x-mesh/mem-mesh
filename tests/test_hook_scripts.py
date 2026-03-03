"""Bash hook script unit tests — render, execute, verify behavior."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.cli.hooks.renderer import _render_template
from app.cli.hooks.templates import (
    KIRO_STOP_HOOK_TEMPLATE,
    SESSION_START_HOOK_TEMPLATE,
    STOP_DECIDE_HOOK_TEMPLATE,
)

HAS_JQ = shutil.which("jq") is not None
pytestmark = pytest.mark.skipif(not HAS_JQ, reason="jq not installed")

FAKE_URL = "http://localhost:1"


def _render_and_write(tmp_path: Path, template: str, **kwargs) -> Path:
    """Render a template and write as executable script."""
    script = _render_template(template, FAKE_URL, **kwargs)
    path = tmp_path / "hook.sh"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return path


def _run_hook(
    script_path: Path,
    input_data: dict,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run a hook script with JSON input on stdin."""
    run_env = {**os.environ, "MEM_MESH_API_URL": FAKE_URL}
    if env:
        run_env.update(env)
    return subprocess.run(
        ["bash", str(script_path)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=10,
        env=run_env,
    )


# ---------------------------------------------------------------------------
# stop-decide tests
# ---------------------------------------------------------------------------


def test_stop_decide_no_keyword_match_exits_zero(tmp_path: Path) -> None:
    """A long message with no save-triggering keywords should exit 0 without saving."""
    script = _render_and_write(tmp_path, STOP_DECIDE_HOOK_TEMPLATE, project_id="test-project")
    result = _run_hook(
        script,
        {
            "stop_hook_active": False,
            "last_assistant_message": (
                "Hello, this is a normal message with no special keywords at all, "
                "just talking about the weather today"
            ),
        },
    )
    assert result.returncode == 0


def test_stop_decide_bug_keyword_triggers_save(tmp_path: Path) -> None:
    """A message containing bug/fix/error keywords should attempt a save and exit 0."""
    script = _render_and_write(tmp_path, STOP_DECIDE_HOOK_TEMPLATE, project_id="test-project")
    result = _run_hook(
        script,
        {
            "stop_hook_active": False,
            "last_assistant_message": "bug를 수정했습니다. error를 해결한 fix 입니다.",
        },
    )
    # curl will fail (no server at FAKE_URL) but the script uses `|| true` so exit 0
    assert result.returncode == 0


def test_stop_decide_idea_keyword_triggers_save(tmp_path: Path) -> None:
    """A message containing idea/제안 keywords should attempt a save and exit 0."""
    script = _render_and_write(tmp_path, STOP_DECIDE_HOOK_TEMPLATE, project_id="test-project")
    result = _run_hook(
        script,
        {
            "stop_hook_active": False,
            "last_assistant_message": "아이디어를 제안합니다. 새로운 기능을 고려해봐야 합니다.",
        },
    )
    assert result.returncode == 0


def test_stop_decide_loop_guard_exits_immediately(tmp_path: Path) -> None:
    """When stop_hook_active is true the script must exit 0 immediately (loop guard)."""
    script = _render_and_write(tmp_path, STOP_DECIDE_HOOK_TEMPLATE, project_id="test-project")
    result = _run_hook(
        script,
        {
            "stop_hook_active": True,
            "last_assistant_message": (
                "아이디어를 제안합니다. 새로운 기능을 고려해봐야 합니다. "
                "이 메시지는 50자 이상이어야 합니다."
            ),
        },
    )
    assert result.returncode == 0


def test_stop_decide_short_message_exits(tmp_path: Path) -> None:
    """A message shorter than 50 characters should be skipped (exit 0)."""
    script = _render_and_write(tmp_path, STOP_DECIDE_HOOK_TEMPLATE, project_id="test-project")
    result = _run_hook(
        script,
        {
            "stop_hook_active": False,
            "last_assistant_message": "short",
        },
    )
    assert result.returncode == 0


def test_stop_decide_already_saved_via_mcp_exits(tmp_path: Path) -> None:
    """If the message contains 'mcp__mem-mesh__add' the hook should skip and exit 0."""
    script = _render_and_write(tmp_path, STOP_DECIDE_HOOK_TEMPLATE, project_id="test-project")
    # The message must be >50 chars AND contain the MCP marker
    long_msg = (
        "이 메시지는 mcp__mem-mesh__add 도구를 통해 이미 저장되었으므로 "
        "중복 저장을 방지해야 합니다."
    )
    result = _run_hook(
        script,
        {
            "stop_hook_active": False,
            "last_assistant_message": long_msg,
        },
    )
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# session-start tests
# ---------------------------------------------------------------------------


def test_session_start_outputs_valid_json(tmp_path: Path) -> None:
    """The session-start hook must produce valid JSON on stdout even when API is unavailable."""
    script = _render_and_write(
        tmp_path, SESSION_START_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(script, {})
    assert result.returncode == 0
    # stdout must be parseable JSON
    parsed = json.loads(result.stdout)
    assert "additional_context" in parsed


def test_session_start_includes_rules_text(tmp_path: Path) -> None:
    """The additional_context field must reference mem-mesh rules."""
    script = _render_and_write(
        tmp_path, SESSION_START_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(script, {})
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    context = parsed["additional_context"]
    assert "mem-mesh" in context


# ---------------------------------------------------------------------------
# kiro-stop tests
# ---------------------------------------------------------------------------


def test_kiro_stop_no_keyword_exits_zero(tmp_path: Path) -> None:
    """A KIRO_RESULT with no save-triggering keywords should exit 0 without saving."""
    script = _render_and_write(tmp_path, KIRO_STOP_HOOK_TEMPLATE, project_id="test-project")
    message = (
        "This is a regular response with no special keywords at all, "
        "just describing some general information about the system."
    )
    result = _run_hook(script, {}, env={"KIRO_RESULT": message})
    assert result.returncode == 0


def test_kiro_stop_decision_keyword_triggers_save(tmp_path: Path) -> None:
    """A KIRO_RESULT containing architecture/decision keywords should attempt save and exit 0."""
    script = _render_and_write(tmp_path, KIRO_STOP_HOOK_TEMPLATE, project_id="test-project")
    message = "아키텍처 결정을 변경했습니다. 새로운 설계를 선택하였습니다."
    result = _run_hook(script, {}, env={"KIRO_RESULT": message})
    # curl fails gracefully; script must still exit 0
    assert result.returncode == 0
