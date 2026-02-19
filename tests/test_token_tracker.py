"""
TokenTracker 단위 테스트

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

import pytest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.services.token_tracker import TokenTracker
from app.core.database.base import Database


@pytest.fixture
async def mock_db():
    """Mock Database 인스턴스"""
    db = MagicMock(spec=Database)
    db.execute = AsyncMock()
    db.fetchone = AsyncMock()
    db.fetchall = AsyncMock()
    return db


@pytest.fixture
def token_tracker(mock_db):
    """TokenTracker 인스턴스"""
    return TokenTracker(mock_db, default_threshold=10000)


class TestTokenTrackerInitialization:
    """TokenTracker 초기화 테스트"""
    
    def test_initialization_default(self, mock_db):
        """기본 설정으로 초기화"""
        tracker = TokenTracker(mock_db)
        
        assert tracker.db == mock_db
        assert tracker.default_threshold == 10000
        assert tracker.token_estimator is not None
    
    def test_initialization_custom_threshold(self, mock_db):
        """커스텀 임계값으로 초기화"""
        tracker = TokenTracker(mock_db, default_threshold=5000)
        
        assert tracker.default_threshold == 5000


class TestEstimateTokens:
    """estimate_tokens 메서드 테스트
    
    Requirements: 7.1, 7.2
    """
    
    @pytest.mark.asyncio
    async def test_estimate_tokens_simple_text(self, token_tracker):
        """간단한 텍스트 토큰 추정"""
        text = "Hello, world!"
        
        token_count = await token_tracker.estimate_tokens(text)
        
        assert token_count > 0
        assert isinstance(token_count, int)
    
    @pytest.mark.asyncio
    async def test_estimate_tokens_empty_string(self, token_tracker):
        """빈 문자열 토큰 추정"""
        token_count = await token_tracker.estimate_tokens("")
        
        assert token_count == 0
    
    @pytest.mark.asyncio
    async def test_estimate_tokens_with_model(self, token_tracker):
        """특정 모델로 토큰 추정"""
        text = "Test text"
        
        token_count = await token_tracker.estimate_tokens(text, model="gpt-3.5-turbo")
        
        assert token_count > 0
    
    @pytest.mark.asyncio
    async def test_estimate_tokens_fallback_on_error(self, token_tracker):
        """에러 발생 시 폴백 동작"""
        # TokenEstimator의 estimate_tokens가 에러를 발생시키도록 설정
        with patch.object(token_tracker.token_estimator, 'estimate_tokens', side_effect=Exception("Test error")):
            text = "Test text with error"
            
            token_count = await token_tracker.estimate_tokens(text)
            
            # 폴백: len(text) // 4
            expected = max(1, len(text) // 4)
            assert token_count == expected


class TestRecordSessionTokens:
    """record_session_tokens 메서드 테스트
    
    Requirements: 7.1, 7.2, 7.4
    """
    
    @pytest.mark.asyncio
    async def test_record_session_tokens_basic(self, token_tracker, mock_db):
        """기본 토큰 기록"""
        session_id = str(uuid.uuid4())
        loaded_tokens = 100
        unloaded_tokens = 50
        
        await token_tracker.record_session_tokens(
            session_id=session_id,
            loaded_tokens=loaded_tokens,
            unloaded_tokens=unloaded_tokens
        )
        
        # session_stats 테이블에 INSERT 호출 확인
        assert mock_db.execute.call_count == 2
        
        # 첫 번째 호출: session_stats INSERT
        first_call = mock_db.execute.call_args_list[0]
        assert "INSERT INTO session_stats" in first_call[0][0]
        
        # 두 번째 호출: sessions UPDATE
        second_call = mock_db.execute.call_args_list[1]
        assert "UPDATE sessions" in second_call[0][0]
    
    @pytest.mark.asyncio
    async def test_record_session_tokens_with_event_type(self, token_tracker, mock_db):
        """이벤트 타입과 함께 토큰 기록"""
        session_id = str(uuid.uuid4())
        
        await token_tracker.record_session_tokens(
            session_id=session_id,
            loaded_tokens=200,
            unloaded_tokens=100,
            event_type="search"
        )
        
        # event_type이 파라미터에 포함되어야 함
        first_call = mock_db.execute.call_args_list[0]
        assert "search" in str(first_call[0][1])
    
    @pytest.mark.asyncio
    async def test_record_session_tokens_with_context_depth(self, token_tracker, mock_db):
        """맥락 깊이와 함께 토큰 기록"""
        session_id = str(uuid.uuid4())
        
        await token_tracker.record_session_tokens(
            session_id=session_id,
            loaded_tokens=150,
            unloaded_tokens=75,
            context_depth=3
        )
        
        # context_depth가 파라미터에 포함되어야 함
        first_call = mock_db.execute.call_args_list[0]
        assert 3 in first_call[0][1]
    
    @pytest.mark.asyncio
    async def test_record_session_tokens_error_handling(self, token_tracker, mock_db):
        """에러 발생 시 예외 전파"""
        mock_db.execute.side_effect = Exception("Database error")
        
        session_id = str(uuid.uuid4())
        
        with pytest.raises(Exception, match="Database error"):
            await token_tracker.record_session_tokens(
                session_id=session_id,
                loaded_tokens=100,
                unloaded_tokens=50
            )


class TestCalculateSavings:
    """calculate_savings 메서드 테스트
    
    Requirements: 7.3, 7.4
    """
    
    @pytest.mark.asyncio
    async def test_calculate_savings_basic(self, token_tracker, mock_db):
        """기본 절감률 계산"""
        session_id = str(uuid.uuid4())
        
        # Mock 데이터 설정
        mock_db.fetchone.return_value = {
            "initial_context_tokens": 100,
            "total_loaded_tokens": 300,
            "total_saved_tokens": 700
        }
        
        result = await token_tracker.calculate_savings(session_id)
        
        assert result["total_tokens"] == 1000  # 300 + 700
        assert result["loaded_tokens"] == 300
        assert result["saved_tokens"] == 700
        assert result["savings_rate"] == 0.7  # 700 / 1000
    
    @pytest.mark.asyncio
    async def test_calculate_savings_no_savings(self, token_tracker, mock_db):
        """절감이 없는 경우"""
        session_id = str(uuid.uuid4())
        
        mock_db.fetchone.return_value = {
            "initial_context_tokens": 100,
            "total_loaded_tokens": 500,
            "total_saved_tokens": 0
        }
        
        result = await token_tracker.calculate_savings(session_id)
        
        assert result["total_tokens"] == 500
        assert result["loaded_tokens"] == 500
        assert result["saved_tokens"] == 0
        assert result["savings_rate"] == 0.0
    
    @pytest.mark.asyncio
    async def test_calculate_savings_session_not_found(self, token_tracker, mock_db):
        """세션이 없는 경우"""
        session_id = str(uuid.uuid4())
        
        mock_db.fetchone.return_value = None
        
        result = await token_tracker.calculate_savings(session_id)
        
        assert result["total_tokens"] == 0
        assert result["loaded_tokens"] == 0
        assert result["saved_tokens"] == 0
        assert result["savings_rate"] == 0.0
    
    @pytest.mark.asyncio
    async def test_calculate_savings_null_values(self, token_tracker, mock_db):
        """NULL 값 처리"""
        session_id = str(uuid.uuid4())
        
        mock_db.fetchone.return_value = {
            "initial_context_tokens": None,
            "total_loaded_tokens": None,
            "total_saved_tokens": None
        }
        
        result = await token_tracker.calculate_savings(session_id)
        
        assert result["total_tokens"] == 0
        assert result["loaded_tokens"] == 0
        assert result["saved_tokens"] == 0
        assert result["savings_rate"] == 0.0
    
    @pytest.mark.asyncio
    async def test_calculate_savings_high_rate(self, token_tracker, mock_db):
        """높은 절감률 (95%)"""
        session_id = str(uuid.uuid4())
        
        mock_db.fetchone.return_value = {
            "initial_context_tokens": 100,
            "total_loaded_tokens": 50,
            "total_saved_tokens": 950
        }
        
        result = await token_tracker.calculate_savings(session_id)
        
        assert result["total_tokens"] == 1000
        assert result["savings_rate"] == 0.95


class TestCheckThreshold:
    """check_threshold 메서드 테스트
    
    Requirements: 7.5
    """
    
    @pytest.mark.asyncio
    async def test_check_threshold_not_exceeded(self, token_tracker, mock_db):
        """임계값 미초과"""
        session_id = str(uuid.uuid4())
        
        mock_db.fetchone.return_value = {
            "total_loaded_tokens": 5000
        }
        
        exceeded = await token_tracker.check_threshold(session_id)
        
        assert exceeded is False
    
    @pytest.mark.asyncio
    async def test_check_threshold_exceeded(self, token_tracker, mock_db):
        """임계값 초과"""
        session_id = str(uuid.uuid4())
        
        mock_db.fetchone.return_value = {
            "total_loaded_tokens": 15000
        }
        
        exceeded = await token_tracker.check_threshold(session_id)
        
        assert exceeded is True
    
    @pytest.mark.asyncio
    async def test_check_threshold_exactly_at_threshold(self, token_tracker, mock_db):
        """임계값과 정확히 같은 경우"""
        session_id = str(uuid.uuid4())
        
        mock_db.fetchone.return_value = {
            "total_loaded_tokens": 10000
        }
        
        exceeded = await token_tracker.check_threshold(session_id)
        
        # 10000 > 10000은 False
        assert exceeded is False
    
    @pytest.mark.asyncio
    async def test_check_threshold_custom_threshold(self, token_tracker, mock_db):
        """커스텀 임계값 사용"""
        session_id = str(uuid.uuid4())
        
        mock_db.fetchone.return_value = {
            "total_loaded_tokens": 6000
        }
        
        exceeded = await token_tracker.check_threshold(session_id, threshold=5000)
        
        assert exceeded is True
    
    @pytest.mark.asyncio
    async def test_check_threshold_session_not_found(self, token_tracker, mock_db):
        """세션이 없는 경우"""
        session_id = str(uuid.uuid4())
        
        mock_db.fetchone.return_value = None
        
        exceeded = await token_tracker.check_threshold(session_id)
        
        assert exceeded is False
    
    @pytest.mark.asyncio
    async def test_check_threshold_null_tokens(self, token_tracker, mock_db):
        """토큰 수가 NULL인 경우"""
        session_id = str(uuid.uuid4())
        
        mock_db.fetchone.return_value = {
            "total_loaded_tokens": None
        }
        
        exceeded = await token_tracker.check_threshold(session_id)
        
        # None은 0으로 처리되므로 초과하지 않음
        assert exceeded is False


class TestRecordTokenUsage:
    """record_token_usage 메서드 테스트"""
    
    @pytest.mark.asyncio
    async def test_record_token_usage_basic(self, token_tracker, mock_db):
        """기본 토큰 사용량 기록"""
        project_id = "test-project"
        operation_type = "search"
        tokens_used = 100
        
        record_id = await token_tracker.record_token_usage(
            project_id=project_id,
            operation_type=operation_type,
            tokens_used=tokens_used
        )
        
        assert record_id is not None
        assert isinstance(record_id, str)
        
        # INSERT 호출 확인
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0]
        assert "INSERT INTO token_usage" in call_args[0]
    
    @pytest.mark.asyncio
    async def test_record_token_usage_with_session(self, token_tracker, mock_db):
        """세션 ID와 함께 기록"""
        session_id = str(uuid.uuid4())
        
        record_id = await token_tracker.record_token_usage(
            project_id="test-project",
            operation_type="session_resume",
            tokens_used=50,
            session_id=session_id
        )
        
        assert record_id is not None
        
        # session_id가 파라미터에 포함되어야 함
        call_args = mock_db.execute.call_args[0]
        assert session_id in call_args[1]
    
    @pytest.mark.asyncio
    async def test_record_token_usage_with_optimization(self, token_tracker, mock_db):
        """최적화 적용과 함께 기록"""
        record_id = await token_tracker.record_token_usage(
            project_id="test-project",
            operation_type="context_load",
            tokens_used=100,
            tokens_saved=50,
            optimization_applied=True
        )
        
        assert record_id is not None
        
        # optimization_applied가 1로 변환되어야 함
        call_args = mock_db.execute.call_args[0]
        assert 1 in call_args[1]  # True -> 1


class TestGetProjectTokenStatistics:
    """get_project_token_statistics 메서드 테스트"""
    
    @pytest.mark.asyncio
    async def test_get_project_statistics_basic(self, token_tracker, mock_db):
        """기본 프로젝트 통계 조회"""
        project_id = "test-project"
        
        # Mock 데이터 설정
        mock_db.fetchall.return_value = [
            {
                "total_used": 1000,
                "total_saved": 500,
                "operation_type": "search",
                "count": 10
            },
            {
                "total_used": 500,
                "total_saved": 250,
                "operation_type": "session_resume",
                "count": 5
            }
        ]
        
        result = await token_tracker.get_project_token_statistics(project_id)
        
        assert result["total_tokens_used"] == 1500  # 1000 + 500
        assert result["total_tokens_saved"] == 750  # 500 + 250
        assert result["avg_savings_rate"] == 0.3333  # 750 / 2250
        assert "search" in result["operation_breakdown"]
        assert result["operation_breakdown"]["search"] == 1000
    
    @pytest.mark.asyncio
    async def test_get_project_statistics_with_date_range(self, token_tracker, mock_db):
        """날짜 범위와 함께 통계 조회"""
        project_id = "test-project"
        start_date = "2026-01-01"
        end_date = "2026-01-31"
        
        mock_db.fetchall.return_value = []
        
        result = await token_tracker.get_project_token_statistics(
            project_id=project_id,
            start_date=start_date,
            end_date=end_date
        )
        
        # 날짜 필터가 쿼리에 포함되어야 함
        call_args = mock_db.fetchall.call_args[0]
        assert "created_at >=" in call_args[0]
        assert "created_at <=" in call_args[0]
        assert start_date in call_args[1]
        assert end_date in call_args[1]
    
    @pytest.mark.asyncio
    async def test_get_project_statistics_no_data(self, token_tracker, mock_db):
        """데이터가 없는 경우"""
        project_id = "empty-project"
        
        mock_db.fetchall.return_value = []
        
        result = await token_tracker.get_project_token_statistics(project_id)
        
        assert result["total_tokens_used"] == 0
        assert result["total_tokens_saved"] == 0
        assert result["avg_savings_rate"] == 0.0
        assert result["operation_breakdown"] == {}


class TestTokenTrackerIntegration:
    """TokenTracker 통합 시나리오 테스트"""
    
    @pytest.mark.asyncio
    async def test_full_session_tracking_workflow(self, token_tracker, mock_db):
        """전체 세션 추적 워크플로우"""
        session_id = str(uuid.uuid4())
        project_id = "test-project"
        
        # 1. 세션 시작 - 토큰 기록
        await token_tracker.record_session_tokens(
            session_id=session_id,
            loaded_tokens=100,
            unloaded_tokens=50,
            event_type="resume"
        )
        
        # 2. 검색 수행 - 토큰 기록
        await token_tracker.record_session_tokens(
            session_id=session_id,
            loaded_tokens=200,
            unloaded_tokens=100,
            event_type="search"
        )
        
        # 3. 임계값 확인
        mock_db.fetchone.return_value = {"total_loaded_tokens": 300}
        exceeded = await token_tracker.check_threshold(session_id)
        assert exceeded is False
        
        # 4. 절감률 계산
        mock_db.fetchone.return_value = {
            "initial_context_tokens": 100,
            "total_loaded_tokens": 300,
            "total_saved_tokens": 150
        }
        savings = await token_tracker.calculate_savings(session_id)
        
        assert savings["total_tokens"] == 450
        assert savings["savings_rate"] > 0
