"""Bash hook script unit tests — render, execute, verify behavior."""

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.cli.hooks.renderer import _render_template
from app.cli.hooks.templates import (
    KIRO_STOP_HOOK_TEMPLATE,
    SESSION_START_HOOK_TEMPLATE,
    STOP_DECIDE_HOOK_TEMPLATE,
    SUBAGENT_START_HOOK_TEMPLATE,
    SUBAGENT_STOP_HOOK_TEMPLATE,
    TASK_COMPLETED_HOOK_TEMPLATE,
    USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
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
    script = _render_and_write(
        tmp_path, STOP_DECIDE_HOOK_TEMPLATE, project_id="test-project"
    )
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
    script = _render_and_write(
        tmp_path, STOP_DECIDE_HOOK_TEMPLATE, project_id="test-project"
    )
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
    script = _render_and_write(
        tmp_path, STOP_DECIDE_HOOK_TEMPLATE, project_id="test-project"
    )
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
    script = _render_and_write(
        tmp_path, STOP_DECIDE_HOOK_TEMPLATE, project_id="test-project"
    )
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
    script = _render_and_write(
        tmp_path, STOP_DECIDE_HOOK_TEMPLATE, project_id="test-project"
    )
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
    script = _render_and_write(
        tmp_path, STOP_DECIDE_HOOK_TEMPLATE, project_id="test-project"
    )
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
    """The session-start hook must produce valid JSON on stdout even when the API
    is unavailable. The thin forwarder emits the server's hookSpecificOutput, or
    ``{}`` on a no-op/unreachable server — both valid JSON for Claude Code's
    output schema."""
    script = _render_and_write(
        tmp_path, SESSION_START_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(script, {})
    assert result.returncode == 0
    parsed = json.loads(result.stdout)  # offline → {} (still valid JSON)
    assert isinstance(parsed, dict)


def _extract_context(parsed: dict) -> str:
    """Extract context string from either legacy or new hook format."""
    if "additional_context" in parsed:
        return parsed["additional_context"]
    return parsed.get("hookSpecificOutput", {}).get("additionalContext", "")


def test_session_start_forwards_server_context(tmp_path: Path, hook_api_server) -> None:
    """The rules block is rendered server-side now; the thin forwarder emits the
    server's hookSpecificOutput verbatim. With the server reachable, its context
    (referencing mem-mesh) must reach stdout."""
    state, url = hook_api_server
    state["response"] = {
        "hookSpecificOutput": {
            "additionalContext": "mem-mesh rules: pin code changes, save decisions."
        }
    }
    script = _render_and_write(
        tmp_path, SESSION_START_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(script, {}, env={"MEM_MESH_API_URL": url})
    assert result.returncode == 0
    context = _extract_context(json.loads(result.stdout))
    assert "mem-mesh" in context


# ---------------------------------------------------------------------------
# kiro-stop tests
# ---------------------------------------------------------------------------


def test_kiro_stop_no_keyword_exits_zero(tmp_path: Path) -> None:
    """A KIRO_RESULT with no save-triggering keywords should exit 0 without saving."""
    script = _render_and_write(
        tmp_path, KIRO_STOP_HOOK_TEMPLATE, project_id="test-project"
    )
    message = (
        "This is a regular response with no special keywords at all, "
        "just describing some general information about the system."
    )
    result = _run_hook(script, {}, env={"KIRO_RESULT": message})
    assert result.returncode == 0


def test_kiro_stop_decision_keyword_triggers_save(tmp_path: Path) -> None:
    """A KIRO_RESULT containing architecture/decision keywords should attempt save and exit 0."""
    script = _render_and_write(
        tmp_path, KIRO_STOP_HOOK_TEMPLATE, project_id="test-project"
    )
    message = "아키텍처 결정을 변경했습니다. 새로운 설계를 선택하였습니다."
    result = _run_hook(script, {}, env={"KIRO_RESULT": message})
    # curl fails gracefully; script must still exit 0
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# user-prompt-submit tests
# ---------------------------------------------------------------------------


def test_user_prompt_submit_short_prompt_exits(tmp_path: Path) -> None:
    """A prompt shorter than 30 chars should be skipped (exit 0, no output)."""
    script = _render_and_write(
        tmp_path, USER_PROMPT_SUBMIT_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(script, {"prompt": "hello"})
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_user_prompt_submit_no_keyword_exits(tmp_path: Path) -> None:
    """A long prompt without matching keywords should exit 0 with no output."""
    script = _render_and_write(
        tmp_path, USER_PROMPT_SUBMIT_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(
        script,
        {
            "prompt": "Please write a function that checks if a number is prime and returns boolean"
        },
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_user_prompt_submit_keyword_match_exits_zero(tmp_path: Path) -> None:
    """A prompt with keyword match should exit 0 (curl fails but script handles gracefully)."""
    script = _render_and_write(
        tmp_path, USER_PROMPT_SUBMIT_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(
        script,
        {"prompt": "이전에 결정한 아키텍처는 무엇이었나요? 변경 이유를 알고 싶습니다."},
    )
    assert result.returncode == 0


def test_user_prompt_submit_empty_prompt_exits(tmp_path: Path) -> None:
    """An empty prompt should exit 0 with no output."""
    script = _render_and_write(
        tmp_path, USER_PROMPT_SUBMIT_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(script, {})
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# user-prompt-submit pin reminder tests
# ---------------------------------------------------------------------------

PIN_REMINDER_TEXT = "현재 추적 중인 pin이 없습니다"
NO_KEYWORD_PROMPT = "please refactor this module for clarity"


@pytest.fixture()
def hook_api_server():
    """Mock mem-mesh serving POST /api/hooks/claude/* with a settable response.

    Exercises the thin-forwarder contract: the hook POSTs the event and emits
    whatever hookSpecificOutput the server returns. Set ``state["response"]`` to
    the JSON the server should reply with.
    """
    state: dict = {"response": {}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 — BaseHTTPRequestHandler contract
            length = int(self.headers.get("Content-Length", 0) or 0)
            self.rfile.read(length)
            # ensure_ascii=False to mirror FastAPI's UTF-8 JSON (so multibyte
            # context survives the round-trip through the hook to stdout).
            body = json.dumps(state["response"], ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence request logging
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture()
def pin_api_server():
    """Mock mem-mesh API serving /api/work/pins from a per-status pin map."""
    state: dict[str, list] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler contract
            parsed = urlparse(self.path)
            if parsed.path != "/api/work/pins":
                self.send_error(404)
                return
            status = parse_qs(parsed.query).get("status", [""])[0]
            pins = state.get(status, [])
            body = json.dumps({"pins": pins, "total": len(pins)}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence request logging
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_user_prompt_submit_reminds_when_no_tracked_pins(
    tmp_path: Path, hook_api_server
) -> None:
    """The pin reminder is decided server-side; when the server returns it, the
    thin forwarder surfaces it on stdout."""
    state, url = hook_api_server
    state["response"] = {"hookSpecificOutput": {"additionalContext": PIN_REMINDER_TEXT}}
    script = _render_and_write(
        tmp_path, USER_PROMPT_SUBMIT_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(
        script, {"prompt": NO_KEYWORD_PROMPT}, env={"MEM_MESH_API_URL": url}
    )
    assert result.returncode == 0
    assert PIN_REMINDER_TEXT in result.stdout


def test_user_prompt_submit_silent_with_in_progress_pin(
    tmp_path: Path, pin_api_server
) -> None:
    """An in_progress pin (pin_add default) counts as tracked — no reminder.

    Regression: the hook used to query status=open only, so it kept asking
    for pin_add while a pin was actively in progress.
    """
    state, url = pin_api_server
    state["in_progress"] = [{"id": "p1", "status": "in_progress"}]
    script = _render_and_write(
        tmp_path, USER_PROMPT_SUBMIT_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(
        script, {"prompt": NO_KEYWORD_PROMPT}, env={"MEM_MESH_API_URL": url}
    )
    assert result.returncode == 0
    assert PIN_REMINDER_TEXT not in result.stdout


def test_user_prompt_submit_silent_with_open_pin(
    tmp_path: Path, pin_api_server
) -> None:
    """A pre-planned open pin also counts as tracked — no reminder."""
    state, url = pin_api_server
    state["open"] = [{"id": "p1", "status": "open"}]
    script = _render_and_write(
        tmp_path, USER_PROMPT_SUBMIT_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(
        script, {"prompt": NO_KEYWORD_PROMPT}, env={"MEM_MESH_API_URL": url}
    )
    assert result.returncode == 0
    assert PIN_REMINDER_TEXT not in result.stdout


def test_user_prompt_submit_silent_on_pin_api_error(tmp_path: Path) -> None:
    """Unreachable API → stay quiet rather than nag with a possibly-wrong reminder."""
    script = _render_and_write(
        tmp_path, USER_PROMPT_SUBMIT_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(script, {"prompt": NO_KEYWORD_PROMPT})
    assert result.returncode == 0
    assert PIN_REMINDER_TEXT not in result.stdout


# ---------------------------------------------------------------------------
# subagent-start tests
# ---------------------------------------------------------------------------


def test_subagent_start_lightweight_agent_exits(tmp_path: Path) -> None:
    """Lightweight agent types (Explore, Glob, etc.) should exit 0 immediately."""
    script = _render_and_write(
        tmp_path, SUBAGENT_START_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(script, {"agent_type": "Explore", "agent_id": "test-123"})
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_subagent_start_plan_agent_exits_zero(tmp_path: Path) -> None:
    """A Plan agent should attempt context injection and exit 0 (curl fails gracefully)."""
    script = _render_and_write(
        tmp_path, SUBAGENT_START_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(script, {"agent_type": "Plan", "agent_id": "test-456"})
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# subagent-stop tests
# ---------------------------------------------------------------------------


def test_subagent_stop_loop_guard_exits(tmp_path: Path) -> None:
    """When stop_hook_active is true, subagent-stop must exit 0 immediately."""
    script = _render_and_write(
        tmp_path, SUBAGENT_STOP_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(
        script,
        {
            "stop_hook_active": True,
            "agent_type": "Plan",
            "last_assistant_message": "버그를 수정했습니다. fix 완료. " * 10,
        },
    )
    assert result.returncode == 0


def test_subagent_stop_short_message_exits(tmp_path: Path) -> None:
    """A message shorter than 100 chars should be skipped."""
    script = _render_and_write(
        tmp_path, SUBAGENT_STOP_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(
        script,
        {
            "stop_hook_active": False,
            "agent_type": "Plan",
            "last_assistant_message": "short msg",
        },
    )
    assert result.returncode == 0


def test_subagent_stop_bug_keyword_triggers_save(tmp_path: Path) -> None:
    """A subagent message with bug/fix keywords should attempt save and exit 0."""
    script = _render_and_write(
        tmp_path, SUBAGENT_STOP_HOOK_TEMPLATE, project_id="test-project"
    )
    long_msg = "버그를 수정했습니다. error를 해결한 fix 입니다. " * 5
    result = _run_hook(
        script,
        {
            "stop_hook_active": False,
            "agent_type": "general-purpose",
            "last_assistant_message": long_msg,
        },
    )
    assert result.returncode == 0


def test_subagent_stop_no_keyword_exits(tmp_path: Path) -> None:
    """A long message without keywords should be skipped."""
    script = _render_and_write(
        tmp_path, SUBAGENT_STOP_HOOK_TEMPLATE, project_id="test-project"
    )
    long_msg = "This is a regular message about general system information. " * 5
    result = _run_hook(
        script,
        {
            "stop_hook_active": False,
            "agent_type": "Plan",
            "last_assistant_message": long_msg,
        },
    )
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# task-completed tests
# ---------------------------------------------------------------------------


def test_task_completed_saves_task(tmp_path: Path) -> None:
    """A task with subject should attempt save and exit 0."""
    script = _render_and_write(
        tmp_path, TASK_COMPLETED_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(
        script,
        {
            "task_subject": "Implement auth",
            "task_description": "Added JWT authentication",
            "teammate_name": "executor",
        },
    )
    # curl fails gracefully; script must still exit 0
    assert result.returncode == 0


def test_task_completed_empty_subject_exits(tmp_path: Path) -> None:
    """An empty task_subject should exit 0 with no output."""
    script = _render_and_write(
        tmp_path, TASK_COMPLETED_HOOK_TEMPLATE, project_id="test-project"
    )
    result = _run_hook(script, {})
    assert result.returncode == 0
