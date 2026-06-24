"""Cross-path hook behavior contracts.

These tests intentionally encode HTTP-vs-command hook parity as observable
behavior. Some assertions may fail until the server-side and shell-side P2 fixes
land; keep them as real assertions so regressions remain visible.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.cli.hooks.renderer import _render_template
from app.cli.hooks.templates import STOP_DECIDE_HOOK_TEMPLATE
from app.core.schemas.hooks import StopPayload
from app.core.services.hook import HookService
from app.web.dashboard.route_modules import hooks as http_hooks

HAS_JQ = shutil.which("jq") is not None
HAS_BASH = shutil.which("bash") is not None


def _render_stop_decide(tmp_path: Path) -> Path:
    script = _render_template(
        STOP_DECIDE_HOOK_TEMPLATE,
        "http://localhost:1",
        source_tag="test-hook",
        ide_tag="claude",
        client_tag="claude_code",
        project_id="test-project",
    )
    path = tmp_path / "stop-decide.sh"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return path


def _render_codex_stop_decide(tmp_path: Path) -> Path:
    script = _render_template(
        STOP_DECIDE_HOOK_TEMPLATE,
        "http://localhost:1",
        source_tag="codex-hook",
        ide_tag="codex",
        client_tag="codex",
        project_id="test-project",
    )
    path = tmp_path / "codex-stop-decide.sh"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return path


def _install_fake_git_and_curl(tmp_path: Path, *, toplevel: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    git = bin_dir / "git"
    git.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "rev-parse" ] && [ "$2" = "--show-toplevel" ]; then\n'
        "  printf '%s\\n' \"$FAKE_GIT_TOPLEVEL\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    git.chmod(0o755)

    curl = bin_dir / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        "payload=''\n"
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = "-d" ]; then\n'
        "    shift\n"
        "    payload=$1\n"
        "  fi\n"
        "  shift || break\n"
        "done\n"
        'if [ -n "${CAPTURED_CURL_PAYLOAD:-}" ] && [ -n "$payload" ]; then\n'
        '  printf \'%s\' "$payload" > "$CAPTURED_CURL_PAYLOAD"\n'
        "fi\n"
        "printf '201'\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)

    return bin_dir


def _run_stop_decide(
    tmp_path: Path,
    payload: dict[str, Any],
    *,
    toplevel: str = "/tmp/Mem.Mesh-wt-ABCDEF",
    script_path: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
    if not HAS_JQ or not HAS_BASH:
        pytest.skip("bash and jq are required to execute command hook contracts")

    script = script_path or _render_stop_decide(tmp_path)
    capture_path = tmp_path / "curl-payload.json"
    bin_dir = _install_fake_git_and_curl(tmp_path, toplevel=toplevel)
    # The rendered hook reads its URL from ~/.mem-mesh/api_url (no env fallback),
    # so pin HOME at the tmp dir: with no config file there the hook uses the
    # baked default URL (http://localhost:1). The fake curl captures the payload
    # regardless of which URL it is aimed at.
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
        "FAKE_GIT_TOPLEVEL": toplevel,
        "CAPTURED_CURL_PAYLOAD": str(capture_path),
    }
    env.pop("MEM_MESH_API_URL", None)
    env.pop("MEM_MESH_HOOK_TOKEN", None)

    result = subprocess.run(
        ["bash", str(script)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        cwd=tmp_path,
    )
    captured = (
        json.loads(capture_path.read_text(encoding="utf-8"))
        if capture_path.exists()
        else None
    )
    return result, captured


def test_codex_command_stop_stamps_client_metadata(tmp_path: Path) -> None:
    """Codex global command hooks must not be classified as Claude Code."""
    result, command_payload = _run_stop_decide(
        tmp_path,
        {
            "stop_hook_active": False,
            "last_assistant_message": (
                "버그 수정과 decision 기록이 필요한 충분히 긴 응답입니다. "
                "Codex 전역 훅에서 저장될 때 client/source 메타데이터가 "
                "claude_code가 아니라 codex로 전달되어야 합니다."
            ),
        },
        toplevel="/repo/mem-mesh",
        script_path=_render_codex_stop_decide(tmp_path),
    )

    assert result.returncode == 0
    assert command_payload is not None, result.stdout + result.stderr
    assert command_payload["client"] == "codex"
    assert command_payload["hook_source"] == "codex-hook"


def test_project_id_normalization_parity_between_http_and_command_paths(
    tmp_path: Path,
) -> None:
    """A worktree/case/path variant must converge to one canonical project id.

    Per the agreed contract the command hook sends a RAW basename and the SERVER
    normalizes (server = single source of truth), so the command payload is
    normalized with the same server function before comparison. The message is
    >=100 chars to clear the command hook's length filter.
    """
    raw_repo_path = "/Users/dev/work/OCI.Tools-wt-ABCDEF"

    http_project_id = http_hooks._project_id(cwd=raw_repo_path, explicit=None)
    result, command_payload = _run_stop_decide(
        tmp_path,
        {
            "stop_hook_active": False,
            "last_assistant_message": (
                "버그를 수정했고 architecture decision을 정리했습니다. 이 변경은 프로젝트 "
                "전반의 project_id 정규화 정합성을 보장하기 위한 것으로, command hook의 save "
                "path가 정상적으로 실행되어 메모리에 저장될 만큼 충분히 긴 메시지입니다."
            ),
        },
        toplevel=raw_repo_path,
    )

    assert result.returncode == 0
    assert command_payload is not None, result.stdout + result.stderr
    # Command hook sends RAW basename; the server normalizer converges it onto
    # the same canonical id the HTTP path resolves to.
    normalized_command_id = http_hooks._normalize_project_id(
        command_payload["project_id"]
    )
    assert normalized_command_id == http_project_id == "oci-tools"


@pytest.mark.asyncio
async def test_turn_counter_counts_user_prompt_submit_only(temp_db) -> None:
    """Stop events must not advance the save-reminder N-turn counter."""
    service = HookService(temp_db)
    session_id = "turn-counter-session"

    await service.record_event(
        project_id="p",
        ide_session_id=session_id,
        event_name="UserPromptSubmit",
        prompt="first prompt",
        saved_memory=False,
    )
    await service.record_event(
        project_id="p",
        ide_session_id=session_id,
        event_name="Stop",
        assistant_message="first answer without save",
        saved_memory=False,
    )
    await service.record_event(
        project_id="p",
        ide_session_id=session_id,
        event_name="Stop",
        assistant_message="second answer without save",
        saved_memory=False,
    )
    await service.record_event(
        project_id="p",
        ide_session_id=session_id,
        event_name="UserPromptSubmit",
        prompt="second prompt",
        saved_memory=False,
    )

    # Contract: the reminder counter follows user submissions only; Stop is an
    # implementation detail of the response lifecycle and should not inflate N.
    assert await service.turns_since_save(session_id) == 2


@pytest.mark.asyncio
async def test_http_save_memory_redacts_secrets_before_persisting(monkeypatch) -> None:
    """Hook save path must never persist API keys, bearer tokens, or email PII."""
    captured: dict[str, Any] = {}

    class FakeEmbedding:
        is_ready = True

    class FakeMemoryService:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return {"id": "mem-1"}

    monkeypatch.setattr(
        http_hooks,
        "get_services",
        lambda: {
            "memory_service": FakeMemoryService(),
            "embedding_service": FakeEmbedding(),
        },
    )

    saved = await http_hooks._save_memory(
        "proj",
        (
            "버그 수정 내용입니다. sk-ant-1234567890abcdef 토큰과 "
            "Bearer abc.def.ghi 그리고 user@example.com 은 저장 전에 마스킹되어야 합니다."
        ),
        "bug",
        tags=["auto-save"],
    )

    assert saved is True
    assert "<REDACTED>" in captured["content"]
    assert "sk-ant-1234567890abcdef" not in captured["content"]
    assert "Bearer abc.def.ghi" not in captured["content"]
    assert "user@example.com" not in captured["content"]


@pytest.mark.asyncio
async def test_http_save_memory_uses_hook_client_metadata(monkeypatch) -> None:
    """Persisted hook memories should keep the originating tool identity."""
    captured: dict[str, Any] = {}

    class FakeEmbedding:
        is_ready = True

    class FakeMemoryService:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return {"id": "mem-1"}

    monkeypatch.setattr(
        http_hooks,
        "get_services",
        lambda: {
            "memory_service": FakeMemoryService(),
            "embedding_service": FakeEmbedding(),
        },
    )

    saved = await http_hooks._save_memory(
        "proj",
        "Codex hook metadata should be preserved.",
        "decision",
        tags=["auto-save"],
        source="codex-hook",
        client="codex",
    )

    assert saved is True
    assert captured["source"] == "codex-hook"
    assert captured["client"] == "codex"


@pytest.mark.asyncio
async def test_noise_artifacts_skip_save_in_http_stop_path(monkeypatch) -> None:
    """HTTP Stop must not save system-reminder/task-notification artifacts."""
    save_memory = AsyncMock(return_value=True)
    monkeypatch.setattr(http_hooks, "_save_memory", save_memory)

    class FakeHookService:
        async def record_event(self, **kwargs):
            return 1

        async def get_last_prompt(self, ide_session_id: str):
            return "normal user prompt"

    payload = StopPayload(
        session_id="noise-session",
        cwd="/repo/mem-mesh",
        stop_hook_active=False,
        last_assistant_message=(
            "<system-reminder> 버그를 수정했고 decision을 기록하라는 시스템 아티팩트입니다. "
            "길이는 충분하지만 저장되면 안 됩니다. </system-reminder>"
        ),
    )

    response = await http_hooks.stop(payload, hook_service=FakeHookService())

    assert response.status_code == 200
    save_memory.assert_not_awaited()


def test_command_stop_forwards_raw_payload_for_server_to_filter(
    tmp_path: Path,
) -> None:
    """The command Stop hook is a thin forwarder now: noise filtering moved
    server-side (covered by test_noise_artifacts_skip_save_in_http_stop_path).
    So the command hook must forward the raw event verbatim — it must NOT drop
    it locally — and the server decides whether to persist."""
    noise = (
        "<task-notification> 버그를 수정했고 decision을 완료했다는 시스템 "
        "아티팩트입니다. 충분히 길지만 메모리에 저장되면 안 됩니다. </task-notification>"
    )
    result, command_payload = _run_stop_decide(
        tmp_path,
        {"stop_hook_active": False, "last_assistant_message": noise},
        toplevel="/repo/mem-mesh",
    )

    assert result.returncode == 0
    # Raw forward: the hook sends the event unfiltered; the server skips the save.
    assert command_payload is not None
    assert command_payload["last_assistant_message"] == noise


def test_command_stop_truncates_multibyte_text_on_character_boundary(
    tmp_path: Path,
) -> None:
    """Rendered command hook must produce valid, uncorrupted UTF-8 for Korean text."""
    long_korean = "버그 수정 완료. " + ("가나다라마바사아자차카타파하" * 900)
    result, command_payload = _run_stop_decide(
        tmp_path,
        {"stop_hook_active": False, "last_assistant_message": long_korean},
        toplevel="/repo/mem-mesh",
    )

    assert result.returncode == 0
    assert command_payload is not None, result.stdout + result.stderr
    content = command_payload["last_assistant_message"]
    content.encode("utf-8").decode("utf-8")
    assert "\ufffd" not in content
    assert content == long_korean  # forwarded verbatim; truncation is server-side
