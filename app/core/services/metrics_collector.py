"""메트릭 수집 서비스

검색 및 임베딩 작업의 성능 메트릭을 수집하고 저장합니다.
버퍼링을 통해 데이터베이스 쓰기를 최적화합니다.
"""

import asyncio
import time
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4

from app.core.database.base import Database
from app.core.database.models import SearchMetric, EmbeddingMetric
from app.core.utils.logger import get_logger

logger = get_logger(__name__)


class MetricsCollector:
    """메트릭 수집 및 저장 서비스"""
    
    def __init__(
        self,
        database: Database,
        buffer_size: int = 100,
        flush_interval: int = 60,
        hash_queries: bool = False
    ):
        """
        Args:
            database: 데이터베이스 인스턴스
            buffer_size: 버퍼 크기 (이 크기에 도달하면 자동 플러시)
            flush_interval: 자동 플러시 간격 (초)
            hash_queries: 쿼리 내용을 해시 처리할지 여부 (보안)
        """
        self.database = database
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        self.hash_queries = hash_queries
        
        self.search_buffer: List[SearchMetric] = []
        self.embedding_buffer: List[EmbeddingMetric] = []
        
        self._flush_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
    
    async def start(self):
        """백그라운드 플러시 태스크 시작"""
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._auto_flush())
            logger.info(f"MetricsCollector started (buffer_size={self.buffer_size}, flush_interval={self.flush_interval}s)")
    
    async def stop(self):
        """백그라운드 태스크 중지 및 버퍼 플러시"""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # 남은 버퍼 플러시
        await self.flush()
        logger.info("MetricsCollector stopped")
    
    async def _auto_flush(self):
        """주기적으로 버퍼 플러시"""
        while True:
            try:
                await asyncio.sleep(self.flush_interval)
                await self.flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Auto flush error: {e}")
    
    def _sanitize_query(self, query: str) -> str:
        """쿼리 내용 처리 (해시 옵션)"""
        if self.hash_queries:
            import hashlib
            return hashlib.sha256(query.encode()).hexdigest()[:16]
        return query
    
    async def collect_search_metric(
        self,
        query: str,
        result_count: int,
        response_time_ms: int,
        avg_similarity: Optional[float] = None,
        top_similarity: Optional[float] = None,
        project_id: Optional[str] = None,
        category: Optional[str] = None,
        embedding_time_ms: Optional[int] = None,
        search_time_ms: Optional[int] = None,
        response_format: Optional[str] = None,
        original_size_bytes: Optional[int] = None,
        compressed_size_bytes: Optional[int] = None,
        user_agent: Optional[str] = None,
        source: str = "unknown"
    ) -> str:
        """
        검색 메트릭 수집
        
        Args:
            query: 검색 쿼리
            result_count: 검색 결과 수
            response_time_ms: 총 응답 시간 (ms)
            avg_similarity: 평균 유사도 점수
            top_similarity: 최고 유사도 점수
            project_id: 프로젝트 ID
            category: 카테고리
            embedding_time_ms: 임베딩 생성 시간 (ms)
            search_time_ms: 검색 시간 (ms)
            response_format: 응답 형식 ('full', 'compact', 'minimal')
            original_size_bytes: 원본 크기 (bytes)
            compressed_size_bytes: 압축 후 크기 (bytes)
            user_agent: User-Agent
            source: 소스 ('mcp_stdio', 'mcp_pure', 'web_api')
        
        Returns:
            메트릭 ID
        """
        metric = SearchMetric(
            query=self._sanitize_query(query),
            query_length=len(query),
            result_count=result_count,
            avg_similarity_score=avg_similarity,
            top_similarity_score=top_similarity,
            response_time_ms=response_time_ms,
            embedding_time_ms=embedding_time_ms,
            search_time_ms=search_time_ms,
            project_id=project_id,
            category=category,
            response_format=response_format,
            original_size_bytes=original_size_bytes,
            compressed_size_bytes=compressed_size_bytes,
            user_agent=user_agent,
            source=source
        )
        
        async with self._lock:
            self.search_buffer.append(metric)
            
            # 버퍼가 가득 차면 자동 플러시
            if len(self.search_buffer) >= self.buffer_size:
                await self._flush_search_buffer()
        
        return metric.id
    
    async def collect_embedding_metric(
        self,
        operation: str,
        count: int,
        total_time_ms: int,
        cache_hit: bool,
        model_name: str,
        memory_usage_mb: Optional[float] = None
    ) -> str:
        """
        임베딩 메트릭 수집
        
        Args:
            operation: 작업 유형 ('generate', 'batch_generate')
            count: 생성된 임베딩 수
            total_time_ms: 총 소요 시간 (ms)
            cache_hit: 캐시 히트 여부
            model_name: 모델 이름
            memory_usage_mb: 메모리 사용량 (MB)
        
        Returns:
            메트릭 ID
        """
        avg_time = total_time_ms / count if count > 0 else 0
        
        metric = EmbeddingMetric(
            operation=operation,
            count=count,
            total_time_ms=total_time_ms,
            avg_time_per_embedding_ms=avg_time,
            cache_hit=cache_hit,
            memory_usage_mb=memory_usage_mb,
            model_name=model_name
        )
        
        async with self._lock:
            self.embedding_buffer.append(metric)
            
            # 버퍼가 가득 차면 자동 플러시
            if len(self.embedding_buffer) >= self.buffer_size:
                await self._flush_embedding_buffer()
        
        return metric.id
    
    async def flush(self):
        """모든 버퍼 플러시"""
        async with self._lock:
            await self._flush_search_buffer()
            await self._flush_embedding_buffer()
    
    async def _flush_search_buffer(self):
        """검색 메트릭 버퍼 플러시"""
        if not self.search_buffer:
            return
        
        try:
            # 개별 삽입 (일괄 삽입 메서드가 없으므로)
            for metric in self.search_buffer:
                await self.database.execute("""
                    INSERT INTO search_metrics (
                        id, timestamp, query, query_length, project_id, category,
                        result_count, avg_similarity_score, top_similarity_score,
                        response_time_ms, embedding_time_ms, search_time_ms,
                        response_format, original_size_bytes, compressed_size_bytes,
                        user_agent, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    metric.id,
                    metric.timestamp,
                    metric.query,
                    metric.query_length,
                    metric.project_id,
                    metric.category,
                    metric.result_count,
                    metric.avg_similarity_score,
                    metric.top_similarity_score,
                    metric.response_time_ms,
                    metric.embedding_time_ms,
                    metric.search_time_ms,
                    metric.response_format,
                    metric.original_size_bytes,
                    metric.compressed_size_bytes,
                    metric.user_agent,
                    metric.source
                ))
            
            count = len(self.search_buffer)
            self.search_buffer.clear()
            logger.debug(f"Flushed {count} search metrics")
            
        except Exception as e:
            logger.error(f"Failed to flush search metrics: {e}")
    
    async def _flush_embedding_buffer(self):
        """임베딩 메트릭 버퍼 플러시"""
        if not self.embedding_buffer:
            return
        
        try:
            # 개별 삽입 (일괄 삽입 메서드가 없으므로)
            for metric in self.embedding_buffer:
                await self.database.execute("""
                    INSERT INTO embedding_metrics (
                        id, timestamp, operation, count, total_time_ms,
                        avg_time_per_embedding_ms, cache_hit, memory_usage_mb, model_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    metric.id,
                    metric.timestamp,
                    metric.operation,
                    metric.count,
                    metric.total_time_ms,
                    metric.avg_time_per_embedding_ms,
                    metric.cache_hit,
                    metric.memory_usage_mb,
                    metric.model_name
                ))
            
            count = len(self.embedding_buffer)
            self.embedding_buffer.clear()
            logger.debug(f"Flushed {count} embedding metrics")
            
        except Exception as e:
            logger.error(f"Failed to flush embedding metrics: {e}")
    
    async def get_buffer_stats(self) -> Dict[str, Any]:
        """버퍼 상태 조회"""
        async with self._lock:
            return {
                "search_buffer_size": len(self.search_buffer),
                "embedding_buffer_size": len(self.embedding_buffer),
                "buffer_capacity": self.buffer_size,
                "flush_interval": self.flush_interval
            }
