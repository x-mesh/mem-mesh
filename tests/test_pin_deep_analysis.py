"""Pin 심층 분석 기반 테스트 — 에이전트 팀 분석에서 도출된 14개 테스트 케이스.

테스트 그룹:
1. expand="smart" 4-Tier 검증 (4 tests)
2. Promote before complete 정책 (3 tests)
3. Cross-session pin 연속성 (2 tests)
4. should_suggest 경계값 (4 tests)
5. Concurrent complete race condition (1 test)
"""

import asyncio
import pytest
import tempfile
import os

from app.core.database.base import Database
from app.core.services.pin import (
    PinService,
    PinAlreadyCompletedError,
)
from app.core.services.session import SessionService
from app.core.schemas.pins import PinResponse


@pytest.fixture
async def db():
    """테스트용 임시 데이터베이스"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    database = Database(db_path)
    await database.connect()

    yield database

    await database.close()
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
async def pin_service(db):
    return PinService(db)


@pytest.fixture
async def session_service(db):
    return SessionService(db)


@pytest.fixture
async def test_session(session_service):
    session = await session_service.get_or_create_active_session(
        project_id="test-project", user_id="test-user"
    )
    return session


# ========== 1. expand="smart" 4-Tier 검증 (4 tests) ==========


class TestSmartExpand4Tier:
    """session_resume expand='smart' 4-Tier 매트릭스 검증"""

    async def _create_pin(self, pin_service, content, importance, status="open"):
        """헬퍼: 핀 생성 후 선택적으로 완료"""
        pin = await pin_service.create_pin(
            project_id="test-project",
            content=content,
            importance=importance,
            user_id="test-user",
        )
        if status == "completed":
            await pin_service.complete_pin(pin.id)
        return pin

    async def test_tier1_active_important_full_content(
        self, session_service, pin_service, test_session
    ):
        """Tier 1: active + importance>=4 → full content + tags + created_at"""
        long_content = "A" * 300 + " 중요한 아키텍처 결정 사항입니다"
        await self._create_pin(pin_service, long_content, importance=5)

        ctx = await session_service.resume_last_session(
            project_id="test-project", user_id="test-user", expand="smart"
        )

        tier1_pins = [p for p in ctx.pins if p.get("_tier") == 1]
        assert len(tier1_pins) == 1

        pin = tier1_pins[0]
        assert pin["content"] == long_content  # 전체 내용, 잘리지 않음
        assert pin["importance"] == 5
        assert pin["status"] in ("open", "in_progress")
        assert "created_at" in pin
        assert "tags" in pin

    async def test_tier2_active_normal_truncated_200(
        self, session_service, pin_service, test_session
    ):
        """Tier 2: active + importance<4 → content[:200] + tags"""
        long_content = "B" * 300 + " 일반 진행중 작업"
        await self._create_pin(pin_service, long_content, importance=2)

        ctx = await session_service.resume_last_session(
            project_id="test-project", user_id="test-user", expand="smart"
        )

        tier2_pins = [p for p in ctx.pins if p.get("_tier") == 2]
        assert len(tier2_pins) == 1

        pin = tier2_pins[0]
        # 200자 초과 → 잘림 + "..."
        assert len(pin["content"]) <= 203  # 200 + "..."
        assert pin["content"].endswith("...")
        assert "tags" in pin

    async def test_tier3_completed_important_truncated_80(
        self, session_service, pin_service, test_session
    ):
        """Tier 3: completed + importance>=4 → content[:80]"""
        long_content = "C" * 200 + " 완료된 중요 작업"
        await self._create_pin(
            pin_service, long_content, importance=4, status="completed"
        )

        ctx = await session_service.resume_last_session(
            project_id="test-project", user_id="test-user", expand="smart"
        )

        tier3_pins = [p for p in ctx.pins if p.get("_tier") == 3]
        assert len(tier3_pins) == 1

        pin = tier3_pins[0]
        assert len(pin["content"]) <= 83  # 80 + "..."
        assert pin["content"].endswith("...")
        # Tier 3에는 tags가 포함되지 않음
        assert "tags" not in pin

    async def test_tier4_completed_normal_minimal(
        self, session_service, pin_service, test_session
    ):
        """Tier 4: completed + importance<4 → id + importance + status만"""
        content = "D" * 100 + " 완료된 일반 작업"
        await self._create_pin(
            pin_service, content, importance=2, status="completed"
        )

        ctx = await session_service.resume_last_session(
            project_id="test-project", user_id="test-user", expand="smart"
        )

        tier4_pins = [p for p in ctx.pins if p.get("_tier") == 4]
        assert len(tier4_pins) == 1

        pin = tier4_pins[0]
        assert "id" in pin
        assert "importance" in pin
        assert "status" in pin
        # content가 없거나 포함되지 않아야 함
        assert "content" not in pin


# ========== 2. Promote before complete 정책 (3 tests) ==========


class TestPromoteBeforeComplete:
    """미완료 Pin 승격 정책 테스트"""

    async def test_promote_open_pin_succeeds(self, pin_service, test_session):
        """open 상태의 Pin도 승격 가능 (현재 정책: 허용)"""
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Important decision made during discussion",
            importance=5,
            user_id="test-user",
        )
        # open 상태에서 바로 승격
        result = await pin_service.promote_to_memory(pin.id)

        assert result["memory_id"] is not None
        assert result["already_promoted"] is False

    async def test_promote_completed_pin_succeeds(self, pin_service, test_session):
        """completed 상태의 Pin 승격 — 표준 워크플로우"""
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Completed and ready for promotion task",
            importance=4,
            user_id="test-user",
        )
        await pin_service.complete_pin(pin.id)

        result = await pin_service.promote_to_memory(pin.id)

        assert result["memory_id"] is not None
        assert result["already_promoted"] is False

    async def test_promote_preserves_category(self, pin_service, test_session):
        """승격 시 지정한 category가 Memory에 반영되는지 검증"""
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Critical bug found in authentication flow",
            importance=5,
            user_id="test-user",
        )
        await pin_service.complete_pin(pin.id)

        result = await pin_service.promote_to_memory(pin.id, category="bug")

        assert result["memory_id"] is not None

        # Memory를 직접 조회하여 category 확인
        memory_row = await pin_service.db.fetchone(
            "SELECT category FROM memories WHERE id = ?",
            (result["memory_id"],),
        )
        assert memory_row is not None
        assert memory_row["category"] == "bug"


# ========== 3. Cross-session pin 연속성 (2 tests) ==========


class TestCrossSessionContinuity:
    """세션 간 Pin 연속성 테스트"""

    async def test_ended_session_pins_not_in_new_resume(
        self, session_service, pin_service, db
    ):
        """종료된 세션의 Pin은 새 세션 resume에 포함되지 않음"""
        # 첫 세션 생성 및 Pin 추가
        session1 = await session_service.get_or_create_active_session(
            project_id="test-project", user_id="test-user"
        )
        await pin_service.create_pin(
            project_id="test-project",
            content="Task from session one with enough content",
            importance=3,
            user_id="test-user",
        )

        # 첫 세션 종료
        await session_service.end_session(session1.id, summary="Session 1 done")

        # 새 세션 생성 및 Pin 추가
        session2 = await session_service.get_or_create_active_session(
            project_id="test-project", user_id="test-user"
        )
        await pin_service.create_pin(
            project_id="test-project",
            content="Task from session two with enough content",
            importance=3,
            user_id="test-user",
        )

        # resume 시 새 세션의 Pin만 보여야 함
        ctx = await session_service.resume_last_session(
            project_id="test-project", user_id="test-user", expand=True
        )

        assert ctx is not None
        assert ctx.session_id == session2.id
        assert ctx.pins_count == 1
        assert len(ctx.pins) == 1

    async def test_incomplete_pins_accessible_after_resume(
        self, session_service, pin_service, db
    ):
        """미완료 Pin이 세션 resume 후 접근 가능"""
        # 세션 생성 및 Pin 추가
        await session_service.get_or_create_active_session(
            project_id="test-project", user_id="test-user"
        )
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Incomplete work that should persist across resumes",
            importance=4,
            user_id="test-user",
        )

        # resume 호출 (세션 다시 로드)
        ctx = await session_service.resume_last_session(
            project_id="test-project", user_id="test-user", expand=True
        )

        assert ctx is not None
        assert ctx.open_pins >= 1
        # 핀 ID가 목록에 있는지 확인
        pin_ids = [p.id if isinstance(p, PinResponse) else p["id"] for p in ctx.pins]
        assert pin.id in pin_ids


# ========== 4. should_suggest 경계값 (4 tests) ==========


class TestShouldSuggestBoundary:
    """should_suggest_promotion() 경계값 테스트"""

    async def test_importance_3_no_suggest(self, pin_service, test_session):
        """importance=3 (경계 아래) → suggest=False"""
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Normal importance task content here",
            importance=3,
            user_id="test-user",
        )
        completed = await pin_service.complete_pin(pin.id)

        assert pin_service.should_suggest_promotion(completed) is False

    async def test_importance_4_suggest(self, pin_service, test_session):
        """importance=4 (경계값) → suggest=True"""
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="High importance task content here",
            importance=4,
            user_id="test-user",
        )
        completed = await pin_service.complete_pin(pin.id)

        assert pin_service.should_suggest_promotion(completed) is True

    async def test_importance_5_suggest(self, pin_service, test_session):
        """importance=5 (최대) → suggest=True"""
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Critical importance task content here",
            importance=5,
            user_id="test-user",
        )
        completed = await pin_service.complete_pin(pin.id)

        assert pin_service.should_suggest_promotion(completed) is True

    async def test_open_importance_4_no_suggest(self, pin_service, test_session):
        """importance=4이지만 open 상태 → suggest=False (완료 필요)"""
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="High importance but still open task",
            importance=4,
            user_id="test-user",
        )
        # complete하지 않고 open 상태에서 확인
        assert pin_service.should_suggest_promotion(pin) is False


# ========== 5. Concurrent complete race condition (1 test) ==========


class TestConcurrentComplete:
    """동시 complete_pin 호출 경쟁 조건 테스트"""

    async def test_concurrent_complete_one_succeeds_one_fails(
        self, pin_service, test_session
    ):
        """동일 Pin에 대해 동시 complete 호출 → 하나만 성공, 나머지는 PinAlreadyCompletedError"""
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Task to complete concurrently with race condition",
            importance=3,
            user_id="test-user",
        )

        # 두 개의 동시 complete 호출
        results = await asyncio.gather(
            pin_service.complete_pin(pin.id),
            pin_service.complete_pin(pin.id),
            return_exceptions=True,
        )

        # 하나는 성공(PinResponse), 하나는 PinAlreadyCompletedError
        successes = [r for r in results if isinstance(r, PinResponse)]
        errors = [r for r in results if isinstance(r, PinAlreadyCompletedError)]

        assert len(successes) == 1
        assert len(errors) == 1
        assert successes[0].status == "completed"
