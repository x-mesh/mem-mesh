"""Redaction of hook_events at the recording path.

The stop/subagent/prompt hooks persist whole user and assistant turns to the
``hook_events`` table (the replay dataset). ``_record`` must scrub secrets/PII
before they land there so the accumulated corpus stays clean (M4) — the
existing tests only covered the *memory save* path (``_save_memory``), not the
raw event stream. ``None`` fields must pass through untouched.
"""

import pytest

from app.core.services.hook import HookService
from app.web.dashboard.route_modules import hooks as http_hooks

# A prompt/answer laced with the credential shapes redact_secrets knows about.
_SECRET_PROMPT = (
    "이전 결정을 확인해줘. sk-ant-1234567890abcdef 토큰과 "
    "Bearer abc.def.ghijklmnop 그리고 user@example.com 은 저장되면 안 됩니다."
)
_SECRET_ANSWER = (
    "버그를 수정했습니다. API_KEY=supersecretvalue123 와 "
    "AKIAIOSFODNN7EXAMPLE 는 마스킹되어야 합니다."
)


def _assert_scrubbed(stored: str) -> None:
    assert stored is not None
    assert "<REDACTED>" in stored
    assert "sk-ant-1234567890abcdef" not in stored
    assert "Bearer abc.def.ghijklmnop" not in stored
    assert "user@example.com" not in stored


# ─────────────────────────── _redact_optional ────────────────────────────


def test_redact_optional_passes_none_through():
    assert http_hooks._redact_optional(None) is None


def test_redact_optional_masks_secret_text():
    out = http_hooks._redact_optional(_SECRET_PROMPT)
    _assert_scrubbed(out)


def test_redact_optional_leaves_clean_text_untouched():
    clean = "이전 결정을 확인하고 architecture 정리. 민감정보 없음."
    assert http_hooks._redact_optional(clean) == clean


# ──────────────────── _record → hook_events persistence ───────────────────


@pytest.mark.asyncio
async def test_record_redacts_prompt_in_hook_events(temp_db):
    """A secret-laden prompt is masked in the hook_events row it produces."""
    service = HookService(temp_db)
    sid = "redact-prompt-session"

    await http_hooks._record(
        service,
        project_id="proj",
        ide_session_id=sid,
        event_name="UserPromptSubmit",
        prompt=_SECRET_PROMPT,
    )

    stored = await service.get_last_prompt(sid)
    _assert_scrubbed(stored)


@pytest.mark.asyncio
async def test_record_redacts_assistant_message_in_hook_events(temp_db):
    """A secret-laden assistant turn is masked before it reaches storage."""
    service = HookService(temp_db)
    sid = "redact-answer-session"

    await http_hooks._record(
        service,
        project_id="proj",
        ide_session_id=sid,
        event_name="Stop",
        assistant_message=_SECRET_ANSWER,
    )

    row = await temp_db.fetchone(
        "SELECT assistant_message FROM hook_events WHERE ide_session_id = ?",
        (sid,),
    )
    stored = row["assistant_message"]
    assert stored is not None
    assert "<REDACTED>" in stored
    assert "supersecretvalue123" not in stored
    assert "AKIAIOSFODNN7EXAMPLE" not in stored
    assert "API_KEY=<REDACTED>" in stored  # key name kept, value masked


@pytest.mark.asyncio
async def test_record_leaves_none_fields_null_in_hook_events(temp_db):
    """A prompt-only event stores NULL assistant_message (and vice versa) —
    the redact step must not coerce an absent field into a masked string."""
    service = HookService(temp_db)
    sid = "redact-none-session"

    await http_hooks._record(
        service,
        project_id="proj",
        ide_session_id=sid,
        event_name="UserPromptSubmit",
        prompt="이전 결정 확인",
        assistant_message=None,
    )

    row = await temp_db.fetchone(
        "SELECT prompt, assistant_message FROM hook_events WHERE ide_session_id = ?",
        (sid,),
    )
    assert row["prompt"] == "이전 결정 확인"
    assert row["assistant_message"] is None


@pytest.mark.asyncio
async def test_record_redaction_preserves_save_marker_detection(temp_db):
    """Redaction must not blind the save-marker autodetection: a turn that
    references mcp__mem-mesh__add still resets the turns-since-save counter."""
    service = HookService(temp_db)
    sid = "redact-savemarker-session"

    await http_hooks._record(
        service,
        project_id="proj",
        ide_session_id=sid,
        event_name="UserPromptSubmit",
        prompt="첫 질문",
    )
    # An assistant turn that saved via MCP *and* leaked a secret. Redaction
    # scrubs the secret but leaves the mcp marker, so saved_memory stays true.
    await http_hooks._record(
        service,
        project_id="proj",
        ide_session_id=sid,
        event_name="Stop",
        assistant_message=(
            "저장 완료 mcp__mem-mesh__add — user@example.com 은 마스킹됨."
        ),
    )
    await http_hooks._record(
        service,
        project_id="proj",
        ide_session_id=sid,
        event_name="UserPromptSubmit",
        prompt="둘째 질문",
    )

    # Save detected on the Stop turn → only the trailing UserPromptSubmit counts.
    assert await service.turns_since_save(sid) == 1
