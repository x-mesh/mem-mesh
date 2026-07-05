"""Derivability pre-check (R17).

Two layers:

* Pure rule functions in ``quality_gate`` — ``is_conversation_dump`` /
  ``is_derivable_from_git`` / ``derivability_hint``.
* Write-time routing in ``MemoryService.create`` — a flagged memory is still
  stored, then routed to the async improve worker (never a synchronous LLM
  call, per CLAUDE.md L1/L5). When no chat LLM is configured the enqueue is
  skipped (nothing could drain it) and only the hint is surfaced.
"""

from unittest.mock import AsyncMock

import pytest

from app.core.services.quality_gate import (
    derivability_hint,
    is_conversation_dump,
    is_derivable_from_git,
)

# A raw stop-hook Q&A pairing dump (Q: …\n\nA: … format).
_QA_DUMP = (
    "Q: How should the derivable-content pre-check behave on the write path?\n\n"
    "A: Store the memory, then enqueue it to the async improve worker so nothing "
    "blocks the save and no LLM runs synchronously on the add path."
)


# ── pure detection: is_conversation_dump ────────────────────────────────────
class TestIsConversationDump:
    def test_qa_pairing_format_is_dump(self):
        assert is_conversation_dump(_QA_DUMP) is True

    def test_multi_turn_markers_is_dump(self):
        content = (
            "User: what broke the build?\n"
            "Assistant: a missing import in memory.py\n"
            "User: fix it please\n"
        )
        assert is_conversation_dump(content) is True

    def test_normal_note_not_dump(self):
        content = "SQLite WAL 모드로 변경 결정. 동시 읽기 성능이 개선되었다. " * 3
        assert is_conversation_dump(content) is False

    def test_code_block_not_dump(self):
        content = "def add(a, b):\n    return a + b\n\nresult = add(1, 2)\n" * 3
        assert is_conversation_dump(content) is False

    def test_single_turn_marker_not_dump(self):
        # One lone marker is not a transcript (threshold is two turns).
        content = "User: this is just a single quoted line inside a note. " * 3
        assert is_conversation_dump(content) is False

    def test_empty_not_dump(self):
        assert is_conversation_dump("") is False


# ── pure detection: is_derivable_from_git ───────────────────────────────────
class TestIsDerivableFromGit:
    def test_diff_git_marker(self):
        content = (
            "diff --git a/app/core/services/memory.py b/app/core/services/memory.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/app/core/services/memory.py\n"
            "+++ b/app/core/services/memory.py\n"
        )
        assert is_derivable_from_git(content) is True

    def test_hunk_header(self):
        content = "some context text\n@@ -10,6 +10,8 @@ def create(self):\n    pass\n"
        assert is_derivable_from_git(content) is True

    def test_git_log_oneline_list(self):
        content = (
            "a5e70cb chore(release): mem-mesh@1.21.0\n"
            "eaf1655 feat(app): add multi-IDE hook support\n"
            "35a573d docs: add hooks installation instructions\n"
        )
        assert is_derivable_from_git(content) is True

    def test_two_log_lines_below_threshold(self):
        content = (
            "a5e70cb chore(release): mem-mesh@1.21.0\n"
            "eaf1655 feat(app): add multi-IDE hook support\n"
        )
        assert is_derivable_from_git(content) is False

    def test_normal_note_not_derivable(self):
        content = (
            "결정: 인덱스를 복합 인덱스로 교체하여 쿼리 성능을 3배 향상시켰다. " * 3
        )
        assert is_derivable_from_git(content) is False

    def test_code_snippet_hex_no_false_positive(self):
        # Hex-heavy code lines match the git-log heuristic, so it is skipped for
        # the code_snippet category (legitimate code is the expected content).
        content = (
            "deadbeef = 0xdeadbeef  # sentinel value\n"
            "cafef00d = compute(deadbeef)\n"
            "abcdef0 = hash(cafef00d)\n"
        )
        # Without the category guard this would false-positive.
        assert is_derivable_from_git(content) is True
        assert is_derivable_from_git(content, category="code_snippet") is False

    def test_diff_still_flagged_in_code_snippet(self):
        # Unambiguous diff markers are flagged regardless of category.
        content = "diff --git a/x b/x\n@@ -1 +1 @@\n-old\n+new\n"
        assert is_derivable_from_git(content, category="code_snippet") is True

    def test_empty_not_derivable(self):
        assert is_derivable_from_git("") is False


# ── pure detection: derivability_hint ───────────────────────────────────────
class TestDerivabilityHint:
    def test_conversation_dump_hint(self):
        assert derivability_hint(_QA_DUMP) == "conversation_dump"

    def test_git_hint(self):
        assert derivability_hint("diff --git a/x b/x\n@@ -1 +1 @@\n") == (
            "derivable_from_git"
        )

    def test_none_for_normal_content(self):
        content = "정상적인 아키텍처 결정 노트입니다. 배경과 이유를 함께 기록한다. " * 3
        assert derivability_hint(content) is None

    def test_code_snippet_no_hint(self):
        code = "def f():\n    return 42\n" * 5
        assert derivability_hint(code, category="code_snippet") is None


# ── write-time routing through MemoryService.create ─────────────────────────
_NORMAL_NOTE = (
    "결정: 검색 파이프라인의 리랭킹은 GPU 배포에서만 활성화한다. CPU에서는 "
    "cross-encoder 반복 추론이 시스템을 불안정하게 만들기 때문이다. 배경과 이유를 "
    "함께 남긴다. " * 2
)

_CODE_SNIPPET = (
    "```python\n"
    "def scaled_threshold(base: float) -> float:\n"
    "    # arctic-ko scores lower than KURE; scale the cosine gate accordingly\n"
    "    return base * 0.85\n"
    "```\n"
    "이 함수는 임베딩 모델별로 코사인 임계값을 보정한다. 배경과 이유를 함께 기록한다."
)


async def _maintenance_rows(db, memory_id):
    """maintenance_queue rows for a memory (ensuring the table exists first)."""
    from app.core.services.maintenance import MaintenanceService

    await MaintenanceService(db).ensure_schema()
    return await db.fetchall(
        "SELECT operation, status FROM maintenance_queue WHERE memory_id = ?",
        (memory_id,),
    )


@pytest.mark.asyncio
async def test_qa_dump_saved_and_enqueued_when_llm_configured(
    memory_service_mocked, temp_db
):
    """Q:/A: dump → stored (status=saved) + an improve job is enqueued."""
    # db app_config value wins over env in ChatService.is_configured → configured.
    await temp_db.set_app_config("chat.llm_api_key", "sk-test-REDACTED")

    resp = await memory_service_mocked.create(
        content=_QA_DUMP, project_id="proj", category="decision", source="test"
    )

    assert resp.status == "saved"
    assert resp.quality_hint is not None
    assert "conversation_dump" in resp.quality_hint
    assert "등록됨" in resp.quality_hint

    rows = await _maintenance_rows(temp_db, resp.id)
    assert len(rows) == 1
    assert rows[0]["operation"] == "improve"
    assert rows[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_qa_dump_skips_enqueue_when_llm_not_configured(
    memory_service_mocked, temp_db, monkeypatch
):
    """LLM not configured → no enqueue (nothing could drain it), hint only."""
    from app.core.services import chat as chat_module

    monkeypatch.setattr(
        chat_module.ChatService,
        "is_configured",
        AsyncMock(return_value=False),
    )

    resp = await memory_service_mocked.create(
        content=_QA_DUMP, project_id="proj", category="decision", source="test"
    )

    assert resp.status == "saved"
    assert resp.quality_hint is not None
    assert "conversation_dump" in resp.quality_hint
    assert "LLM 미설정" in resp.quality_hint

    rows = await _maintenance_rows(temp_db, resp.id)
    assert rows == []


@pytest.mark.asyncio
async def test_normal_content_unaffected(memory_service_mocked, temp_db):
    """A distilled note is stored with no hint and no enqueue."""
    await temp_db.set_app_config("chat.llm_api_key", "sk-test-REDACTED")

    resp = await memory_service_mocked.create(
        content=_NORMAL_NOTE, project_id="proj", category="decision", source="test"
    )

    assert resp.status == "saved"
    assert resp.quality_hint is None

    rows = await _maintenance_rows(temp_db, resp.id)
    assert rows == []


@pytest.mark.asyncio
async def test_code_snippet_no_false_positive(memory_service_mocked, temp_db):
    """A legitimate code_snippet is not flagged as a dump/derivable."""
    await temp_db.set_app_config("chat.llm_api_key", "sk-test-REDACTED")

    resp = await memory_service_mocked.create(
        content=_CODE_SNIPPET,
        project_id="proj",
        category="code_snippet",
        source="test",
    )

    assert resp.status == "saved"
    assert resp.quality_hint is None

    rows = await _maintenance_rows(temp_db, resp.id)
    assert rows == []


@pytest.mark.asyncio
async def test_sync_add_path_makes_no_llm_call(
    memory_service_mocked, temp_db, monkeypatch
):
    """The add path enqueues but never runs the improve/enrich LLM inline."""
    from app.core.services import chat as chat_module

    await temp_db.set_app_config("chat.llm_api_key", "sk-test-REDACTED")

    refine = AsyncMock()
    enrich = AsyncMock()
    monkeypatch.setattr(chat_module.ChatService, "refine_memory_content", refine)
    monkeypatch.setattr(chat_module.ChatService, "enrich_memory_content", enrich)

    resp = await memory_service_mocked.create(
        content=_QA_DUMP, project_id="proj", category="decision", source="test"
    )

    # Enqueued for async processing …
    assert resp.quality_hint is not None
    assert "등록됨" in resp.quality_hint
    rows = await _maintenance_rows(temp_db, resp.id)
    assert len(rows) == 1
    # … but the LLM refine/enrich never runs on the synchronous write path.
    refine.assert_not_called()
    enrich.assert_not_called()
