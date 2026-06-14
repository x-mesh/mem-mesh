"""UnifiedSearchService의 search_with_context_optimization 메서드 테스트

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.schemas.responses import SearchResponse
from app.core.schemas.sessions import SessionContext
from app.core.services.unified_search import UnifiedSearchService


@pytest.fixture
def mock_db():
    """Mock Database"""
    db = MagicMock()
    db.fetchall = AsyncMock(return_value=[])
    db.fetchone = AsyncMock(return_value=None)
    db.execute = AsyncMock()
    db.vector_search = AsyncMock(return_value=[])
    return db


@pytest.fixture
def mock_embedding_service():
    """Mock EmbeddingService"""
    from app.core.config import Settings

    dim = Settings().embedding_dim
    service = MagicMock()
    service.embed = MagicMock(return_value=[0.1] * dim)
    # Search now offloads embedding via the async aembed/aembed_batch wrappers.
    service.aembed = AsyncMock(return_value=[0.1] * dim)
    service.aembed_batch = AsyncMock(return_value=[[0.1] * dim])
    service.to_bytes = MagicMock(return_value=b"\x00" * (dim * 4))
    return service


@pytest.fixture
def unified_search_service(mock_db, mock_embedding_service):
    """UnifiedSearchService 인스턴스"""
    return UnifiedSearchService(
        db=mock_db,
        embedding_service=mock_embedding_service,
        enable_quality_features=True,
        enable_korean_optimization=True,
    )


@pytest.mark.asyncio
async def test_search_with_context_optimization_disabled(unified_search_service):
    """맥락 최적화가 비활성화된 경우 검색 결과만 반환"""
    # Given
    query = "test query"
    project_id = "test-project"

    # When
    search_response, context = (
        await unified_search_service.search_with_context_optimization(
            query=query, project_id=project_id, optimize_context=False
        )
    )

    # Then
    assert search_response is not None
    assert isinstance(search_response, SearchResponse)
    assert context is None  # 최적화 비활성화 시 맥락 없음


@pytest.mark.asyncio
async def test_search_with_context_optimization_no_project_id(unified_search_service):
    """프로젝트 ID가 없으면 맥락 최적화 스킵"""
    # Given
    query = "test query"

    # When
    search_response, context = (
        await unified_search_service.search_with_context_optimization(
            query=query, project_id=None, optimize_context=True
        )
    )

    # Then
    assert search_response is not None
    assert context is None  # 프로젝트 ID 없으면 맥락 없음


@pytest.mark.asyncio
async def test_search_with_context_optimization_with_intent(
    unified_search_service, mock_db
):
    """의도 분석과 함께 맥락 최적화 수행"""
    # Given
    query = "debug error in authentication"
    project_id = "test-project"

    # Mock 세션 데이터
    mock_db.fetchone.return_value = {
        "id": "session-1",
        "project_id": project_id,
        "user_id": "root",
        "started_at": "2026-02-03T00:00:00+00:00",
        "ended_at": None,
        "status": "active",
        "summary": "Test session",
        "created_at": "2026-02-03T00:00:00+00:00",
        "updated_at": "2026-02-03T00:00:00+00:00",
    }

    # Mock 핀 통계
    mock_db.fetchall.return_value = []

    # When
    with patch("app.core.services.session.SessionService") as MockSessionService:
        with patch(
            "app.core.services.context_optimizer.ContextOptimizer"
        ) as MockContextOptimizer:
            # Mock SessionService
            mock_session_service = MagicMock()
            MockSessionService.return_value = mock_session_service

            # Mock ContextOptimizer
            mock_context_optimizer = MagicMock()
            mock_context = SessionContext(
                session_id="session-1",
                project_id=project_id,
                user_id="root",
                status="active",
                started_at="2026-02-03T00:00:00+00:00",
                summary="Test session",
                pins_count=5,
                open_pins=2,
                completed_pins=3,
                pins=[],
            )
            mock_context_optimizer.load_context_for_search = AsyncMock(
                return_value=mock_context
            )
            MockContextOptimizer.return_value = mock_context_optimizer

            search_response, context = (
                await unified_search_service.search_with_context_optimization(
                    query=query, project_id=project_id, optimize_context=True
                )
            )

    # Then
    assert search_response is not None
    assert context is not None
    assert context.session_id == "session-1"
    assert context.project_id == project_id


@pytest.mark.asyncio
async def test_search_with_context_optimization_no_active_session(
    unified_search_service, mock_db
):
    """활성 세션이 없으면 맥락 없이 검색 결과만 반환"""
    # Given
    query = "test query"
    project_id = "test-project"

    # Mock: 세션 없음
    mock_db.fetchone.return_value = None

    # When
    with patch("app.core.services.session.SessionService") as MockSessionService:
        with patch(
            "app.core.services.context_optimizer.ContextOptimizer"
        ) as MockContextOptimizer:
            mock_session_service = MagicMock()
            MockSessionService.return_value = mock_session_service

            mock_context_optimizer = MagicMock()
            mock_context_optimizer.load_context_for_search = AsyncMock(
                return_value=None
            )
            MockContextOptimizer.return_value = mock_context_optimizer

            search_response, context = (
                await unified_search_service.search_with_context_optimization(
                    query=query, project_id=project_id, optimize_context=True
                )
            )

    # Then
    assert search_response is not None
    assert context is None  # 세션 없으면 맥락 없음


@pytest.mark.asyncio
async def test_search_with_context_optimization_error_handling(unified_search_service):
    """맥락 로드 실패 시에도 검색 결과는 반환"""
    # Given
    query = "test query"
    project_id = "test-project"

    # When
    with patch("app.core.services.session.SessionService") as MockSessionService:
        # SessionService 초기화 시 예외 발생
        MockSessionService.side_effect = Exception("Database error")

        search_response, context = (
            await unified_search_service.search_with_context_optimization(
                query=query, project_id=project_id, optimize_context=True
            )
        )

    # Then
    assert search_response is not None  # 검색은 성공
    assert context is None  # 맥락 로드는 실패했지만 에러는 발생하지 않음


@pytest.mark.asyncio
async def test_search_with_context_optimization_default_intent(unified_search_service):
    """의도 분석기가 없을 때 기본 의도 사용"""
    # Given
    query = "test query"
    project_id = "test-project"

    # 의도 분석기 비활성화
    unified_search_service.enable_quality_features = False
    unified_search_service.intent_analyzer = None

    # When
    with patch("app.core.services.session.SessionService") as MockSessionService:
        with patch(
            "app.core.services.context_optimizer.ContextOptimizer"
        ) as MockContextOptimizer:
            mock_session_service = MagicMock()
            MockSessionService.return_value = mock_session_service

            mock_context_optimizer = MagicMock()
            mock_context_optimizer.load_context_for_search = AsyncMock(
                return_value=None
            )
            MockContextOptimizer.return_value = mock_context_optimizer

            search_response, context = (
                await unified_search_service.search_with_context_optimization(
                    query=query, project_id=project_id, optimize_context=True
                )
            )

    # Then
    assert search_response is not None
    # 기본 의도가 사용되었는지 확인 (load_context_for_search가 호출되었는지)
    mock_context_optimizer.load_context_for_search.assert_called_once()
    call_args = mock_context_optimizer.load_context_for_search.call_args
    assert call_args[1]["query"] == query
    assert call_args[1]["project_id"] == project_id
    assert call_args[1]["intent"] is not None  # 기본 의도가 전달됨
