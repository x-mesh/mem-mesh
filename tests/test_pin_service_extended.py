"""PinService 확장 기능 테스트 (Task 6.1-6.3)"""

import os
import tempfile

import pytest

from app.core.database.base import Database
from app.core.errors import PinNotFoundError
from app.core.services.pin import PinService
from app.core.services.session import SessionService


@pytest.fixture
async def db():
    """테스트용 임시 데이터베이스 생성"""
    # 임시 파일 생성
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Database 인스턴스 생성 및 연결
    database = Database(db_path)
    await database.connect()

    yield database

    # 정리
    await database.close()
    for ext in ["", "-wal", "-shm"]:
        p = db_path + ext
        if os.path.exists(p):
            os.unlink(p)


@pytest.fixture
async def pin_service(db, mock_embedding_service):
    """PinService 인스턴스 (mock embedding으로 promote 시 모델 로드 방지)"""
    return PinService(db, embedding_service=mock_embedding_service)


@pytest.fixture
async def session_service(db):
    """SessionService 인스턴스"""
    return SessionService(db)


@pytest.fixture
async def test_session(session_service):
    """테스트용 세션 생성"""
    session = await session_service.get_or_create_active_session(
        project_id="test-project", user_id="test-user"
    )
    return session


class TestGetPinsFiltered:
    """get_pins_filtered() 메서드 테스트"""

    async def test_filter_by_min_importance(self, pin_service, test_session):
        """최소 중요도 필터링 테스트"""
        # 다양한 중요도의 핀 생성 (user_id를 명시하여 같은 세션 사용)
        await pin_service.create_pin(
            project_id="test-project",
            content="Low importance task",
            importance=2,
            user_id="test-user",
        )
        await pin_service.create_pin(
            project_id="test-project",
            content="High importance task",
            importance=4,
            user_id="test-user",
        )
        await pin_service.create_pin(
            project_id="test-project",
            content="Critical task",
            importance=5,
            user_id="test-user",
        )

        # importance >= 4 필터링
        filtered = await pin_service.get_pins_filtered(
            session_id=test_session.id, min_importance=4
        )

        assert len(filtered) == 2
        assert all(pin.importance >= 4 for pin in filtered)

    async def test_filter_by_status(self, pin_service, test_session):
        """상태 필터링 테스트"""
        # 다양한 상태의 핀 생성
        await pin_service.create_pin(
            project_id="test-project",
            content="Open task",
            importance=3,
            user_id="test-user",
        )
        pin2 = await pin_service.create_pin(
            project_id="test-project",
            content="Task to complete",
            importance=3,
            user_id="test-user",
        )
        await pin_service.complete_pin(pin2.id)

        # completed 상태만 필터링
        filtered = await pin_service.get_pins_filtered(
            session_id=test_session.id, status="completed"
        )

        assert len(filtered) == 1
        assert filtered[0].status == "completed"

    async def test_filter_by_tags(self, pin_service, test_session):
        """태그 필터링 테스트"""
        # 다양한 태그의 핀 생성
        await pin_service.create_pin(
            project_id="test-project",
            content="Backend task",
            importance=3,
            tags=["backend", "api"],
            user_id="test-user",
        )
        await pin_service.create_pin(
            project_id="test-project",
            content="Frontend task",
            importance=3,
            tags=["frontend", "ui"],
            user_id="test-user",
        )
        await pin_service.create_pin(
            project_id="test-project",
            content="Full stack task",
            importance=3,
            tags=["backend", "frontend"],
            user_id="test-user",
        )

        # backend 태그 필터링
        filtered = await pin_service.get_pins_filtered(
            session_id=test_session.id, tags=["backend"]
        )

        assert len(filtered) == 2
        assert all("backend" in pin.tags for pin in filtered)

    async def test_filter_multiple_conditions(self, pin_service, test_session):
        """여러 필터 조건 동시 적용 (AND 조건) 테스트"""
        # 다양한 핀 생성
        pin1 = await pin_service.create_pin(
            project_id="test-project",
            content="High priority backend task",
            importance=4,
            tags=["backend"],
            user_id="test-user",
        )
        await pin_service.complete_pin(pin1.id)

        await pin_service.create_pin(
            project_id="test-project",
            content="Low priority backend task",
            importance=2,
            tags=["backend"],
            user_id="test-user",
        )

        pin3 = await pin_service.create_pin(
            project_id="test-project",
            content="High priority frontend task",
            importance=4,
            tags=["frontend"],
            user_id="test-user",
        )
        await pin_service.complete_pin(pin3.id)

        # importance >= 4 AND status = completed AND tags = backend
        filtered = await pin_service.get_pins_filtered(
            session_id=test_session.id,
            min_importance=4,
            status="completed",
            tags=["backend"],
        )

        assert len(filtered) == 1
        assert filtered[0].importance >= 4
        assert filtered[0].status == "completed"
        assert "backend" in filtered[0].tags

    async def test_filter_results_sorted_by_created_at(self, pin_service, test_session):
        """결과가 created_at 기준 내림차순으로 정렬되는지 테스트"""
        # 여러 핀 생성
        pins = []
        for i in range(5):
            pin = await pin_service.create_pin(
                project_id="test-project",
                content=f"Task {i}",
                importance=3,
                user_id="test-user",
            )
            pins.append(pin)

        # 필터링 (모든 핀)
        filtered = await pin_service.get_pins_filtered(
            session_id=test_session.id, limit=10
        )

        # 최신 핀이 먼저 나와야 함
        assert len(filtered) == 5
        for i in range(len(filtered) - 1):
            assert filtered[i].created_at >= filtered[i + 1].created_at

    async def test_filter_limit(self, pin_service, test_session):
        """limit 파라미터 테스트"""
        # 10개 핀 생성
        for i in range(10):
            await pin_service.create_pin(
                project_id="test-project",
                content=f"Task {i}",
                importance=3,
                user_id="test-user",
            )

        # limit=5로 조회
        filtered = await pin_service.get_pins_filtered(
            session_id=test_session.id, limit=5
        )

        assert len(filtered) == 5


class TestGetPinStatistics:
    """get_pin_statistics() 메서드 테스트"""

    async def test_statistics_basic(self, pin_service, test_session):
        """기본 통계 계산 테스트"""
        # 다양한 핀 생성
        await pin_service.create_pin(
            project_id="test-project",
            content="Task 1",
            importance=1,
            user_id="test-user",
        )
        await pin_service.create_pin(
            project_id="test-project",
            content="Task 2",
            importance=3,
            user_id="test-user",
        )
        pin3 = await pin_service.create_pin(
            project_id="test-project",
            content="Task 3",
            importance=5,
            user_id="test-user",
        )
        await pin_service.complete_pin(pin3.id)

        # 통계 조회
        stats = await pin_service.get_pin_statistics(test_session.id)

        assert stats["total"] == 3
        assert stats["by_status"]["in_progress"] == 2
        assert stats["by_status"]["completed"] == 1
        assert stats["by_importance"][1] == 1
        assert stats["by_importance"][3] == 1
        assert stats["by_importance"][5] == 1

    async def test_statistics_promotion_candidates(self, pin_service, test_session):
        """승격 후보 집계 테스트"""
        # importance >= 4인 완료된 핀 생성
        pin1 = await pin_service.create_pin(
            project_id="test-project",
            content="High priority task",
            importance=4,
            user_id="test-user",
        )
        await pin_service.complete_pin(pin1.id)

        pin2 = await pin_service.create_pin(
            project_id="test-project",
            content="Critical task",
            importance=5,
            user_id="test-user",
        )
        await pin_service.complete_pin(pin2.id)

        # importance < 4인 완료된 핀
        pin3 = await pin_service.create_pin(
            project_id="test-project",
            content="Normal task",
            importance=3,
            user_id="test-user",
        )
        await pin_service.complete_pin(pin3.id)

        # 통계 조회
        stats = await pin_service.get_pin_statistics(test_session.id)

        assert stats["promotion_candidates"] == 2

    async def test_statistics_avg_lead_time(self, pin_service, test_session):
        """평균 lead_time 계산 테스트"""
        # 핀 생성 및 완료
        pin1 = await pin_service.create_pin(
            project_id="test-project",
            content="Task 1",
            importance=3,
            user_id="test-user",
        )
        await pin_service.complete_pin(pin1.id)

        pin2 = await pin_service.create_pin(
            project_id="test-project",
            content="Task 2",
            importance=3,
            user_id="test-user",
        )
        await pin_service.complete_pin(pin2.id)

        # 통계 조회
        stats = await pin_service.get_pin_statistics(test_session.id)

        # lead_time이 계산되어야 함 (매우 짧은 시간이지만 0 이상)
        assert stats["avg_lead_time_hours"] is not None
        assert stats["avg_lead_time_hours"] >= 0

    async def test_statistics_empty_session(self, pin_service, test_session):
        """빈 세션의 통계 테스트"""
        stats = await pin_service.get_pin_statistics(test_session.id)

        assert stats["total"] == 0
        assert stats["by_status"]["open"] == 0
        assert stats["by_status"]["completed"] == 0
        assert stats["promotion_candidates"] == 0
        assert stats["avg_lead_time_hours"] is None


class TestPromoteToMemoryDuplicatePrevention:
    """promote_to_memory() 중복 승격 방지 테스트"""

    async def test_promote_once(self, pin_service, test_session):
        """첫 승격 테스트"""
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Important task to promote — critical architectural decision about database migration strategy that needs permanent memory preservation",
            importance=5,
            user_id="test-user",
        )
        await pin_service.complete_pin(pin.id)

        # 첫 승격
        result = await pin_service.promote_to_memory(pin.id)

        assert result["memory_id"] is not None
        assert result["already_promoted"] is False
        assert "승격되었습니다" in result["message"]

    async def test_prevent_duplicate_promotion(self, pin_service, test_session):
        """중복 승격 방지 테스트"""
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Important task to promote — critical architectural decision about database migration strategy that needs permanent memory preservation",
            importance=5,
            user_id="test-user",
        )
        await pin_service.complete_pin(pin.id)

        # 첫 승격
        result1 = await pin_service.promote_to_memory(pin.id)
        memory_id = result1["memory_id"]

        # 두 번째 승격 시도
        result2 = await pin_service.promote_to_memory(pin.id)

        # 동일한 memory_id 반환
        assert result2["memory_id"] == memory_id
        assert result2["already_promoted"] is True
        assert "이미" in result2["message"]

    async def test_promoted_pin_has_memory_id(self, pin_service, test_session):
        """승격된 핀이 promoted_to_memory_id를 가지는지 테스트"""
        pin = await pin_service.create_pin(
            project_id="test-project",
            content="Important task — redesigning the authentication flow to support multi-factor authentication with TOTP and backup codes for enhanced security",
            importance=5,
            user_id="test-user",
        )
        await pin_service.complete_pin(pin.id)

        # 승격
        result = await pin_service.promote_to_memory(pin.id)

        # 핀 다시 조회
        updated_pin = await pin_service.get_pin(pin.id)

        assert updated_pin.promoted_to_memory_id == result["memory_id"]

    async def test_promote_nonexistent_pin(self, pin_service):
        """존재하지 않는 핀 승격 시도 테스트"""
        with pytest.raises(PinNotFoundError):
            await pin_service.promote_to_memory("nonexistent-pin-id")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
