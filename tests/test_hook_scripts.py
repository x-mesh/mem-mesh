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

from app.cli.hooks.renderer import _render_local_template, _render_template
from app.cli.hooks.templates import (
    CURSOR_SESSION_START_TEMPLATE,
    CURSOR_STOP_TEMPLATE,
    KIRO_STOP_HOOK_TEMPLATE,
    LOCAL_SESSION_START_HOOK_TEMPLATE,
    POST_TOOL_USE_HOOK_TEMPLATE,
    PRECOMPACT_HOOK_TEMPLATE,
    SESSION_END_HOOK_TEMPLATE,
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
    *,
    api_url: str | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    """Run a hook script with JSON input on stdin.

    The rendered hook reads its API URL only from ``~/.mem-mesh/api_url`` (no env
    fallback), so the run is pinned to a hermetic HOME (the script's tmp dir).
    Pass ``api_url`` to drop a config file there and aim the hook at a fake
    server; without it the hook uses the baked default (FAKE_URL → curl fails
    fast, offline). The inherited mem-mesh control vars are dropped so a stray
    host value can never shadow the file.
    """
    home = script_path.parent
    run_env = {**os.environ, "HOME": str(home)}
    run_env.pop("MEM_MESH_API_URL", None)
    run_env.pop("MEM_MESH_HOOK_TOKEN", None)
    if api_url is not None:
        cfg_dir = home / ".mem-mesh"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "api_url").write_text(api_url, encoding="utf-8")
    if env:
        run_env.update(env)
    return subprocess.run(
        ["bash", str(script_path)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=10,
        env=run_env,
        cwd=str(cwd) if cwd else None,
    )


# ---------------------------------------------------------------------------
# post-tool-use tests
# ---------------------------------------------------------------------------


def test_post_tool_use_empty_payload_skips_curl(
    tmp_path: Path, hook_api_server
) -> None:
    state, url = hook_api_server
    script = _render_and_write(
        tmp_path,
        POST_TOOL_USE_HOOK_TEMPLATE,
        source_tag="agy-hook",
        client_tag="agy",
        project_id="test-project",
    )

    result = _run_hook(script, {}, api_url=url)

    assert result.returncode == 0
    assert "last_payload" not in state


@pytest.mark.parametrize(
    ("raw_tool", "expected"),
    [
        ("write_to_file", "Write"),
        ("replace_file_content", "Edit"),
        ("multi_replace_file_content", "MultiEdit"),
    ],
)
def test_post_tool_use_normalizes_agy_payload(
    tmp_path: Path, hook_api_server, raw_tool: str, expected: str
) -> None:
    state, url = hook_api_server
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".mem-mesh").mkdir()
    (workspace / ".mem-mesh" / "project-id").write_text(
        "workspace-project\n", encoding="utf-8"
    )
    script = _render_and_write(
        tmp_path,
        POST_TOOL_USE_HOOK_TEMPLATE,
        source_tag="agy-hook",
        client_tag="agy",
        project_id="test-project",
    )

    result = _run_hook(
        script,
        {
            "sessionId": "agy-session-1",
            "toolName": raw_tool,
            "cwd": str(workspace),
        },
        api_url=url,
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert state["last_payload"]["project_id"] == "workspace-project"
    assert state["last_payload"]["client"] == "agy"
    assert state["last_payload"]["hook_source"] == "agy-hook"
    assert state["last_payload"]["session_id"] == "agy-session-1"
    assert state["last_payload"]["tool_name"] == expected


def test_post_tool_use_accepts_agy_v2_tool_call_payload(
    tmp_path: Path, hook_api_server
) -> None:
    state, url = hook_api_server
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".mem-mesh").mkdir()
    (workspace / ".mem-mesh" / "project-id").write_text(
        "workspace-project\n", encoding="utf-8"
    )
    config_cwd = tmp_path / "config-cwd"
    config_cwd.mkdir()
    script = _render_and_write(
        tmp_path,
        POST_TOOL_USE_HOOK_TEMPLATE,
        source_tag="agy-hook",
        client_tag="agy",
        project_id="test-project",
    )

    result = _run_hook(
        script,
        {
            "conversationId": "agy-conversation-1",
            "modelName": "gemini-test",
            "stepIdx": 2,
            "workspacePaths": [str(workspace)],
            "toolCall": {
                "name": "run_command",
                "args": {"cmd": "printf agy-final-hook-probe"},
            },
            "error": None,
        },
        api_url=url,
        cwd=config_cwd,
    )

    assert result.returncode == 0
    assert state["last_payload"]["project_id"] == "workspace-project"
    assert state["last_payload"]["client"] == "agy"
    assert state["last_payload"]["hook_source"] == "agy-hook"
    assert state["last_payload"]["session_id"] == "agy-conversation-1"
    assert state["last_payload"]["tool_name"] == "run_command"


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


def test_cursor_stop_uses_workspace_project_id(tmp_path: Path, hook_api_server) -> None:
    state, url = hook_api_server
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".mem-mesh").mkdir()
    (workspace / ".mem-mesh" / "project-id").write_text(
        "workspace-project\n", encoding="utf-8"
    )
    script = _render_and_write(
        tmp_path,
        CURSOR_STOP_TEMPLATE,
        source_tag="cursor-hook",
        client_tag="cursor",
        project_id="test-project",
    )

    result = _run_hook(
        script,
        {
            "stopHookActive": False,
            "lastAssistantMessage": (
                "Cursor agent stop hook 검증용 응답입니다. workspace.current_dir "
                "기준으로 project_id가 workspace-project가 되어야 합니다."
            ),
            "workspace_roots": [str(workspace)],
        },
        api_url=url,
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert state["last_payload"]["project_id"] == "workspace-project"
    assert state["last_payload"]["client"] == "cursor"
    assert state["last_payload"]["last_assistant_message"].startswith("Cursor agent")


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
    result = _run_hook(script, {}, api_url=url)
    assert result.returncode == 0
    context = _extract_context(json.loads(result.stdout))
    assert "mem-mesh" in context


def test_session_start_uses_git_config_project_id(
    tmp_path: Path, hook_api_server
) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not installed")

    state, url = hook_api_server
    state["response"] = {}
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "--local", "mem-mesh.project-id", "canonical-project"],
        cwd=repo,
        check=True,
    )
    script = _render_and_write(
        tmp_path, SESSION_START_HOOK_TEMPLATE, project_id="test-project"
    )

    result = _run_hook(script, {}, api_url=url, cwd=repo)

    assert result.returncode == 0
    assert state["last_payload"]["project_id"] == "canonical-project"


def test_cursor_session_start_uses_workspace_project_id(
    tmp_path: Path, hook_api_server
) -> None:
    state, url = hook_api_server
    state["response"] = {}
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".mem-mesh").mkdir()
    (workspace / ".mem-mesh" / "project-id").write_text(
        "workspace-project\n", encoding="utf-8"
    )
    script = _render_and_write(
        tmp_path,
        CURSOR_SESSION_START_TEMPLATE,
        source_tag="cursor-hook",
        client_tag="cursor",
        project_id="test-project",
    )

    result = _run_hook(
        script,
        {
            "sessionId": "cursor-session-1",
            "workspace_roots": [str(workspace)],
        },
        api_url=url,
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert state["last_payload"]["project_id"] == "workspace-project"
    assert state["last_payload"]["client"] == "cursor"
    assert state["last_payload"]["session_id"] == "cursor-session-1"


def test_codex_session_start_compact_stdout_keeps_full_payload(
    tmp_path: Path, hook_api_server
) -> None:
    """Codex compact stdout injects bounded real context without trimming POST."""
    state, url = hook_api_server
    long_prompt = "retain-me-" + ("x" * 2000)
    expected_context = (
        "## mem-mesh Session Context (Auto-injected)\n"
        '**You MUST call `session_resume(project_id="mem-mesh", expand="smart")` immediately**\n'
        "### Rules\n" + ("very noisy rule text\n" * 100)
    )
    state["response"] = {"hookSpecificOutput": {"additionalContext": expected_context}}
    script = _render_and_write(
        tmp_path,
        SESSION_START_HOOK_TEMPLATE,
        source_tag="codex-hook",
        client_tag="codex",
        hook_output_mode="compact",
        project_id="test-project",
    )

    result = _run_hook(script, {"prompt": long_prompt}, api_url=url)

    assert result.returncode == 0
    context = _extract_context(json.loads(result.stdout))
    assert context == expected_context[:2000]
    assert "MUST call" in context
    assert "very noisy rule text" in context
    assert len(context) == 2000
    assert state["last_payload"]["prompt"] == long_prompt
    assert state["last_payload"]["client"] == "codex"


def test_codex_local_session_start_compact_keeps_bounded_real_context(
    tmp_path: Path,
) -> None:
    rendered = _render_local_template(
        LOCAL_SESSION_START_HOOK_TEMPLATE,
        str(tmp_path),
        hook_output_mode="compact",
    )

    assert "COMPACT_CONTEXT_CHARS=2000" in rendered
    assert "additionalContext: $ctx" in rendered
    assert "'.[0:$limit]'" in rendered
    assert "Detailed hook output suppressed for Codex" not in rendered


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


def test_kiro_stop_extracts_agy_transcript_response(
    tmp_path: Path, hook_api_server
) -> None:
    state, url = hook_api_server
    script = _render_and_write(
        tmp_path,
        KIRO_STOP_HOOK_TEMPLATE,
        source_tag="agy-hook",
        client_tag="agy",
        ide_tag="agy",
        project_id="test-project",
    )
    transcript = tmp_path / "transcript_full.jsonl"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".mem-mesh").mkdir()
    (workspace / ".mem-mesh" / "project-id").write_text(
        "workspace-project\n", encoding="utf-8"
    )
    config_cwd = tmp_path / "config-cwd"
    config_cwd.mkdir()
    expected = (
        "아키텍처 결정을 기록합니다. agy Stop payload는 응답 본문 대신 "
        "transcriptPath를 제공하므로 마지막 MODEL content를 저장해야 합니다. "
        "이 회귀 테스트는 100자 미만 응답을 저장하지 않는 hook guard를 통과하도록 "
        "충분히 긴 실제 응답 형태를 사용합니다."
    )
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"source": "USER_EXPLICIT", "content": "요청"}),
                json.dumps({"source": "MODEL", "content": expected}),
                json.dumps({"source": "SYSTEM", "content": "{{ CHECKPOINT }}"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_hook(
        script,
        {"transcriptPath": str(transcript), "workspacePaths": [str(workspace)]},
        api_url=url,
        cwd=config_cwd,
    )

    assert result.returncode == 0
    assert state["last_payload"]["project_id"] == "workspace-project"
    assert state["last_payload"]["client"] == "agy"
    assert state["last_payload"]["source"] == "agy-hook"
    assert expected in state["last_payload"]["content"]
    assert str(transcript) not in state["last_payload"]["content"]
    assert '"transcriptPath"' not in state["last_payload"]["content"]


def test_kiro_stop_extracts_cli_assistant_response(
    tmp_path: Path, hook_api_server
) -> None:
    state, url = hook_api_server
    script = _render_and_write(
        tmp_path,
        KIRO_STOP_HOOK_TEMPLATE,
        source_tag="kiro-hook",
        client_tag="kiro",
        ide_tag="kiro",
        project_id="test-project",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".mem-mesh").mkdir()
    (workspace / ".mem-mesh" / "project-id").write_text(
        "workspace-project\n", encoding="utf-8"
    )
    expected = (
        "Kiro CLI custom agent stop hook 검증입니다. 실제 kiro-cli 2.10.0 "
        "payload는 assistant_response 필드에 최종 응답을 담으므로, hook이 이 필드를 "
        "읽어 mem-mesh에 저장해야 합니다. 이 문장은 100자 guard를 통과합니다."
    )

    result = _run_hook(
        script,
        {
            "hook_event_name": "stop",
            "cwd": str(workspace),
            "assistant_response": expected,
        },
        api_url=url,
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert state["last_payload"]["project_id"] == "workspace-project"
    assert state["last_payload"]["client"] == "kiro"
    assert state["last_payload"]["source"] == "kiro-hook"
    assert expected in state["last_payload"]["content"]


def test_kiro_stop_skips_repetitive_padding(tmp_path: Path, hook_api_server) -> None:
    """A response padded with a long run of one char (a probe) must not be saved."""
    state, url = hook_api_server
    script = _render_and_write(
        tmp_path,
        KIRO_STOP_HOOK_TEMPLATE,
        source_tag="agy-hook",
        client_tag="agy",
        ide_tag="agy",
        project_id="test-project",
    )
    padded = "Stop hook flat-shape verification. " + ("x" * 170)

    result = _run_hook(script, {}, env={"KIRO_RESULT": padded}, api_url=url)

    assert result.returncode == 0
    assert "last_payload" not in state


def test_kiro_stop_skips_model_banner(tmp_path: Path, hook_api_server) -> None:
    """A short model-identity greeting (agy fires Stop on it) must not be saved."""
    state, url = hook_api_server
    script = _render_and_write(
        tmp_path,
        KIRO_STOP_HOOK_TEMPLATE,
        source_tag="agy-hook",
        client_tag="agy",
        ide_tag="agy",
        project_id="test-project",
    )
    banner = (
        "You are currently using **Gemini 3.1 Pro**. Let me know if you have "
        "any questions or tasks you'd like to work on!"
    )

    result = _run_hook(script, {}, env={"KIRO_RESULT": banner}, api_url=url)

    assert result.returncode == 0
    assert "last_payload" not in state


def test_kiro_stop_saves_json_findings_as_markdown(
    tmp_path: Path, hook_api_server
) -> None:
    """A genuine findings JSON envelope is saved, but rendered as readable
    markdown (severity/file:line/claim/evidence) — not the raw one-line blob."""
    state, url = hook_api_server
    script = _render_and_write(
        tmp_path,
        KIRO_STOP_HOOK_TEMPLATE,
        source_tag="kiro-hook",
        client_tag="kiro",
        ide_tag="kiro",
        project_id="test-project",
    )
    findings = (
        '{"findings":[{"severity":"medium","file":"internal/resolve/resolver.go",'
        '"line":421,"claim":"AI failure silently skips the file",'
        '"evidence":"the fallthrough leaves resolutions empty"}]}'
    )

    result = _run_hook(script, {}, env={"KIRO_RESULT": findings}, api_url=url)

    assert result.returncode == 0
    content = state["last_payload"]["content"]
    assert "## Review findings (1)" in content
    assert "[medium] `internal/resolve/resolver.go:421`" in content
    assert "AI failure silently skips the file" in content
    assert "evidence: the fallthrough leaves resolutions empty" in content
    assert '{"findings"' not in content


def test_kiro_stop_saves_fenced_json_findings_as_markdown(
    tmp_path: Path, hook_api_server
) -> None:
    """kiro wraps the findings envelope in a ```json fence — strip it and
    render the same markdown (the shape that produced unreadable saves)."""
    state, url = hook_api_server
    script = _render_and_write(
        tmp_path,
        KIRO_STOP_HOOK_TEMPLATE,
        source_tag="kiro-hook",
        client_tag="kiro",
        ide_tag="kiro",
        project_id="test-project",
    )
    fenced = (
        "```json\n"
        '{"findings":[{"severity":"high","file":"a.swift","line":9,'
        '"claim":"stale snapshot","evidence":"guard returns early\\nsecond line"}]}'
        "\n```"
    )

    result = _run_hook(script, {}, env={"KIRO_RESULT": fenced}, api_url=url)

    assert result.returncode == 0
    content = state["last_payload"]["content"]
    assert "## Review findings (1)" in content
    assert "[high] `a.swift:9` — stale snapshot" in content
    # multi-line evidence is flattened to one line
    assert "evidence: guard returns early second line" in content


def test_agy_stop_saves_fenced_json_verdicts_as_markdown(
    tmp_path: Path, hook_api_server
) -> None:
    """agy panel output uses a verdicts envelope; render it instead of storing
    the fenced one-line JSON blob that exposed this regression."""
    state, url = hook_api_server
    script = _render_and_write(
        tmp_path,
        KIRO_STOP_HOOK_TEMPLATE,
        source_tag="agy-hook",
        client_tag="agy",
        ide_tag="agy",
        project_id="test-project",
    )
    fenced = (
        "```json\n"
        '{"verdicts":[{"ref":"[claude:claude-opus-4-8#0]",'
        '"stance":"concede","reason":"Ignoring failure causes flaky\\n'
        'tests."}]}\n'
        "```"
    )

    result = _run_hook(script, {}, env={"KIRO_RESULT": fenced}, api_url=url)

    assert result.returncode == 0
    content = state["last_payload"]["content"]
    assert "## Panel verdicts (1)" in content
    assert "[concede] `[claude:claude-opus-4-8#0]`" in content
    assert "Ignoring failure causes flaky tests." in content
    assert '"verdicts"' not in content


def test_kiro_stop_non_findings_json_saved_verbatim(
    tmp_path: Path, hook_api_server
) -> None:
    """JSON that is not a findings envelope passes through unchanged."""
    state, url = hook_api_server
    script = _render_and_write(
        tmp_path,
        KIRO_STOP_HOOK_TEMPLATE,
        source_tag="kiro-hook",
        client_tag="kiro",
        ide_tag="kiro",
        project_id="test-project",
    )
    payload = (
        '{"status":"ok","message":"deployment completed successfully on the '
        'remote server after fast-forwarding the checkout to v1.24.0"}'
    )

    result = _run_hook(script, {}, env={"KIRO_RESULT": payload}, api_url=url)

    assert result.returncode == 0
    assert payload in state["last_payload"]["content"]


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


def test_user_prompt_submit_uses_workspace_project_id(
    tmp_path: Path, hook_api_server
) -> None:
    state, url = hook_api_server
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".mem-mesh").mkdir()
    (workspace / ".mem-mesh" / "project-id").write_text(
        "workspace-project\n", encoding="utf-8"
    )
    script = _render_and_write(
        tmp_path,
        USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
        source_tag="cursor-hook",
        client_tag="cursor",
        project_id="test-project",
    )

    result = _run_hook(
        script,
        {
            "prompt": (
                "이전에 결정한 아키텍처와 저장된 메모리를 찾아줘. Cursor agent "
                "beforeSubmitPrompt가 workspace.current_dir 기준 project_id를 써야 합니다."
            ),
            "workspace_roots": [str(workspace)],
        },
        api_url=url,
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert state["last_payload"]["project_id"] == "workspace-project"
    assert state["last_payload"]["client"] == "cursor"


def test_session_end_uses_workspace_project_id(tmp_path: Path, hook_api_server) -> None:
    state, url = hook_api_server
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".mem-mesh").mkdir()
    (workspace / ".mem-mesh" / "project-id").write_text(
        "workspace-project\n", encoding="utf-8"
    )
    script = _render_and_write(
        tmp_path,
        SESSION_END_HOOK_TEMPLATE,
        source_tag="cursor-hook",
        client_tag="cursor",
        project_id="test-project",
    )

    result = _run_hook(
        script,
        {"workspace_roots": [str(workspace)]},
        api_url=url,
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert state["last_path"].endswith(
        "/api/work/sessions/end-by-project/workspace-project"
    )


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
            state["last_path"] = self.path
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length)
            state["last_body"] = raw.decode("utf-8")
            try:
                state["last_payload"] = json.loads(state["last_body"])
            except json.JSONDecodeError:
                state["last_payload"] = None
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


@pytest.fixture()
def memory_search_server():
    """Mock memory search endpoint used by SubagentStart."""
    state: dict = {"response": {"results": []}, "queries": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler contract
            parsed = urlparse(self.path)
            state["queries"].append(parsed)
            if parsed.path != "/api/memories/search":
                self.send_error(404)
                return
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
def precompact_api_server():
    """Mock PreCompact endpoints and record session-end side effects."""
    state: dict = {"post_paths": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 — BaseHTTPRequestHandler contract
            state["post_paths"].append(self.path)
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler contract
            body = json.dumps({"pins": []}).encode("utf-8")
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
    result = _run_hook(script, {"prompt": NO_KEYWORD_PROMPT}, api_url=url)
    assert result.returncode == 0
    assert PIN_REMINDER_TEXT in result.stdout


def test_codex_user_prompt_submit_compact_stdout_keeps_full_payload(
    tmp_path: Path, hook_api_server
) -> None:
    state, url = hook_api_server
    long_prompt = "이전에 결정한 내용을 다시 보고 싶습니다. " + ("가" * 2000)
    long_context = "Related memory\n" + ("details\n" * 500)
    state["response"] = {"hookSpecificOutput": {"additionalContext": long_context}}
    script = _render_and_write(
        tmp_path,
        USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
        source_tag="codex-hook",
        client_tag="codex",
        hook_output_mode="compact",
        project_id="test-project",
    )

    result = _run_hook(script, {"prompt": long_prompt}, api_url=url)

    assert result.returncode == 0
    context = _extract_context(json.loads(result.stdout))
    assert context.startswith("Related memory")
    assert len(context) <= 1200
    assert len(context) < len(long_context)
    assert state["last_payload"]["prompt"] == long_prompt
    assert state["last_payload"]["client"] == "codex"


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
    result = _run_hook(script, {"prompt": NO_KEYWORD_PROMPT}, api_url=url)
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
    result = _run_hook(script, {"prompt": NO_KEYWORD_PROMPT}, api_url=url)
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


def test_subagent_start_quiet_stdout_still_queries_context(
    tmp_path: Path, memory_search_server
) -> None:
    state, url = memory_search_server
    state["response"] = {
        "results": [{"content": "architecture decision " + ("x" * 500)}]
    }
    script = _render_and_write(
        tmp_path,
        SUBAGENT_START_HOOK_TEMPLATE,
        hook_output_mode="quiet",
        project_id="test-project",
    )

    result = _run_hook(
        script,
        {"agent_type": "Plan", "agent_id": "test-456"},
        api_url=url,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""
    assert len(state["queries"]) == 1
    assert state["queries"][0].path == "/api/memories/search"


def test_precompact_quiet_stdout_still_ends_session(
    tmp_path: Path, precompact_api_server
) -> None:
    state, url = precompact_api_server
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": "버그를 수정했습니다. error를 해결했습니다."},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    script = _render_and_write(
        tmp_path,
        PRECOMPACT_HOOK_TEMPLATE,
        hook_output_mode="quiet",
        project_id="test-project",
    )

    result = _run_hook(script, {"transcript_path": str(transcript)}, api_url=url)

    assert result.returncode == 0
    assert result.stdout.strip() == ""
    assert len(state["post_paths"]) == 1
    assert state["post_paths"][0].startswith("/api/work/sessions/end-by-project/")


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
