"""메트릭 수집 통합 테스트

SearchService와 EmbeddingService에 MetricsCollector가 올바르게 통합되었는지 테스트합니다.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.services.search import SearchService
from app.core.services.metrics_collector import MetricsCollector
from app.core.embeddings.service import EmbeddingService
from app.core.schemas.responses import SearchResponse, SearchResult


class TestSearchServiceMetricsIntegration:
    """SearchService 메트릭 통합 테스트"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock Database"""
        db = AsyncMock()
        db.vector_search = AsyncMock(return_value=[])
        db.get_recent_memories = AsyncMock(return_value=[])
        db.count_memories = AsyncMock(return_value=0)
        db.fetchall = AsyncMock(return_value=[])
        return db
    
    @pytest.fixture
    def mock_embedding_service(self):
        """Mock EmbeddingService"""
        service = MagicMock()
        service.embed = MagicMock(return_value=[0.1] * 384)
        service.to_bytes = MagicMock(return_value=b'\x00' * 1536)
        return service
    
    @pytest.fixture
    def mock_metrics_collector(self):
        """Mock MetricsCollector"""
        collector = AsyncMock(spec=MetricsCollector)
        collector.collect_search_metric = AsyncMock(return_value="metric-id-123")
        return collector
    
    @pytest.mark.asyncio
    async def test_search_collects_metrics(
        self, mock_db, mock_embedding_service, mock_metrics_collector
    ):
        """검색 시 메트릭이 수집되는지 테스트"""
        # Given
        service = SearchService(
            db=mock_db,
            embedding_service=mock_embedding_service,
            metrics_collector=mock_metrics_collector
        )
        
        # When
        with patch.object(service.cache_manager, 'get_cached_search', return_value=None):
            with patch.object(service.cache_manager, 'get_cached_embedding', return_value=None):
                with patch.object(service.cache_manager, 'cache_embedding', return_value=None):
                    with patch.object(service.cache_manager, 'cache_search_results', return_value=None):
                        result = await service.search(query="test query", limit=5)
        
        # Then
        mock_metrics_collector.collect_search_metric.assert_called_once()
        call_kwargs = mock_metrics_collector.collect_search_metric.call_args.kwargs
        assert call_kwargs['query'] == "test query"
        assert call_kwargs['result_count'] == 0
        assert call_kwargs['response_time_ms'] >= 0
        assert call_kwargs['source'] == "search_service"
    
    @pytest.mark.asyncio
    async def test_search_without_metrics_collector(
        self, mock_db, mock_embedding_service
    ):
        """MetricsCollector 없이도 검색이 정상 동작하는지 테스트"""
        # Given
        service = SearchService(
            db=mock_db,
            embedding_service=mock_embedding_service,
            metrics_collector=None  # No metrics collector
        )
        
        # When
        with patch.object(service.cache_manager, 'get_cached_search', return_value=None):
            with patch.object(service.cache_manager, 'get_cached_embedding', return_value=None):
                with patch.object(service.cache_manager, 'cache_embedding', return_value=None):
                    with patch.object(service.cache_manager, 'cache_search_results', return_value=None):
                        result = await service.search(query="test query", limit=5)
        
        # Then - 에러 없이 결과 반환
        assert isinstance(result, SearchResponse)
    
    @pytest.mark.asyncio
    async def test_search_metrics_include_similarity_scores(
        self, mock_db, mock_embedding_service, mock_metrics_collector
    ):
        """검색 결과에 유사도 점수가 포함되는지 테스트"""
        # Given
        mock_db.vector_search = AsyncMock(return_value=[
            {
                'id': '1', 'content': 'test content 1', 'distance': 0.2,
                'created_at': '2024-01-01T00:00:00Z', 'project_id': 'test',
                'category': 'task', 'source': 'test', 'tags': '[]'
            },
            {
                'id': '2', 'content': 'test content 2', 'distance': 0.4,
                'created_at': '2024-01-01T00:00:00Z', 'project_id': 'test',
                'category': 'task', 'source': 'test', 'tags': '[]'
            }
        ])
        
        service = SearchService(
            db=mock_db,
            embedding_service=mock_embedding_service,
            metrics_collector=mock_metrics_collector
        )
        
        # When
        with patch.object(service.cache_manager, 'get_cached_search', return_value=None):
            with patch.object(service.cache_manager, 'get_cached_embedding', return_value=None):
                with patch.object(service.cache_manager, 'cache_embedding', return_value=None):
                    with patch.object(service.cache_manager, 'cache_search_results', return_value=None):
                        result = await service.search(query="test", limit=5)
        
        # Then
        call_kwargs = mock_metrics_collector.collect_search_metric.call_args.kwargs
        assert call_kwargs['avg_similarity'] is not None
        assert call_kwargs['top_similarity'] is not None
        assert call_kwargs['result_count'] == 2
    
    @pytest.mark.asyncio
    async def test_empty_query_collects_metrics(
        self, mock_db, mock_embedding_service, mock_metrics_collector
    ):
        """빈 쿼리 검색도 메트릭을 수집하는지 테스트"""
        # Given
        mock_db.get_recent_memories = AsyncMock(return_value=[
            {
                'id': '1', 'content': 'test', 'created_at': '2024-01-01T00:00:00Z',
                'project_id': 'test', 'category': 'task', 'source': 'test', 'tags': '[]'
            }
        ])
        mock_db.count_memories = AsyncMock(return_value=1)
        
        service = SearchService(
            db=mock_db,
            embedding_service=mock_embedding_service,
            metrics_collector=mock_metrics_collector
        )
        
        # When
        result = await service.search(query="", limit=5)
        
        # Then
        mock_metrics_collector.collect_search_metric.assert_called_once()
        call_kwargs = mock_metrics_collector.collect_search_metric.call_args.kwargs
        assert call_kwargs['query'] == ""


class TestEmbeddingServiceMetricsIntegration:
    """EmbeddingService 메트릭 통합 테스트"""
    
    @pytest.fixture
    def mock_metrics_collector(self):
        """Mock MetricsCollector"""
        collector = AsyncMock(spec=MetricsCollector)
        collector.collect_embedding_metric = AsyncMock(return_value="metric-id-456")
        return collector
    
    def test_embedding_service_accepts_metrics_collector(self, mock_metrics_collector):
        """EmbeddingService가 metrics_collector를 받는지 테스트"""
        # Given/When
        with patch('app.core.embeddings.service.SentenceTransformer'):
            service = EmbeddingService(
                model_name="all-MiniLM-L6-v2",
                preload=False,
                metrics_collector=mock_metrics_collector
            )
        
        # Then
        assert service.metrics_collector == mock_metrics_collector
    
    def test_embedding_without_metrics_collector(self):
        """MetricsCollector 없이도 임베딩이 정상 동작하는지 테스트"""
        # Given
        import numpy as np
        
        with patch('app.core.embeddings.service.SentenceTransformer') as mock_st:
            mock_model = MagicMock()
            # numpy array를 반환하도록 설정
            mock_model.encode.return_value = np.array([0.1] * 384)
            mock_model.get_sentence_embedding_dimension.return_value = 384
            mock_st.return_value = mock_model
            
            service = EmbeddingService(
                model_name="all-MiniLM-L6-v2",
                preload=True,
                metrics_collector=None
            )
        
        # When
        result = service.embed("test text")
        
        # Then
        assert len(result) == 384


class TestMetricsCollectorBuffering:
    """MetricsCollector 버퍼링 테스트"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock Database"""
        db = AsyncMock()
        db.execute = AsyncMock()
        return db
    
    @pytest.mark.asyncio
    async def test_buffer_auto_flush_on_size(self, mock_db):
        """버퍼 크기 도달 시 자동 플러시 테스트"""
        # Given
        collector = MetricsCollector(
            database=mock_db,
            buffer_size=3,  # 작은 버퍼 크기
            flush_interval=3600  # 긴 간격 (자동 플러시 방지)
        )
        
        # When - 버퍼 크기만큼 메트릭 추가
        for i in range(3):
            await collector.collect_search_metric(
                query=f"query {i}",
                result_count=i,
                response_time_ms=100
            )
        
        # Then - 자동 플러시 발생
        assert mock_db.execute.call_count == 3
        assert len(collector.search_buffer) == 0
    
    @pytest.mark.asyncio
    async def test_manual_flush(self, mock_db):
        """수동 플러시 테스트"""
        # Given
        collector = MetricsCollector(
            database=mock_db,
            buffer_size=100,
            flush_interval=3600
        )
        
        await collector.collect_search_metric(
            query="test",
            result_count=5,
            response_time_ms=100
        )
        
        # When
        await collector.flush()
        
        # Then
        assert mock_db.execute.call_count == 1
        assert len(collector.search_buffer) == 0
    
    @pytest.mark.asyncio
    async def test_buffer_stats(self, mock_db):
        """버퍼 상태 조회 테스트"""
        # Given
        collector = MetricsCollector(
            database=mock_db,
            buffer_size=100,
            flush_interval=60
        )
        
        await collector.collect_search_metric(
            query="test",
            result_count=5,
            response_time_ms=100
        )
        
        # When
        stats = await collector.get_buffer_stats()
        
        # Then
        assert stats['search_buffer_size'] == 1
        assert stats['embedding_buffer_size'] == 0
        assert stats['buffer_capacity'] == 100
        assert stats['flush_interval'] == 60
