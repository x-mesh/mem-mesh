"""ContextOptimizer 서비스 테스트

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass

from app.core.services.context_optimizer import ContextOptimizer, ContextLoadingParams
from app.core.schemas.sessions import SessionContext, SessionResponse
from app.core.schemas.pins import PinResponse


@dataclass
class MockSearchIntent:
    """테스트용 SearchIntent 모의 객체"""
    intent_type: str
    urgency: float
    specificity: float
    temporal_focus: str
    expected_category: str = None
    key_entities: list = None


@pytest.fixture
def mock_session_service():
    """SessionService 모의 객체"""
    service = MagicMock()
    service.resume_last_session = AsyncMock()
    return service


@pytest.fixture
def context_optimizer(mock_session_service):
    """ContextOptimizer 인스턴스"""
    return ContextOptimizer(session_service=mock_session_service)


@pytest.fixture
def sample_session_context():
    """샘플 세션 컨텍스트"""
    return SessionContext(
        session_id="test-session-id",
        project_id="test-project",
        user_id="test-user",
        status="active",
        started_at="2026-02-03T00:00:00Z",
        summary="테스트 세션",
        pins_count=5,
        open_pins=3,
        completed_pins=2,
        pins=[
            PinResponse(
                id="pin-1",
                session_id="test-session-id",
                project_id="test-project",
                user_id="test-user",
                content="중요한 작업 1" * 20,  # ~200자
                importance=5,
                status="open",
                tags=["important"],
                completed_at=None,
                lead_time_hours=None,
                created_at="2026-02-03T00:00:00Z",
                updated_at="2026-02-03T00:00:00Z"
            ),
            PinResponse(
                id="pin-2",
                session_id="test-session-id",
                project_id="test-project",
                user_id="test-user",
                content="일반 작업 2" * 10,  # ~100자
                importance=3,
                status="open",
                tags=["normal"],
                completed_at=None,
                lead_time_hours=None,
                created_at="2026-02-03T00:00:00Z",
                updated_at="2026-02-03T00:00:00Z"
            ),
            PinResponse(
                id="pin-3",
                session_id="test-session-id",
                project_id="test-project",
                user_id="test-user",
                content="사소한 작업 3" * 5,  # ~50자
                importance=1,
                status="completed",
                tags=["minor"],
                completed_at="2026-02-03T01:00:00Z",
                lead_time_hours=1.0,
                created_at="2026-02-03T00:00:00Z",
                updated_at="2026-02-03T01:00:00Z"
            )
        ]
    )


class TestContextOptimizerInitialization:
    """ContextOptimizer 초기화 테스트"""
    
    def test_initialization(self, mock_session_service):
        """정상 초기화 확인"""
        optimizer = ContextOptimizer(session_service=mock_session_service)
        
        assert optimizer.session_service == mock_session_service
        assert 'debug' in optimizer._intent_params
        assert 'explore' in optimizer._intent_params
        assert 'implement' in optimizer._intent_params
        assert optimizer._default_params is not None
    
    def test_intent_params_structure(self, context_optimizer):
        """의도별 파라미터 구조 확인"""
        for intent_type, params in context_optimizer._intent_params.items():
            assert isinstance(params, ContextLoadingParams)
            assert isinstance(params.expand, bool)
            assert isinstance(params.limit, int)
            assert isinstance(params.min_importance, int)
            assert 1 <= params.min_importance <= 5


class TestAdjustForIntent:
    """adjust_for_intent 메서드 테스트"""
    
    @pytest.mark.asyncio
    async def test_debug_intent(self, context_optimizer):
        """Debug 의도: 상세 모드, 적은 개수, 높은 중요도
        
        Requirements: 6.1
        """
        intent = MockSearchIntent(
            intent_type='debug',
            urgency=0.5,
            specificity=0.5,
            temporal_focus='any'
        )
        
        expand, limit, min_importance = await context_optimizer.adjust_for_intent(
            intent=intent,
            project_id="test-project",
            base_limit=10
        )
        
        assert expand is True, "Debug 의도는 상세 모드여야 함"
        assert limit <= 10, "Debug 의도는 적은 개수를 반환해야 함"
        assert min_importance >= 3, "Debug 의도는 높은 중요도를 요구해야 함"
    
    @pytest.mark.asyncio
    async def test_explore_intent(self, context_optimizer):
        """Explore 의도: 요약 모드, 많은 개수, 낮은 중요도
        
        Requirements: 6.2
        """
        intent = MockSearchIntent(
            intent_type='explore',
            urgency=0.3,
            specificity=0.3,
            temporal_focus='any'
        )
        
        expand, limit, min_importance = await context_optimizer.adjust_for_intent(
            intent=intent,
            project_id="test-project",
            base_limit=10
        )
        
        assert expand is False, "Explore 의도는 요약 모드여야 함"
        assert limit >= 15, "Explore 의도는 많은 개수를 반환해야 함"
        assert min_importance <= 2, "Explore 의도는 낮은 중요도를 허용해야 함"
    
    @pytest.mark.asyncio
    async def test_implement_intent(self, context_optimizer):
        """Implement 의도: 상세 모드, 중간 개수, 중간 중요도
        
        Requirements: 6.3
        """
        intent = MockSearchIntent(
            intent_type='implement',
            urgency=0.5,
            specificity=0.6,
            temporal_focus='any'
        )
        
        expand, limit, min_importance = await context_optimizer.adjust_for_intent(
            intent=intent,
            project_id="test-project",
            base_limit=10
        )
        
        assert expand is True, "Implement 의도는 상세 모드여야 함"
        assert 5 <= limit <= 15, "Implement 의도는 중간 개수를 반환해야 함"
        assert 2 <= min_importance <= 4, "Implement 의도는 중간 중요도를 요구해야 함"
    
    @pytest.mark.asyncio
    async def test_unknown_intent_uses_default(self, context_optimizer):
        """알 수 없는 의도는 기본값 사용
        
        Requirements: 6.4
        """
        intent = MockSearchIntent(
            intent_type='unknown_type',
            urgency=0.5,
            specificity=0.5,
            temporal_focus='any'
        )
        
        expand, limit, min_importance = await context_optimizer.adjust_for_intent(
            intent=intent,
            project_id="test-project",
            base_limit=10
        )
        
        # 기본값 확인
        assert expand is False, "알 수 없는 의도는 요약 모드를 기본값으로 사용"
        assert limit == 10, "알 수 없는 의도는 기본 limit 사용"
        assert min_importance == 1, "알 수 없는 의도는 낮은 중요도를 기본값으로 사용"
    
    @pytest.mark.asyncio
    async def test_high_urgency_adjustment(self, context_optimizer):
        """높은 긴급도는 결과 수를 줄이고 중요도를 높임"""
        intent = MockSearchIntent(
            intent_type='lookup',
            urgency=0.9,  # 매우 긴급
            specificity=0.5,
            temporal_focus='any'
        )
        
        expand, limit, min_importance = await context_optimizer.adjust_for_intent(
            intent=intent,
            project_id="test-project",
            base_limit=10
        )
        
        assert limit <= 5, "높은 긴급도는 결과 수를 5개 이하로 제한"
        assert min_importance >= 4, "높은 긴급도는 중요도를 4 이상으로 설정"
        assert expand is True, "높은 긴급도는 상세 모드 활성화"
    
    @pytest.mark.asyncio
    async def test_high_specificity_adjustment(self, context_optimizer):
        """높은 구체성은 정확한 매칭 필요"""
        intent = MockSearchIntent(
            intent_type='lookup',
            urgency=0.5,
            specificity=0.9,  # 매우 구체적
            temporal_focus='any'
        )
        
        expand, limit, min_importance = await context_optimizer.adjust_for_intent(
            intent=intent,
            project_id="test-project",
            base_limit=10
        )
        
        assert limit <= 3, "높은 구체성은 결과 수를 3개 이하로 제한"
        assert expand is True, "높은 구체성은 상세 모드 활성화"
    
    @pytest.mark.asyncio
    async def test_low_specificity_adjustment(self, context_optimizer):
        """낮은 구체성은 넓은 범위 탐색"""
        intent = MockSearchIntent(
            intent_type='lookup',
            urgency=0.5,
            specificity=0.2,  # 모호함
            temporal_focus='any'
        )
        
        expand, limit, min_importance = await context_optimizer.adjust_for_intent(
            intent=intent,
            project_id="test-project",
            base_limit=10
        )
        
        assert limit >= 15, "낮은 구체성은 결과 수를 15개 이상으로 확장"
        assert expand is False, "낮은 구체성은 요약 모드 사용"
        assert min_importance == 1, "낮은 구체성은 모든 중요도 허용"
    
    @pytest.mark.asyncio
    async def test_recent_temporal_focus(self, context_optimizer):
        """최근 시간 초점은 더 많은 결과"""
        intent = MockSearchIntent(
            intent_type='review',
            urgency=0.5,
            specificity=0.5,
            temporal_focus='recent'
        )
        
        expand, limit, min_importance = await context_optimizer.adjust_for_intent(
            intent=intent,
            project_id="test-project",
            base_limit=10
        )
        
        assert limit >= 10, "최근 시간 초점은 더 많은 결과 반환"
    
    @pytest.mark.asyncio
    async def test_base_limit_consideration(self, context_optimizer):
        """base_limit이 기본값이 아닌 경우 중간값 사용"""
        intent = MockSearchIntent(
            intent_type='explore',
            urgency=0.5,
            specificity=0.5,
            temporal_focus='any'
        )
        
        # explore의 기본 limit은 20
        expand, limit, min_importance = await context_optimizer.adjust_for_intent(
            intent=intent,
            project_id="test-project",
            base_limit=30  # 사용자 명시적 요청
        )
        
        # (20 + 30) / 2 = 25 정도 예상
        assert 20 <= limit <= 30, "base_limit과 의도 기반 limit의 중간값 사용"


class TestLoadContextForSearch:
    """load_context_for_search 메서드 테스트"""
    
    @pytest.mark.asyncio
    async def test_load_context_with_debug_intent(
        self, 
        context_optimizer, 
        mock_session_service,
        sample_session_context
    ):
        """Debug 의도로 맥락 로드
        
        Requirements: 6.1, 6.5
        """
        mock_session_service.resume_last_session.return_value = sample_session_context
        
        intent = MockSearchIntent(
            intent_type='debug',
            urgency=0.5,
            specificity=0.5,
            temporal_focus='any'
        )
        
        context = await context_optimizer.load_context_for_search(
            query="test query",
            project_id="test-project",
            intent=intent
        )
        
        assert context is not None
        assert context.session_id == "test-session-id"
        
        # resume_last_session이 올바른 파라미터로 호출되었는지 확인
        mock_session_service.resume_last_session.assert_called_once()
        call_kwargs = mock_session_service.resume_last_session.call_args.kwargs
        assert call_kwargs['project_id'] == "test-project"
        assert call_kwargs['expand'] is True  # Debug는 상세 모드
    
    @pytest.mark.asyncio
    async def test_load_context_with_explore_intent(
        self, 
        context_optimizer, 
        mock_session_service,
        sample_session_context
    ):
        """Explore 의도로 맥락 로드
        
        Requirements: 6.2, 6.5
        """
        mock_session_service.resume_last_session.return_value = sample_session_context
        
        intent = MockSearchIntent(
            intent_type='explore',
            urgency=0.3,
            specificity=0.3,
            temporal_focus='any'
        )
        
        context = await context_optimizer.load_context_for_search(
            query="test query",
            project_id="test-project",
            intent=intent
        )
        
        assert context is not None
        
        # resume_last_session이 올바른 파라미터로 호출되었는지 확인
        call_kwargs = mock_session_service.resume_last_session.call_args.kwargs
        assert call_kwargs['expand'] is False  # Explore는 요약 모드
        assert call_kwargs['limit'] >= 15  # Explore는 많은 개수
    
    @pytest.mark.asyncio
    async def test_load_context_no_session(
        self, 
        context_optimizer, 
        mock_session_service
    ):
        """세션이 없는 경우 None 반환"""
        mock_session_service.resume_last_session.return_value = None
        
        intent = MockSearchIntent(
            intent_type='debug',
            urgency=0.5,
            specificity=0.5,
            temporal_focus='any'
        )
        
        context = await context_optimizer.load_context_for_search(
            query="test query",
            project_id="nonexistent-project",
            intent=intent
        )
        
        assert context is None
    
    @pytest.mark.asyncio
    async def test_importance_filtering_in_expand_mode(
        self, 
        context_optimizer, 
        mock_session_service,
        sample_session_context
    ):
        """상세 모드에서 중요도 필터링 적용"""
        mock_session_service.resume_last_session.return_value = sample_session_context
        
        intent = MockSearchIntent(
            intent_type='debug',
            urgency=0.9,  # 높은 긴급도 -> min_importance=4
            specificity=0.5,
            temporal_focus='any'
        )
        
        context = await context_optimizer.load_context_for_search(
            query="test query",
            project_id="test-project",
            intent=intent
        )
        
        assert context is not None
        # importance >= 4인 핀만 남아야 함 (pin-1만 해당)
        assert len(context.pins) == 1
        assert context.pins[0].importance >= 4
    
    @pytest.mark.asyncio
    async def test_no_filtering_in_summary_mode(
        self, 
        context_optimizer, 
        mock_session_service,
        sample_session_context
    ):
        """요약 모드에서는 중요도 필터링 미적용"""
        mock_session_service.resume_last_session.return_value = sample_session_context
        
        intent = MockSearchIntent(
            intent_type='explore',
            urgency=0.3,
            specificity=0.3,
            temporal_focus='any'
        )
        
        context = await context_optimizer.load_context_for_search(
            query="test query",
            project_id="test-project",
            intent=intent
        )
        
        assert context is not None
        # 요약 모드에서는 필터링 없이 모든 핀 유지
        assert len(context.pins) == 3


class TestTokenEstimation:
    """토큰 추정 테스트"""
    
    def test_estimate_summary_mode(self, context_optimizer, sample_session_context):
        """요약 모드 토큰 추정
        
        Requirements: 6.5
        """
        estimated = context_optimizer._estimate_context_tokens(
            context=sample_session_context,
            expand=False
        )
        
        # 요약 모드: 기본(50) + 요약(50) = ~100 토큰
        assert estimated <= 150, "요약 모드는 150 토큰 이하여야 함"
        assert estimated >= 50, "최소 기본 정보는 포함"
    
    def test_estimate_expand_mode(self, context_optimizer, sample_session_context):
        """상세 모드 토큰 추정
        
        Requirements: 6.5
        """
        estimated = context_optimizer._estimate_context_tokens(
            context=sample_session_context,
            expand=True
        )
        
        # 상세 모드: 기본(50) + 요약(50) + 핀들(~150-600) = 250-700 토큰
        assert estimated > 150, "상세 모드는 요약 모드보다 많은 토큰 사용"
        assert estimated < 1000, "합리적인 범위 내의 토큰 수"
    
    def test_estimate_no_summary(self, context_optimizer, sample_session_context):
        """요약이 없는 경우"""
        sample_session_context.summary = None
        
        estimated = context_optimizer._estimate_context_tokens(
            context=sample_session_context,
            expand=False
        )
        
        # 요약 없음: 기본(50) = ~50 토큰
        assert estimated <= 100, "요약 없는 경우 더 적은 토큰"
    
    def test_estimate_no_pins(self, context_optimizer, sample_session_context):
        """핀이 없는 경우"""
        sample_session_context.pins = []
        
        estimated = context_optimizer._estimate_context_tokens(
            context=sample_session_context,
            expand=True
        )
        
        # 핀 없음: 기본(50) + 요약(50) = ~100 토큰
        assert estimated <= 150, "핀이 없으면 상세 모드도 적은 토큰"


class TestGetIntentStrategyInfo:
    """get_intent_strategy_info 메서드 테스트"""
    
    def test_get_debug_strategy(self, context_optimizer):
        """Debug 전략 정보 조회"""
        info = context_optimizer.get_intent_strategy_info('debug')
        
        assert info['intent_type'] == 'debug'
        assert info['expand'] is True
        assert info['min_importance'] >= 3
        assert 'description' in info
    
    def test_get_explore_strategy(self, context_optimizer):
        """Explore 전략 정보 조회"""
        info = context_optimizer.get_intent_strategy_info('explore')
        
        assert info['intent_type'] == 'explore'
        assert info['expand'] is False
        assert info['limit'] >= 15
        assert 'description' in info
    
    def test_get_unknown_strategy(self, context_optimizer):
        """알 수 없는 전략은 기본값 반환"""
        info = context_optimizer.get_intent_strategy_info('unknown')
        
        assert info['intent_type'] == 'unknown'
        assert 'description' in info
