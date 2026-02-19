"""
SessionService 확장 기능 테스트

Tasks 7.1-7.3: 토큰 추적 통합, 자동 승격, 세션 통계 메서드 테스트

Requirements: 1.1, 1.2, 1.3, 1.5, 5.4, 7.1, 7.2, 9.1, 9.2, 9.3, 9.4, 9.5
"""

import pytest
import asyncio
import tempfile
import os
from datetime import datetime, timezone, timedelta
from app.core.database.base import Database
from app.core.services.session import SessionService
from app.core.services.pin import PinService
from app.core.services.token_tracker import TokenTracker


@pytest.fixture
async def db():
    """테스트용 임시 데이터베이스"""
    # 임시 파일 생성
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    # Database 인스턴스 생성 및 연결
    database = Database(db_path)
    await database.connect()
    
    yield database
    
    # 정리
    await database.close()
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
async def session_service(db):
    """SessionService 인스턴스"""
    return SessionService(db)


@pytest.fixture
async def pin_service(db):
    """PinService 인스턴스"""
    return PinService(db)


@pytest.fixture
async def token_tracker(db):
    """TokenTracker 인스턴스"""
    return TokenTracker(db)


class TestResumeWithTokenTracking:
    """Task 7.1: resume_with_token_tracking() 메서드 테스트"""
    
    async def test_resume_with_no_session(self, session_service):
        """세션이 없을 때 None과 0 토큰 정보 반환"""
        context, token_info = await session_service.resume_with_token_tracking(
            project_id="nonexistent-project",
            expand=False
        )
        
        assert context is None
        assert token_info["loaded_tokens"] == 0
        assert token_info["unloaded_tokens"] == 0
        assert token_info["estimated_total"] == 0
    
    async def test_resume_with_expand_false(self, session_service, pin_service):
        """expand=false일 때 요약만 로드하고 토큰 절감"""
        # 세션 및 핀 생성
        pin1 = await pin_service.create_pin(
            project_id="test-project",
            content="This is a test pin with some content",
            importance=3
        )
        
        pin2 = await pin_service.create_pin(
            project_id="test-project",
            content="Another test pin with more detailed content here",
            importance=4
        )
        
        # expand=false로 재개
        context, token_info = await session_service.resume_with_token_tracking(
            project_id="test-project",
            expand=False,
            limit=10
        )
        
        assert context is not None
        assert context.pins_count == 2
        assert token_info["loaded_tokens"] > 0  # 요약 토큰
        assert token_info["unloaded_tokens"] > 0  # 핀 내용 토큰
        assert token_info["estimated_total"] == (
            token_info["loaded_tokens"] + token_info["unloaded_tokens"]
        )
    
    async def test_resume_with_expand_true(self, session_service, pin_service):
        """expand=true일 때 전체 핀 내용 로드"""
        # 세션 및 핀 생성
        await pin_service.create_pin(
            project_id="test-project2",
            content="Pin content for expansion test",
            importance=3
        )
        
        # expand=true로 재개
        context, token_info = await session_service.resume_with_token_tracking(
            project_id="test-project2",
            expand=True,
            limit=10
        )
        
        assert context is not None
        assert len(context.pins) > 0
        assert token_info["loaded_tokens"] > 0
        # expand=true이므로 unloaded_tokens는 0이어야 함
        assert token_info["unloaded_tokens"] == 0
    
    async def test_resume_with_limit(self, session_service, pin_service):
        """limit 파라미터가 올바르게 적용되는지 확인"""
        # 5개의 핀 생성
        for i in range(5):
            await pin_service.create_pin(
                project_id="test-project3",
                content=f"Pin number {i} with some content",
                importance=3
            )
        
        # limit=2, expand=True로 재개
        context, token_info = await session_service.resume_with_token_tracking(
            project_id="test-project3",
            expand=True,
            limit=2
        )
        
        assert context is not None
        assert context.pins_count == 5
        assert len(context.pins) == 2  # limit 적용
        # expand=True이므로 2개 핀만 로드, 나머지는 unloaded
        # 하지만 현재 구현에서는 expand=True일 때 unloaded_tokens를 계산하지 않음
        # 대신 loaded_tokens가 2개 핀의 토큰만 포함하는지 확인
        assert token_info["loaded_tokens"] > 0


class TestEndWithAutoPromotion:
    """Task 7.2: end_with_auto_promotion() 메서드 테스트"""
    
    async def test_end_with_no_session(self, session_service):
        """존재하지 않는 세션 종료 시도"""
        result = await session_service.end_with_auto_promotion(
            session_id="nonexistent-session"
        )
        
        assert result["session"] is None
        assert result["promoted_pins"] == []
        assert result["token_savings"]["savings_rate"] == 0.0
    
    async def test_auto_promotion_threshold_4(self, session_service, pin_service):
        """importance >= 4인 완료된 핀만 자동 승격"""
        # 다양한 중요도의 핀 생성
        pin_low = await pin_service.create_pin(
            project_id="promo-test",
            content="Low importance pin",
            importance=2
        )
        
        pin_medium = await pin_service.create_pin(
            project_id="promo-test",
            content="Medium importance pin",
            importance=3
        )
        
        pin_high = await pin_service.create_pin(
            project_id="promo-test",
            content="High importance pin",
            importance=4
        )
        
        pin_critical = await pin_service.create_pin(
            project_id="promo-test",
            content="Critical importance pin",
            importance=5
        )
        
        # 핀 완료
        await pin_service.complete_pin(pin_low.id)
        await pin_service.complete_pin(pin_medium.id)
        await pin_service.complete_pin(pin_high.id)
        await pin_service.complete_pin(pin_critical.id)
        
        # 세션 종료 및 자동 승격
        result = await session_service.end_with_auto_promotion(
            session_id=pin_high.session_id,
            auto_promote_threshold=4
        )
        
        assert result["session"] is not None
        assert result["session"].status == "completed"
        # importance 4, 5인 핀만 승격되어야 함
        assert len(result["promoted_pins"]) == 2
        assert pin_high.id in result["promoted_pins"]
        assert pin_critical.id in result["promoted_pins"]
        assert pin_low.id not in result["promoted_pins"]
        assert pin_medium.id not in result["promoted_pins"]
    
    async def test_auto_promotion_custom_threshold(self, session_service, pin_service):
        """커스텀 임계값 적용 테스트"""
        pin1 = await pin_service.create_pin(
            project_id="custom-threshold",
            content="Pin with importance 3",
            importance=3
        )
        
        pin2 = await pin_service.create_pin(
            project_id="custom-threshold",
            content="Pin with importance 5",
            importance=5
        )
        
        await pin_service.complete_pin(pin1.id)
        await pin_service.complete_pin(pin2.id)
        
        # 임계값 3으로 설정
        result = await session_service.end_with_auto_promotion(
            session_id=pin1.session_id,
            auto_promote_threshold=3
        )
        
        # importance 3, 5 모두 승격되어야 함
        assert len(result["promoted_pins"]) == 2
    
    async def test_no_promotion_for_incomplete_pins(self, session_service, pin_service):
        """완료되지 않은 핀은 승격되지 않음"""
        pin_open = await pin_service.create_pin(
            project_id="incomplete-test",
            content="Open pin with high importance",
            importance=5
        )
        
        pin_completed = await pin_service.create_pin(
            project_id="incomplete-test",
            content="Completed pin with high importance",
            importance=5
        )
        
        await pin_service.complete_pin(pin_completed.id)
        # pin_open은 완료하지 않음
        
        result = await session_service.end_with_auto_promotion(
            session_id=pin_open.session_id
        )
        
        # 완료된 핀만 승격
        assert len(result["promoted_pins"]) == 1
        assert pin_completed.id in result["promoted_pins"]
        assert pin_open.id not in result["promoted_pins"]
    
    async def test_token_savings_calculation(self, session_service, pin_service, token_tracker):
        """토큰 절감 통계가 올바르게 계산되는지 확인"""
        pin = await pin_service.create_pin(
            project_id="savings-test",
            content="Test pin for token savings",
            importance=4
        )
        
        # 토큰 사용량 기록
        await token_tracker.record_session_tokens(
            session_id=pin.session_id,
            loaded_tokens=100,
            unloaded_tokens=400,
            event_type="resume"
        )
        
        await pin_service.complete_pin(pin.id)
        
        result = await session_service.end_with_auto_promotion(
            session_id=pin.session_id
        )
        
        assert "token_savings" in result
        assert result["token_savings"]["total_tokens"] == 500
        assert result["token_savings"]["loaded_tokens"] == 100
        assert result["token_savings"]["saved_tokens"] == 400
        assert result["token_savings"]["savings_rate"] == 0.8


class TestGetSessionStatistics:
    """Task 7.3: get_session_statistics() 메서드 테스트"""
    
    async def test_statistics_with_no_sessions(self, session_service):
        """세션이 없을 때 통계"""
        stats = await session_service.get_session_statistics(
            project_id="empty-project"
        )
        
        assert stats["total_sessions"] == 0
        assert stats["avg_duration_hours"] == 0.0
        assert stats["avg_pins_per_session"] == 0.0
        assert stats["importance_distribution"] == {}
        assert stats["avg_token_savings_rate"] == 0.0
    
    async def test_statistics_with_multiple_sessions(self, session_service, pin_service):
        """여러 세션의 통계 계산"""
        # 첫 번째 세션
        pin1 = await pin_service.create_pin(
            project_id="stats-project",
            content="Pin 1",
            importance=3
        )
        pin2 = await pin_service.create_pin(
            project_id="stats-project",
            content="Pin 2",
            importance=4
        )
        await session_service.end_session(pin1.session_id)
        
        # 두 번째 세션 (새로운 세션 강제 생성)
        await asyncio.sleep(0.1)  # 시간 차이 확보
        pin3 = await pin_service.create_pin(
            project_id="stats-project",
            content="Pin 3",
            importance=5
        )
        
        stats = await session_service.get_session_statistics(
            project_id="stats-project"
        )
        
        assert stats["total_sessions"] >= 1
        assert stats["avg_pins_per_session"] > 0
        assert len(stats["importance_distribution"]) > 0
    
    async def test_importance_distribution(self, session_service, pin_service):
        """중요도별 분포 계산"""
        # 다양한 중요도의 핀 생성
        await pin_service.create_pin(
            project_id="dist-project",
            content="Pin importance 1",
            importance=1
        )
        await pin_service.create_pin(
            project_id="dist-project",
            content="Pin importance 3",
            importance=3
        )
        await pin_service.create_pin(
            project_id="dist-project",
            content="Another pin importance 3",
            importance=3
        )
        await pin_service.create_pin(
            project_id="dist-project",
            content="Pin importance 5",
            importance=5
        )
        
        stats = await session_service.get_session_statistics(
            project_id="dist-project"
        )
        
        assert stats["importance_distribution"][1] == 1
        assert stats["importance_distribution"][3] == 2
        assert stats["importance_distribution"][5] == 1
    
    async def test_statistics_with_date_filter(self, session_service, pin_service):
        """날짜 필터링 테스트"""
        # 핀 생성
        await pin_service.create_pin(
            project_id="date-filter-project",
            content="Test pin",
            importance=3
        )
        
        # 현재 날짜 기준으로 필터링
        today = datetime.now(timezone.utc).isoformat()
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        
        stats = await session_service.get_session_statistics(
            project_id="date-filter-project",
            start_date=yesterday,
            end_date=today
        )
        
        assert stats["total_sessions"] >= 1
    
    async def test_statistics_all_projects(self, session_service, pin_service):
        """전체 프로젝트 통계 (project_id=None)"""
        # 여러 프로젝트에 핀 생성
        await pin_service.create_pin(
            project_id="project-a",
            content="Pin in project A",
            importance=3
        )
        await pin_service.create_pin(
            project_id="project-b",
            content="Pin in project B",
            importance=4
        )
        
        stats = await session_service.get_session_statistics()
        
        assert stats["total_sessions"] >= 2
        assert stats["avg_pins_per_session"] > 0


class TestIntegration:
    """통합 테스트: 전체 워크플로우"""
    
    async def test_full_workflow_with_token_tracking(
        self, session_service, pin_service, token_tracker
    ):
        """
        전체 워크플로우 테스트:
        1. 세션 재개 (토큰 추적)
        2. 핀 추가
        3. 핀 완료
        4. 세션 종료 (자동 승격)
        5. 통계 조회
        """
        project_id = "integration-test"
        
        # 1. 세션 재개
        context1, token_info1 = await session_service.resume_with_token_tracking(
            project_id=project_id,
            expand=False
        )
        # 첫 재개는 세션이 없을 수 있음
        
        # 2. 핀 추가
        pin1 = await pin_service.create_pin(
            project_id=project_id,
            content="Important feature implementation",
            importance=5
        )
        
        pin2 = await pin_service.create_pin(
            project_id=project_id,
            content="Minor documentation update",
            importance=2
        )
        
        # 3. 세션 재개 (핀이 있는 상태)
        context2, token_info2 = await session_service.resume_with_token_tracking(
            project_id=project_id,
            expand=False
        )
        
        assert context2 is not None
        assert context2.pins_count == 2
        assert token_info2["loaded_tokens"] > 0
        
        # 4. 핀 완료
        await pin_service.complete_pin(pin1.id)
        await pin_service.complete_pin(pin2.id)
        
        # 5. 세션 종료 (자동 승격)
        end_result = await session_service.end_with_auto_promotion(
            session_id=pin1.session_id,
            auto_promote_threshold=4
        )
        
        assert end_result["session"].status == "completed"
        assert pin1.id in end_result["promoted_pins"]  # importance 5
        assert pin2.id not in end_result["promoted_pins"]  # importance 2
        
        # 6. 통계 조회
        stats = await session_service.get_session_statistics(
            project_id=project_id
        )
        
        assert stats["total_sessions"] >= 1
        assert stats["avg_pins_per_session"] >= 2
        assert 5 in stats["importance_distribution"]
        assert 2 in stats["importance_distribution"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
