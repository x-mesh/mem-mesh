"""메트릭 수집 서비스

검색 및 임베딩 작업의 성능 메트릭을 수집하고 저장합니다.
버퍼링을 통해 데이터베이스 쓰기를 최적화합니다.
"""

import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any

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
        hash_queries: bool = False,
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
            logger.info(
                f"MetricsCollector started (buffer_size={self.buffer_size}, flush_interval={self.flush_interval}s)"
            )

    async def stop(self):
        """백그라운드 태스크 중지 및 버퍼 플러시"""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                # Task cancelled - flush loop terminated gracefully
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
        source: str = "unknown",
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
        # 빈 쿼리는 모니터링에서 제외 (입력 중 상태, 의미 없는 검색)
        if not query or not query.strip():
            logger.debug("Skipping metric collection for empty query")
            return "skipped-empty-query"

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
            source=source,
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
        memory_usage_mb: Optional[float] = None,
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
            model_name=model_name,
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
                await self.database.execute(
                    """
                    INSERT INTO search_metrics (
                        id, timestamp, query, query_length, project_id, category,
                        result_count, avg_similarity_score, top_similarity_score,
                        response_time_ms, embedding_time_ms, search_time_ms,
                        response_format, original_size_bytes, compressed_size_bytes,
                        user_agent, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
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
                        metric.source,
                    ),
                )

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
                await self.database.execute(
                    """
                    INSERT INTO embedding_metrics (
                        id, timestamp, operation, count, total_time_ms,
                        avg_time_per_embedding_ms, cache_hit, memory_usage_mb, model_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        metric.id,
                        metric.timestamp,
                        metric.operation,
                        metric.count,
                        metric.total_time_ms,
                        metric.avg_time_per_embedding_ms,
                        metric.cache_hit,
                        metric.memory_usage_mb,
                        metric.model_name,
                    ),
                )

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
                "flush_interval": self.flush_interval,
            }

    async def get_search_quality_stats(
        self, hours: int = 24, project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        검색 품질 통계 조회

        Args:
            hours: 조회 기간 (시간)
            project_id: 프로젝트 필터 (선택)

        Returns:
            검색 품질 통계
        """
        from datetime import timedelta

        # 시작 시간 계산
        start_time = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"

        # 기본 쿼리 (빈 쿼리 제외)
        where_clause = "WHERE timestamp >= ? AND query IS NOT NULL AND query != ''"
        params = [start_time]

        if project_id:
            where_clause += " AND project_id = ?"
            params.append(project_id)

        # 전체 통계
        total_stats = await self.database.fetchone(
            f"""
            SELECT 
                COUNT(*) as total_searches,
                AVG(result_count) as avg_results,
                AVG(avg_similarity_score) as avg_score,
                AVG(top_similarity_score) as avg_top_score,
                AVG(response_time_ms) as avg_response_time,
                SUM(CASE WHEN result_count = 0 THEN 1 ELSE 0 END) as zero_result_count,
                SUM(CASE WHEN avg_similarity_score < 0.3 THEN 1 ELSE 0 END) as low_score_count
            FROM search_metrics
            {where_clause}
        """,
            tuple(params),
        )

        # 검색 모드별 통계 (source 기반)
        mode_stats = await self.database.fetchall(
            f"""
            SELECT 
                source,
                COUNT(*) as count,
                AVG(result_count) as avg_results,
                AVG(response_time_ms) as avg_response_time
            FROM search_metrics
            {where_clause}
            GROUP BY source
            ORDER BY count DESC
        """,
            tuple(params),
        )

        # 시간대별 검색 트렌드 (시간별)
        trend_stats = await self.database.fetchall(
            f"""
            SELECT 
                strftime('%Y-%m-%d %H:00:00', timestamp) as hour,
                COUNT(*) as search_count,
                AVG(result_count) as avg_results,
                AVG(avg_similarity_score) as avg_score
            FROM search_metrics
            {where_clause}
            GROUP BY hour
            ORDER BY hour DESC
            LIMIT 24
        """,
            tuple(params),
        )

        # 인기 검색어 Top 10 (해시되지 않은 경우만)
        if not self.hash_queries:
            popular_queries = await self.database.fetchall(
                f"""
                SELECT 
                    query,
                    COUNT(*) as count,
                    AVG(result_count) as avg_results
                FROM search_metrics
                {where_clause}
                GROUP BY query
                ORDER BY count DESC
                LIMIT 10
            """,
                tuple(params),
            )
        else:
            popular_queries = []

        # 품질 지표 계산
        total = total_stats["total_searches"] if total_stats else 0
        zero_result_rate = (
            (total_stats["zero_result_count"] / total * 100)
            if total_stats and total > 0
            else 0
        )
        low_score_rate = (
            (total_stats["low_score_count"] / total * 100)
            if total_stats and total > 0
            else 0
        )

        return {
            "period": {
                "hours": hours,
                "start_time": start_time,
                "end_time": datetime.utcnow().isoformat() + "Z",
            },
            "summary": {
                "total_searches": total,
                "avg_results_per_search": round(total_stats["avg_results"], 2)
                if total_stats and total_stats["avg_results"]
                else 0,
                "avg_similarity_score": round(total_stats["avg_score"], 3)
                if total_stats and total_stats["avg_score"]
                else 0,
                "avg_top_score": round(total_stats["avg_top_score"], 3)
                if total_stats and total_stats["avg_top_score"]
                else 0,
                "avg_response_time_ms": round(total_stats["avg_response_time"], 1)
                if total_stats and total_stats["avg_response_time"]
                else 0,
                "zero_result_rate": round(zero_result_rate, 2),
                "low_score_rate": round(low_score_rate, 2),
            },
            "by_source": [
                {
                    "source": row["source"],
                    "count": row["count"],
                    "avg_results": round(row["avg_results"], 2),
                    "avg_response_time_ms": round(row["avg_response_time"], 1),
                }
                for row in mode_stats
            ],
            "trend": [
                {
                    "hour": row["hour"],
                    "search_count": row["search_count"],
                    "avg_results": round(row["avg_results"], 2),
                    "avg_score": round(row["avg_score"], 3) if row["avg_score"] else 0,
                }
                for row in trend_stats
            ],
            "popular_queries": [
                {
                    "query": row["query"],
                    "count": row["count"],
                    "avg_results": round(row["avg_results"], 2),
                }
                for row in popular_queries
            ]
            if not self.hash_queries
            else [],
        }

    async def get_project_search_stats(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        프로젝트별 검색 통계 조회

        Args:
            hours: 조회 기간 (시간)

        Returns:
            프로젝트별 검색 통계 리스트
        """
        from datetime import timedelta

        start_time = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"

        stats = await self.database.fetchall(
            """
            SELECT 
                project_id,
                COUNT(*) as search_count,
                AVG(result_count) as avg_results,
                AVG(avg_similarity_score) as avg_score,
                AVG(response_time_ms) as avg_response_time,
                SUM(CASE WHEN result_count = 0 THEN 1 ELSE 0 END) as zero_result_count
            FROM search_metrics
            WHERE timestamp >= ? 
              AND project_id IS NOT NULL
              AND query IS NOT NULL 
              AND query != ''
            GROUP BY project_id
            ORDER BY search_count DESC
        """,
            (start_time,),
        )

        return [
            {
                "project_id": row["project_id"],
                "search_count": row["search_count"],
                "avg_results": round(row["avg_results"], 2),
                "avg_score": round(row["avg_score"], 3) if row["avg_score"] else 0,
                "avg_response_time_ms": round(row["avg_response_time"], 1),
                "zero_result_rate": round(
                    row["zero_result_count"] / row["search_count"] * 100, 2
                )
                if row["search_count"] > 0
                else 0,
            }
            for row in stats
        ]

    async def get_cache_performance_stats(self, hours: int = 24) -> Dict[str, Any]:
        """
        캐시 성능 통계 조회

        Args:
            hours: 조회 기간 (시간)

        Returns:
            캐시 성능 통계
        """
        from datetime import timedelta

        start_time = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"

        try:
            # 임베딩 캐시 통계
            embedding_stats = await self.database.fetchone(
                """
                SELECT 
                    COUNT(*) as total_operations,
                    SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) as cache_hits,
                    AVG(total_time_ms) as avg_time_ms
                FROM embedding_metrics
                WHERE timestamp >= ?
            """,
                (start_time,),
            )

            total_ops = (
                embedding_stats["total_operations"]
                if embedding_stats and embedding_stats["total_operations"]
                else 0
            )
            cache_hits = (
                embedding_stats["cache_hits"]
                if embedding_stats and embedding_stats["cache_hits"]
                else 0
            )
            avg_time = (
                embedding_stats["avg_time_ms"]
                if embedding_stats and embedding_stats["avg_time_ms"]
                else 0
            )

        except Exception as e:
            # 테이블이 없거나 에러 발생 시 기본값 반환
            logger.warning(f"Failed to fetch embedding metrics: {e}")
            total_ops = 0
            cache_hits = 0
            avg_time = 0

        hit_rate = (cache_hits / total_ops * 100) if total_ops > 0 else 0

        return {
            "period": {
                "hours": hours,
                "start_time": start_time,
                "end_time": datetime.utcnow().isoformat() + "Z",
            },
            "embedding_cache": {
                "total_operations": total_ops,
                "cache_hits": cache_hits,
                "cache_misses": total_ops - cache_hits,
                "hit_rate": round(hit_rate, 2),
                "avg_time_ms": round(avg_time, 1) if avg_time else 0,
            },
        }
