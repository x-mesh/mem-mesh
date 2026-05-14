"""HookService 테스트.

Claude Code HTTP hook 이벤트 스트림 기반 세션 상태 재구성을 검증한다:
continuation 감지, Q&A 페어링, 턴 카운터, 보존 정리.
"""

import os
import tempfile

import pytest

from app.cli.hooks.keywords import match_category
from app.core.database.base import Database
from app.core.services.hook import HookService


@pytest.fixture
async def temp_db():
    """초기화된 임시 Database 인스턴스"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    db = Database(db_path)
    await db.connect()
    yield db
    await db.close()

    for ext in ["", "-wal", "-shm"]:
        path = db_path + ext
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture
async def hook_service(temp_db):
    return HookService(temp_db)


class TestHookEventTable:
    """hook_events 테이블 생성 검증"""

    @pytest.mark.asyncio
    async def test_table_exists(self, temp_db):
        row = await temp_db.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hook_events'"
        )
        assert row is not None


class TestRecordEvent:
    """record_event 턴 인덱스 증가"""

    @pytest.mark.asyncio
    async def test_turn_index_increments_per_session(self, hook_service):
        t0 = await hook_service.record_event(
            project_id="p", ide_session_id="s1", event_name="SessionStart"
        )
        t1 = await hook_service.record_event(
            project_id="p",
            ide_session_id="s1",
            event_name="UserPromptSubmit",
            prompt="hello",
        )
        t2 = await hook_service.record_event(
            project_id="p",
            ide_session_id="s1",
            event_name="Stop",
            assistant_message="done",
        )
        assert (t0, t1, t2) == (0, 1, 2)

    @pytest.mark.asyncio
    async def test_turn_index_independent_per_session(self, hook_service):
        await hook_service.record_event(
            project_id="p", ide_session_id="s1", event_name="SessionStart"
        )
        t = await hook_service.record_event(
            project_id="p", ide_session_id="s2", event_name="SessionStart"
        )
        assert t == 0

    @pytest.mark.asyncio
    async def test_save_marker_auto_detected(self, hook_service):
        await hook_service.record_event(
            project_id="p",
            ide_session_id="s1",
            event_name="Stop",
            assistant_message="저장합니다 mcp__mem-mesh__add 호출",
        )
        row = await hook_service.db.fetchone(
            "SELECT saved_memory FROM hook_events WHERE ide_session_id='s1'"
        )
        assert row["saved_memory"] == 1


class TestContinuation:
    """continuation 감지 — 같은 session_id 재등장"""

    @pytest.mark.asyncio
    async def test_fresh_session_is_not_continuation(self, hook_service):
        assert await hook_service.is_continuation("never-seen") is False

    @pytest.mark.asyncio
    async def test_seen_session_is_continuation(self, hook_service):
        await hook_service.record_event(
            project_id="p",
            ide_session_id="s1",
            event_name="UserPromptSubmit",
            prompt="hi",
        )
        assert await hook_service.is_continuation("s1") is True

    @pytest.mark.asyncio
    async def test_empty_session_id_is_not_continuation(self, hook_service):
        assert await hook_service.is_continuation("") is False


class TestQAPairing:
    """get_last_prompt — transcript 파일 없이 Q 페어링"""

    @pytest.mark.asyncio
    async def test_returns_most_recent_prompt(self, hook_service):
        await hook_service.record_event(
            project_id="p",
            ide_session_id="s1",
            event_name="UserPromptSubmit",
            prompt="first question",
        )
        await hook_service.record_event(
            project_id="p",
            ide_session_id="s1",
            event_name="Stop",
            assistant_message="answer",
        )
        await hook_service.record_event(
            project_id="p",
            ide_session_id="s1",
            event_name="UserPromptSubmit",
            prompt="second question",
        )
        assert await hook_service.get_last_prompt("s1") == "second question"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_prompt(self, hook_service):
        await hook_service.record_event(
            project_id="p", ide_session_id="s1", event_name="SessionStart"
        )
        assert await hook_service.get_last_prompt("s1") is None


class TestTurnsSinceSave:
    """turns_since_save — 이벤트 스트림 기반 턴 카운터"""

    @pytest.mark.asyncio
    async def test_counts_all_turns_when_never_saved(self, hook_service):
        for i in range(3):
            await hook_service.record_event(
                project_id="p",
                ide_session_id="s1",
                event_name="UserPromptSubmit",
                prompt=f"q{i}",
            )
        assert await hook_service.turns_since_save("s1") == 3

    @pytest.mark.asyncio
    async def test_resets_after_save(self, hook_service):
        await hook_service.record_event(
            project_id="p",
            ide_session_id="s1",
            event_name="UserPromptSubmit",
            prompt="q0",
        )
        await hook_service.record_event(
            project_id="p",
            ide_session_id="s1",
            event_name="Stop",
            assistant_message="saved mcp__mem-mesh__add",
        )
        await hook_service.record_event(
            project_id="p",
            ide_session_id="s1",
            event_name="UserPromptSubmit",
            prompt="q1",
        )
        # Stop(saved) 이후 UserPromptSubmit 1턴만 카운트
        assert await hook_service.turns_since_save("s1") == 1

    @pytest.mark.asyncio
    async def test_session_start_does_not_count_as_turn(self, hook_service):
        await hook_service.record_event(
            project_id="p", ide_session_id="s1", event_name="SessionStart"
        )
        assert await hook_service.turns_since_save("s1") == 0


class TestPrune:
    """prune_old_events — 보존 정리"""

    @pytest.mark.asyncio
    async def test_prune_keeps_recent_events(self, hook_service):
        await hook_service.record_event(
            project_id="p", ide_session_id="s1", event_name="SessionStart"
        )
        removed = await hook_service.prune_old_events(retention_days=14)
        assert removed == 0
        assert await hook_service.is_continuation("s1") is True

    @pytest.mark.asyncio
    async def test_prune_removes_old_events(self, hook_service):
        await hook_service.record_event(
            project_id="p", ide_session_id="s1", event_name="SessionStart"
        )
        # created_at을 과거로 강제 변경
        await hook_service.db.execute(
            "UPDATE hook_events SET created_at = '2000-01-01T00:00:00+00:00'"
        )
        hook_service.db.connection.commit()
        removed = await hook_service.prune_old_events(retention_days=14)
        assert removed == 1
        assert await hook_service.is_continuation("s1") is False


class TestKeywordMatcher:
    """match_category — 서버 사이드 키워드 분류 (bash 블록과 동일 동작)"""

    @pytest.mark.parametrize(
        "message,expected",
        [
            ("버그를 수정 완료했습니다. fix: null check", "bug"),
            ("아키텍처를 전환하기로 결정했습니다", "decision"),
            ("새로운 함수를 구현 완료했습니다", "code_snippet"),
            ("프로덕션 장애가 발생해서 롤백했습니다", "incident"),
            ("그냥 단순한 질문입니다", "SKIP"),
            ("", "SKIP"),
        ],
    )
    def test_match_category(self, message, expected):
        assert match_category(message) == expected

    def test_extra_keywords_do_not_mutate_module_state(self):
        match_category("배포 완료", extra_kw="bug:커스텀패턴")
        # 두 번째 호출에서 커스텀 패턴이 누적되면 안 됨
        assert match_category("커스텀패턴 완료") == "SKIP"
