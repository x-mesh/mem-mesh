"""모니터링 서비스

검색 및 임베딩 메트릭을 집계하고 분석합니다.
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Literal

from app.core.database.base import Database
from app.core.utils.logger import get_logger

logger = get_logger(__name__)


class MonitoringService:
    """메트릭 집계 및 분석 서비스"""
    
    def __init__(self, database: Database):
        self.database = database
    
    async def get_search_metrics(
        self,
        start_date: datetime,
        end_date: datetime,
        project_id: Optional[str] = None,
        aggregation: Literal["hourly", "daily"] = "hourly"
    ) -> Dict[str, Any]:
        """
        검색 메트릭 집계
        
        Args:
            start_date: 시작 날짜
            end_date: 종료 날짜
            project_id: 프로젝트 ID (선택)
            aggregation: 집계 단위 ('hourly' 또는 'daily')
        
        Returns:
            집계된 검색 메트릭
        """
        # 날짜 포맷 결정
        if aggregation == "hourly":
            date_format = "%Y-%m-%d %H:00:00"
            group_by = "strftime('%Y-%m-%d %H:00:00', timestamp)"
        else:
            date_format = "%Y-%m-%d"
            group_by = "strftime('%Y-%m-%d', timestamp)"
        
        # 기본 조건 (빈 쿼리 제외)
        conditions = [
            "timestamp >= ? AND timestamp <= ?",
            "query IS NOT NULL",
            "query != ''"
        ]
        params: List[Any] = [start_date.isoformat(), end_date.isoformat()]
        
        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)
        
        where_clause = " AND ".join(conditions)
        
        # 시계열 데이터 조회
        timeseries_query = f"""
            SELECT 
                {group_by} as period,
                COUNT(*) as total_searches,
                AVG(avg_similarity_score) as avg_similarity,
                AVG(response_time_ms) as avg_response_time,
                SUM(CASE WHEN result_count = 0 THEN 1 ELSE 0 END) as no_results_count,
                AVG(result_count) as avg_result_count
            FROM search_metrics
            WHERE {where_clause}
            GROUP BY {group_by}
            ORDER BY period
        """
        
        timeseries = await self.database.fetchall(timeseries_query, tuple(params))
        
        # 전체 요약 통계
        summary_query = f"""
            SELECT 
                COUNT(*) as total_searches,
                AVG(avg_similarity_score) as avg_similarity,
                MAX(avg_similarity_score) as max_similarity,
                MIN(avg_similarity_score) as min_similarity,
                AVG(response_time_ms) as avg_response_time,
                MAX(response_time_ms) as max_response_time,
                MIN(response_time_ms) as min_response_time,
                SUM(CASE WHEN result_count = 0 THEN 1 ELSE 0 END) as no_results_count,
                AVG(result_count) as avg_result_count
            FROM search_metrics
            WHERE {where_clause}
        """
        
        summary = await self.database.fetchone(summary_query, tuple(params))
        
        # 결과 없음 비율 계산
        total = summary["total_searches"] if summary["total_searches"] else 0
        no_results = summary["no_results_count"] if summary["no_results_count"] else 0
        no_results_rate = (no_results / total * 100) if total > 0 else 0
        
        return {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "aggregation": aggregation
            },
            "summary": {
                "total_searches": total,
                "avg_similarity": round(summary["avg_similarity"] or 0, 4),
                "max_similarity": round(summary["max_similarity"] or 0, 4),
                "min_similarity": round(summary["min_similarity"] or 0, 4),
                "avg_response_time_ms": round(summary["avg_response_time"] or 0, 2),
                "max_response_time_ms": summary["max_response_time"] or 0,
                "min_response_time_ms": summary["min_response_time"] or 0,
                "no_results_count": no_results,
                "no_results_rate": round(no_results_rate, 2),
                "avg_result_count": round(summary["avg_result_count"] or 0, 2)
            },
            "timeseries": [
                {
                    "period": row["period"],
                    "total_searches": row["total_searches"],
                    "avg_similarity": round(row["avg_similarity"] or 0, 4),
                    "avg_response_time_ms": round(row["avg_response_time"] or 0, 2),
                    "no_results_count": row["no_results_count"],
                    "no_results_rate": round(
                        (row["no_results_count"] / row["total_searches"] * 100) 
                        if row["total_searches"] > 0 else 0, 2
                    )
                }
                for row in timeseries
            ]
        }
    
    async def get_query_analysis(
        self,
        limit: int = 100,
        sort_by: Literal["frequency", "similarity", "time"] = "frequency",
        days: int = 7
    ) -> Dict[str, Any]:
        """
        쿼리 분석
        
        Args:
            limit: 최대 결과 수
            sort_by: 정렬 기준 ('frequency', 'similarity', 'time')
            days: 분석 기간 (일)
        
        Returns:
            쿼리 분석 결과
        """
        cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
        
        # 정렬 기준 결정
        order_by = {
            "frequency": "search_count DESC",
            "similarity": "avg_similarity ASC",  # 낮은 유사도 우선
            "time": "avg_response_time DESC"  # 느린 응답 우선
        }.get(sort_by, "search_count DESC")
        
        # 빈 쿼리 제외 조건
        non_empty_query = "query IS NOT NULL AND query != ''"
        
        # 쿼리별 통계
        query_stats = await self.database.fetchall(f"""
            SELECT 
                query,
                COUNT(*) as search_count,
                AVG(avg_similarity_score) as avg_similarity,
                AVG(response_time_ms) as avg_response_time,
                AVG(result_count) as avg_result_count,
                SUM(CASE WHEN result_count = 0 THEN 1 ELSE 0 END) as no_results_count
            FROM search_metrics
            WHERE timestamp >= ? AND {non_empty_query}
            GROUP BY query
            ORDER BY {order_by}
            LIMIT ?
        """, (cutoff_date, limit))
        
        # Top 10 빈도 쿼리
        top_queries = await self.database.fetchall(f"""
            SELECT query, COUNT(*) as count
            FROM search_metrics
            WHERE timestamp >= ? AND {non_empty_query}
            GROUP BY query
            ORDER BY count DESC
            LIMIT 10
        """, (cutoff_date,))
        
        # 낮은 유사도 쿼리 Top 10
        low_similarity_queries = await self.database.fetchall(f"""
            SELECT query, AVG(avg_similarity_score) as avg_similarity, COUNT(*) as count
            FROM search_metrics
            WHERE timestamp >= ? AND avg_similarity_score IS NOT NULL AND {non_empty_query}
            GROUP BY query
            HAVING count >= 2
            ORDER BY avg_similarity ASC
            LIMIT 10
        """, (cutoff_date,))
        
        # 결과 없음 쿼리
        no_results_queries = await self.database.fetchall(f"""
            SELECT query, COUNT(*) as count
            FROM search_metrics
            WHERE timestamp >= ? AND result_count = 0 AND {non_empty_query}
            GROUP BY query
            ORDER BY count DESC
            LIMIT 20
        """, (cutoff_date,))
        
        # 쿼리 길이 분포
        length_distribution = await self.database.fetchall(f"""
            SELECT 
                CASE 
                    WHEN query_length <= 20 THEN 'short'
                    WHEN query_length <= 50 THEN 'medium'
                    ELSE 'long'
                END as length_category,
                COUNT(*) as count,
                AVG(avg_similarity_score) as avg_similarity
            FROM search_metrics
            WHERE timestamp >= ? AND {non_empty_query}
            GROUP BY length_category
        """, (cutoff_date,))
        
        return {
            "period_days": days,
            "queries": [
                {
                    "query": row["query"],
                    "search_count": row["search_count"],
                    "avg_similarity": round(row["avg_similarity"] or 0, 4),
                    "avg_response_time_ms": round(row["avg_response_time"] or 0, 2),
                    "avg_result_count": round(row["avg_result_count"] or 0, 2),
                    "no_results_count": row["no_results_count"]
                }
                for row in query_stats
            ],
            "top_queries": [
                {"query": row["query"], "count": row["count"]}
                for row in top_queries
            ],
            "low_similarity_queries": [
                {
                    "query": row["query"],
                    "avg_similarity": round(row["avg_similarity"] or 0, 4),
                    "count": row["count"]
                }
                for row in low_similarity_queries
            ],
            "no_results_queries": [
                {"query": row["query"], "count": row["count"]}
                for row in no_results_queries
            ],
            "length_distribution": {
                row["length_category"]: {
                    "count": row["count"],
                    "avg_similarity": round(row["avg_similarity"] or 0, 4)
                }
                for row in length_distribution
            }
        }
    
    async def get_embedding_metrics(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """
        임베딩 메트릭 집계
        
        Args:
            start_date: 시작 날짜
            end_date: 종료 날짜
        
        Returns:
            임베딩 성능 메트릭
        """
        # 전체 요약
        summary = await self.database.fetchone("""
            SELECT 
                COUNT(*) as total_operations,
                SUM(count) as total_embeddings,
                AVG(total_time_ms) as avg_total_time,
                AVG(avg_time_per_embedding_ms) as avg_time_per_embedding,
                SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) as cache_hits,
                AVG(memory_usage_mb) as avg_memory_usage
            FROM embedding_metrics
            WHERE timestamp >= ? AND timestamp <= ?
        """, (start_date.isoformat(), end_date.isoformat()))
        
        # 작업 유형별 통계
        by_operation = await self.database.fetchall("""
            SELECT 
                operation,
                COUNT(*) as count,
                SUM(count) as total_embeddings,
                AVG(total_time_ms) as avg_time,
                AVG(avg_time_per_embedding_ms) as avg_time_per_embedding
            FROM embedding_metrics
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY operation
        """, (start_date.isoformat(), end_date.isoformat()))
        
        # 시계열 데이터 (시간별)
        timeseries = await self.database.fetchall("""
            SELECT 
                strftime('%Y-%m-%d %H:00:00', timestamp) as period,
                COUNT(*) as operations,
                SUM(count) as embeddings,
                AVG(avg_time_per_embedding_ms) as avg_time
            FROM embedding_metrics
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY strftime('%Y-%m-%d %H:00:00', timestamp)
            ORDER BY period
        """, (start_date.isoformat(), end_date.isoformat()))
        
        # 캐시 히트율 계산
        total_ops = summary["total_operations"] if summary["total_operations"] else 0
        cache_hits = summary["cache_hits"] if summary["cache_hits"] else 0
        cache_hit_rate = (cache_hits / total_ops * 100) if total_ops > 0 else 0
        
        return {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "summary": {
                "total_operations": total_ops,
                "total_embeddings": summary["total_embeddings"] or 0,
                "avg_total_time_ms": round(summary["avg_total_time"] or 0, 2),
                "avg_time_per_embedding_ms": round(summary["avg_time_per_embedding"] or 0, 2),
                "cache_hits": cache_hits,
                "cache_hit_rate": round(cache_hit_rate, 2),
                "avg_memory_usage_mb": round(summary["avg_memory_usage"] or 0, 2)
            },
            "by_operation": [
                {
                    "operation": row["operation"],
                    "count": row["count"],
                    "total_embeddings": row["total_embeddings"],
                    "avg_time_ms": round(row["avg_time"] or 0, 2),
                    "avg_time_per_embedding_ms": round(row["avg_time_per_embedding"] or 0, 2)
                }
                for row in by_operation
            ],
            "timeseries": [
                {
                    "period": row["period"],
                    "operations": row["operations"],
                    "embeddings": row["embeddings"],
                    "avg_time_ms": round(row["avg_time"] or 0, 2)
                }
                for row in timeseries
            ]
        }
    
    async def get_recent_searches(
        self,
        limit: int = 50,
        project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        최근 검색 목록 조회
        
        Args:
            limit: 최대 결과 수
            project_id: 프로젝트 ID (선택)
        
        Returns:
            최근 검색 목록
        """
        if project_id:
            rows = await self.database.fetchall("""
                SELECT * FROM search_metrics
                WHERE project_id = ? 
                  AND query IS NOT NULL 
                  AND query != ''
                ORDER BY timestamp DESC
                LIMIT ?
            """, (project_id, limit))
        else:
            rows = await self.database.fetchall("""
                SELECT * FROM search_metrics
                WHERE query IS NOT NULL 
                  AND query != ''
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
        
        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "query": row["query"],
                "query_length": row["query_length"],
                "project_id": row["project_id"],
                "result_count": row["result_count"],
                "avg_similarity_score": row["avg_similarity_score"],
                "response_time_ms": row["response_time_ms"],
                "source": row["source"]
            }
            for row in rows
        ]
    
    async def get_dashboard_summary(self) -> Dict[str, Any]:
        """
        대시보드 요약 정보
        
        Returns:
            대시보드 요약 데이터
        """
        now = datetime.utcnow()
        last_24h = (now - timedelta(hours=24)).isoformat()
        last_7d = (now - timedelta(days=7)).isoformat()
        
        # 최근 24시간 검색 통계
        search_24h = await self.database.fetchone("""
            SELECT 
                COUNT(*) as total,
                AVG(avg_similarity_score) as avg_similarity,
                AVG(response_time_ms) as avg_response_time,
                SUM(CASE WHEN result_count = 0 THEN 1 ELSE 0 END) as no_results
            FROM search_metrics
            WHERE timestamp >= ?
        """, (last_24h,))
        
        # 최근 7일 검색 통계
        search_7d = await self.database.fetchone("""
            SELECT 
                COUNT(*) as total,
                AVG(avg_similarity_score) as avg_similarity
            FROM search_metrics
            WHERE timestamp >= ?
        """, (last_7d,))
        
        # 최근 24시간 임베딩 통계
        embedding_24h = await self.database.fetchone("""
            SELECT 
                COUNT(*) as total_operations,
                SUM(count) as total_embeddings,
                AVG(avg_time_per_embedding_ms) as avg_time
            FROM embedding_metrics
            WHERE timestamp >= ?
        """, (last_24h,))
        
        # 활성 알림 수
        active_alerts = await self.database.fetchone("""
            SELECT COUNT(*) as count
            FROM alerts
            WHERE status = 'active'
        """)
        
        total_24h = search_24h["total"] if search_24h["total"] else 0
        no_results_24h = search_24h["no_results"] if search_24h["no_results"] else 0
        
        return {
            "search": {
                "last_24h": {
                    "total": total_24h,
                    "avg_similarity": round(search_24h["avg_similarity"] or 0, 4),
                    "avg_response_time_ms": round(search_24h["avg_response_time"] or 0, 2),
                    "no_results_rate": round(
                        (no_results_24h / total_24h * 100) if total_24h > 0 else 0, 2
                    )
                },
                "last_7d": {
                    "total": search_7d["total"] or 0,
                    "avg_similarity": round(search_7d["avg_similarity"] or 0, 4)
                }
            },
            "embedding": {
                "last_24h": {
                    "total_operations": embedding_24h["total_operations"] or 0,
                    "total_embeddings": embedding_24h["total_embeddings"] or 0,
                    "avg_time_per_embedding_ms": round(embedding_24h["avg_time"] or 0, 2)
                }
            },
            "alerts": {
                "active_count": active_alerts["count"] if active_alerts else 0
            },
            "generated_at": now.isoformat() + "Z"
        }
