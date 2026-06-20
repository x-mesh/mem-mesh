"""
Statistics service for mem-mesh.

This module provides statistics and analytics for stored memories,
including counts by project, category, source, and date ranges.
"""

import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from ..database.base import Database

logger = logging.getLogger(__name__)


class StatsService:
    """메모리 통계 서비스"""

    def __init__(self, db: Database):
        self.db = db

    async def get_overall_stats(
        self,
        project_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        전체 통계 조회

        Args:
            project_id: 특정 프로젝트로 필터링 (선택사항)
            start_date: 시작 날짜 (YYYY-MM-DD 형식, 선택사항)
            end_date: 종료 날짜 (YYYY-MM-DD 형식, 선택사항)

        Returns:
            통계 정보 딕셔너리
        """
        start_time = time.time()

        try:
            # Build base filter conditions
            where_conditions = []
            params = []

            if project_id:
                where_conditions.append("project_id = ?")
                params.append(project_id)

            if start_date:
                where_conditions.append("created_at >= ?")
                params.append(f"{start_date}T00:00:00Z")

            if end_date:
                where_conditions.append("created_at <= ?")
                params.append(f"{end_date}T23:59:59Z")

            where_clause = ""
            if where_conditions:
                where_clause = "WHERE " + " AND ".join(where_conditions)

            # Query total memory count
            total_query = f"SELECT COUNT(*) as total FROM memories {where_clause}"
            total_result = await self.db.fetchone(total_query, tuple(params))
            total_memories = total_result["total"] if total_result else 0

            # Query unique project count
            unique_projects_query = f"""
                SELECT COUNT(DISTINCT project_id) as unique_projects 
                FROM memories 
                {where_clause}
            """
            unique_result = await self.db.fetchone(unique_projects_query, tuple(params))
            unique_projects = unique_result["unique_projects"] if unique_result else 0

            # Distribution by category
            categories_breakdown = await self.get_category_stats(
                project_id, start_date, end_date
            )

            # Distribution by source
            sources_breakdown = await self.get_source_stats(
                project_id, start_date, end_date
            )

            # Distribution by client tool
            clients_breakdown = await self.get_client_stats(
                project_id, start_date, end_date
            )

            # Distribution by project (only when no project_id filter)
            projects_breakdown = {}
            if not project_id:
                projects_breakdown = await self.get_project_stats(
                    None, start_date, end_date
                )

            # Date range info
            date_range = None
            if start_date or end_date:
                date_range = {}
                if start_date:
                    date_range["start"] = start_date
                if end_date:
                    date_range["end"] = end_date

            query_time_ms = (time.time() - start_time) * 1000

            return {
                "total_memories": total_memories,
                "unique_projects": unique_projects,
                "categories_breakdown": categories_breakdown,
                "sources_breakdown": sources_breakdown,
                "projects_breakdown": projects_breakdown,
                "clients_breakdown": clients_breakdown,
                "date_range": date_range,
                "query_time_ms": round(query_time_ms, 2),
            }

        except Exception as e:
            logger.error(f"Failed to get overall stats: {e}")
            raise

    async def get_project_stats(
        self,
        project_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, int]:
        """프로젝트별 메모리 수 조회"""
        try:
            where_conditions = []
            params = []

            if project_id:
                where_conditions.append("project_id = ?")
                params.append(project_id)

            if start_date:
                where_conditions.append("created_at >= ?")
                params.append(f"{start_date}T00:00:00Z")

            if end_date:
                where_conditions.append("created_at <= ?")
                params.append(f"{end_date}T23:59:59Z")

            where_clause = ""
            if where_conditions:
                where_clause = "WHERE " + " AND ".join(where_conditions)

            query = f"""
                SELECT 
                    COALESCE(project_id, 'global') as project_name,
                    COUNT(*) as count
                FROM memories 
                {where_clause}
                GROUP BY project_id
                ORDER BY count DESC
            """

            results = await self.db.fetchall(query, tuple(params))

            return {row["project_name"]: row["count"] for row in results}

        except Exception as e:
            logger.error(f"Failed to get project stats: {e}")
            raise

    async def get_category_stats(
        self,
        project_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, int]:
        """카테고리별 메모리 수 조회"""
        try:
            where_conditions = []
            params = []

            if project_id:
                where_conditions.append("project_id = ?")
                params.append(project_id)

            if start_date:
                where_conditions.append("created_at >= ?")
                params.append(f"{start_date}T00:00:00Z")

            if end_date:
                where_conditions.append("created_at <= ?")
                params.append(f"{end_date}T23:59:59Z")

            where_clause = ""
            if where_conditions:
                where_clause = "WHERE " + " AND ".join(where_conditions)

            query = f"""
                SELECT 
                    category,
                    COUNT(*) as count
                FROM memories 
                {where_clause}
                GROUP BY category
                ORDER BY count DESC
            """

            results = await self.db.fetchall(query, tuple(params))

            return {row["category"]: row["count"] for row in results}

        except Exception as e:
            logger.error(f"Failed to get category stats: {e}")
            raise

    async def get_source_stats(
        self,
        project_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, int]:
        """소스별 메모리 수 조회"""
        try:
            where_conditions = []
            params = []

            if project_id:
                where_conditions.append("project_id = ?")
                params.append(project_id)

            if start_date:
                where_conditions.append("created_at >= ?")
                params.append(f"{start_date}T00:00:00Z")

            if end_date:
                where_conditions.append("created_at <= ?")
                params.append(f"{end_date}T23:59:59Z")

            where_clause = ""
            if where_conditions:
                where_clause = "WHERE " + " AND ".join(where_conditions)

            query = f"""
                SELECT 
                    source,
                    COUNT(*) as count
                FROM memories 
                {where_clause}
                GROUP BY source
                ORDER BY count DESC
            """

            results = await self.db.fetchall(query, tuple(params))

            return {row["source"]: row["count"] for row in results}

        except Exception as e:
            logger.error(f"Failed to get source stats: {e}")
            raise

    async def get_client_stats(
        self,
        project_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, int]:
        """클라이언트 도구별 메모리 수 조회"""
        try:
            where_conditions: list[str] = []
            params: list[str] = []

            if project_id:
                where_conditions.append("project_id = ?")
                params.append(project_id)

            if start_date:
                where_conditions.append("created_at >= ?")
                params.append(f"{start_date}T00:00:00Z")

            if end_date:
                where_conditions.append("created_at <= ?")
                params.append(f"{end_date}T23:59:59Z")

            where_clause = ""
            if where_conditions:
                where_clause = "WHERE " + " AND ".join(where_conditions)

            query = f"""
                SELECT
                    COALESCE(client, 'unknown') as client_name,
                    COUNT(*) as count
                FROM memories
                {where_clause}
                GROUP BY client
                ORDER BY count DESC
            """

            results = await self.db.fetchall(query, tuple(params))

            return {row["client_name"]: row["count"] for row in results}

        except Exception as e:
            logger.error(f"Failed to get client stats: {e}")
            raise

    async def get_date_range_stats(
        self, start_date: str, end_date: str, project_id: Optional[str] = None
    ) -> Dict[str, int]:
        """날짜 범위별 메모리 수 조회 (일별 분포)"""
        try:
            where_conditions = ["created_at >= ?", "created_at <= ?"]
            params = [f"{start_date}T00:00:00Z", f"{end_date}T23:59:59Z"]

            if project_id:
                where_conditions.append("project_id = ?")
                params.append(project_id)

            where_clause = "WHERE " + " AND ".join(where_conditions)

            query = f"""
                SELECT 
                    DATE(created_at) as date,
                    COUNT(*) as count
                FROM memories 
                {where_clause}
                GROUP BY DATE(created_at)
                ORDER BY date
            """

            results = await self.db.fetchall(query, tuple(params))

            return {row["date"]: row["count"] for row in results}

        except Exception as e:
            logger.error(f"Failed to get date range stats: {e}")
            raise

    async def get_projects_detail(self) -> List[Dict[str, Any]]:
        """
        프로젝트별 상세 정보 조회 (서버에서 집계)

        Returns:
            프로젝트별 상세 통계 리스트
        """
        try:
            # Basic statistics per project
            query = """
                SELECT
                    COALESCE(project_id, 'default') as project_id,
                    COUNT(*) as memory_count,
                    SUM(content_bytes) as total_size,
                    MIN(created_at) as created_at,
                    MAX(created_at) as updated_at
                FROM memories
                GROUP BY COALESCE(project_id, 'default')
                ORDER BY memory_count DESC
            """

            projects = await self.db.fetchall(query, ())

            # Categories per project — one grouped query for all projects.
            # (was N+1: a DISTINCT-category query per project, each a full scan
            # because WHERE COALESCE(project_id,'default')=? can't use an index)
            cat_rows = await self.db.fetchall(
                """
                SELECT COALESCE(project_id, 'default') AS pid, category
                FROM memories
                GROUP BY pid, category
                """,
                (),
            )
            cats_by_pid: Dict[str, List[str]] = defaultdict(list)
            for row in cat_rows:
                cats_by_pid[row["pid"]].append(row["category"])

            # Tags per project — one grouped query for all projects.
            # (was N+1: a json_each + full-scan query per project)
            tag_rows = await self.db.fetchall(
                """
                SELECT COALESCE(m.project_id, 'default') AS pid, je.value AS tag
                FROM memories m,
                     json_each(CASE
                         WHEN m.tags IS NULL OR m.tags = '' THEN '[]'
                         ELSE m.tags
                     END) je
                GROUP BY pid, je.value
                """,
                (),
            )
            tags_by_pid: Dict[str, List[str]] = defaultdict(list)
            for row in tag_rows:
                tags_by_pid[row["pid"]].append(row["tag"])

            result = []
            for project in projects:
                pid = project["project_id"]
                result.append(
                    {
                        "id": pid,
                        "name": "Default Project" if pid == "default" else pid,
                        "memory_count": project["memory_count"],
                        "total_size": project["total_size"] or 0,
                        "avg_memory_size": (
                            (project["total_size"] or 0) // project["memory_count"]
                            if project["memory_count"] > 0
                            else 0
                        ),
                        "categories": cats_by_pid.get(pid, []),
                        "tags": tags_by_pid.get(pid, []),
                        "created_at": project["created_at"],
                        "updated_at": project["updated_at"],
                    }
                )

            return result

        except Exception as e:
            logger.error(f"Failed to get projects detail: {e}")
            raise

    # ===== Work Tracking System Statistics =====

    async def get_pin_stats(
        self, project_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Pin 관련 통계 조회

        Args:
            project_id: 프로젝트 필터
            user_id: 사용자 필터

        Returns:
            Pin 통계 딕셔너리
        """
        try:
            where_conditions = []
            params = []

            if project_id:
                where_conditions.append("project_id = ?")
                params.append(project_id)

            if user_id:
                where_conditions.append("user_id = ?")
                params.append(user_id)

            where_clause = ""
            if where_conditions:
                where_clause = "WHERE " + " AND ".join(where_conditions)

            # Pin count by status
            status_query = f"""
                SELECT 
                    status,
                    COUNT(*) as count
                FROM pins
                {where_clause}
                GROUP BY status
            """
            status_results = await self.db.fetchall(status_query, tuple(params))
            status_breakdown = {row["status"]: row["count"] for row in status_results}

            # Total pin count
            total_pins = sum(status_breakdown.values())

            # Average lead time (completed pins only)
            lead_time_query = f"""
                SELECT 
                    AVG((julianday(completed_at) - julianday(created_at)) * 24) as avg_lead_time_hours,
                    MIN((julianday(completed_at) - julianday(created_at)) * 24) as min_lead_time_hours,
                    MAX((julianday(completed_at) - julianday(created_at)) * 24) as max_lead_time_hours,
                    COUNT(*) as completed_count
                FROM pins
                {where_clause + ' AND ' if where_clause else 'WHERE '}
                status = 'completed' AND completed_at IS NOT NULL
            """
            lead_time_result = await self.db.fetchone(lead_time_query, tuple(params))

            avg_lead_time = (
                lead_time_result["avg_lead_time_hours"] if lead_time_result else None
            )
            min_lead_time = (
                lead_time_result["min_lead_time_hours"] if lead_time_result else None
            )
            max_lead_time = (
                lead_time_result["max_lead_time_hours"] if lead_time_result else None
            )
            lead_time_result["completed_count"] if lead_time_result else 0

            # Distribution by importance
            importance_query = f"""
                SELECT 
                    importance,
                    COUNT(*) as count
                FROM pins
                {where_clause}
                GROUP BY importance
                ORDER BY importance DESC
            """
            importance_results = await self.db.fetchall(importance_query, tuple(params))
            importance_breakdown = {
                row["importance"]: row["count"] for row in importance_results
            }

            return {
                "total_pins": total_pins,
                "status_breakdown": status_breakdown,
                "open_pins": status_breakdown.get("open", 0),
                "in_progress_pins": status_breakdown.get("in_progress", 0),
                "completed_pins": status_breakdown.get("completed", 0),
                "avg_lead_time_hours": (
                    round(avg_lead_time, 2) if avg_lead_time else None
                ),
                "min_lead_time_hours": (
                    round(min_lead_time, 2) if min_lead_time else None
                ),
                "max_lead_time_hours": (
                    round(max_lead_time, 2) if max_lead_time else None
                ),
                "importance_breakdown": importance_breakdown,
            }

        except Exception as e:
            logger.error(f"Failed to get pin stats: {e}")
            raise

    async def get_daily_pin_completions(
        self, project_id: Optional[str] = None, days: int = 7
    ) -> List[Dict[str, Any]]:
        """
        일별 Pin 완료 수 조회

        Args:
            project_id: 프로젝트 필터
            days: 조회할 일수 (기본 7일)

        Returns:
            일별 완료 수 리스트
        """
        try:
            where_conditions = ["status = 'completed'", "completed_at IS NOT NULL"]
            params = []

            if project_id:
                where_conditions.append("project_id = ?")
                params.append(project_id)

            where_clause = "WHERE " + " AND ".join(where_conditions)

            query = f"""
                SELECT 
                    DATE(completed_at) as date,
                    COUNT(*) as count,
                    AVG((julianday(completed_at) - julianday(created_at)) * 24) as avg_lead_time
                FROM pins
                {where_clause}
                AND DATE(completed_at) >= DATE('now', '-{days} days')
                GROUP BY DATE(completed_at)
                ORDER BY date DESC
            """

            results = await self.db.fetchall(query, tuple(params))

            return [
                {
                    "date": row["date"],
                    "completed_count": row["count"],
                    "avg_lead_time_hours": (
                        round(row["avg_lead_time"], 2) if row["avg_lead_time"] else None
                    ),
                }
                for row in results
            ]

        except Exception as e:
            logger.error(f"Failed to get daily pin completions: {e}")
            raise

    async def get_weekly_pin_completions(
        self, project_id: Optional[str] = None, weeks: int = 4
    ) -> List[Dict[str, Any]]:
        """
        주별 Pin 완료 수 조회

        Args:
            project_id: 프로젝트 필터
            weeks: 조회할 주 수 (기본 4주)

        Returns:
            주별 완료 수 리스트
        """
        try:
            where_conditions = ["status = 'completed'", "completed_at IS NOT NULL"]
            params = []

            if project_id:
                where_conditions.append("project_id = ?")
                params.append(project_id)

            where_clause = "WHERE " + " AND ".join(where_conditions)

            query = f"""
                SELECT 
                    strftime('%Y-W%W', completed_at) as week,
                    COUNT(*) as count,
                    AVG((julianday(completed_at) - julianday(created_at)) * 24) as avg_lead_time
                FROM pins
                {where_clause}
                AND DATE(completed_at) >= DATE('now', '-{weeks * 7} days')
                GROUP BY strftime('%Y-W%W', completed_at)
                ORDER BY week DESC
            """

            results = await self.db.fetchall(query, tuple(params))

            return [
                {
                    "week": row["week"],
                    "completed_count": row["count"],
                    "avg_lead_time_hours": (
                        round(row["avg_lead_time"], 2) if row["avg_lead_time"] else None
                    ),
                }
                for row in results
            ]

        except Exception as e:
            logger.error(f"Failed to get weekly pin completions: {e}")
            raise

    async def get_session_stats(
        self, project_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Session 관련 통계 조회

        Args:
            project_id: 프로젝트 필터
            user_id: 사용자 필터

        Returns:
            Session 통계 딕셔너리
        """
        try:
            where_conditions = []
            params = []

            if project_id:
                where_conditions.append("project_id = ?")
                params.append(project_id)

            if user_id:
                where_conditions.append("user_id = ?")
                params.append(user_id)

            where_clause = ""
            if where_conditions:
                where_clause = "WHERE " + " AND ".join(where_conditions)

            # Session count by status
            status_query = f"""
                SELECT 
                    status,
                    COUNT(*) as count
                FROM sessions
                {where_clause}
                GROUP BY status
            """
            status_results = await self.db.fetchall(status_query, tuple(params))
            status_breakdown = {row["status"]: row["count"] for row in status_results}

            # Total session count
            total_sessions = sum(status_breakdown.values())

            # Average session duration (completed sessions only)
            duration_query = f"""
                SELECT 
                    AVG((julianday(ended_at) - julianday(started_at)) * 24) as avg_duration_hours
                FROM sessions
                {where_clause + ' AND ' if where_clause else 'WHERE '}
                status = 'completed' AND ended_at IS NOT NULL
            """
            duration_result = await self.db.fetchone(duration_query, tuple(params))
            avg_duration = (
                duration_result["avg_duration_hours"] if duration_result else None
            )

            return {
                "total_sessions": total_sessions,
                "status_breakdown": status_breakdown,
                "active_sessions": status_breakdown.get("active", 0),
                "paused_sessions": status_breakdown.get("paused", 0),
                "completed_sessions": status_breakdown.get("completed", 0),
                "avg_session_duration_hours": (
                    round(avg_duration, 2) if avg_duration else None
                ),
            }

        except Exception as e:
            logger.error(f"Failed to get session stats: {e}")
            raise

    # ===== Analytics Extensions (token economics / KB health / recall / trend) =====

    @staticmethod
    def _memory_filters(
        project_id: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str],
        *,
        date_col: str = "created_at",
        use_date_fn: bool = False,
    ) -> tuple[str, list]:
        """Build a WHERE clause + params for project/date filtering.

        use_date_fn wraps the date column in DATE() and compares against plain
        YYYY-MM-DD strings — robust to ISO 'T'/'Z' vs space-separated storage
        (token_usage). The created_at form keeps the indexable comparison used
        by the memories table elsewhere.
        """
        conds: list[str] = []
        params: list = []
        if project_id:
            conds.append("project_id = ?")
            params.append(project_id)
        if start_date:
            if use_date_fn:
                conds.append(f"DATE({date_col}) >= ?")
                params.append(start_date)
            else:
                conds.append(f"{date_col} >= ?")
                params.append(f"{start_date}T00:00:00Z")
        if end_date:
            if use_date_fn:
                conds.append(f"DATE({date_col}) <= ?")
                params.append(end_date)
            else:
                conds.append(f"{date_col} <= ?")
                params.append(f"{end_date}T23:59:59Z")
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        return where, params

    async def get_token_economics(
        self,
        project_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """토큰 절약 이코노믹스 (token_usage 집계).

        mem-mesh 핵심 가치 제안(컨텍스트 토큰 절감)을 수치화한다.
        """
        try:
            where, params = self._memory_filters(
                project_id, start_date, end_date, use_date_fn=True
            )

            totals_row = await self.db.fetchone(
                f"""
                SELECT
                    COALESCE(SUM(tokens_used), 0)   AS tokens_used,
                    COALESCE(SUM(tokens_saved), 0)  AS tokens_saved,
                    COUNT(*)                        AS operations,
                    COALESCE(SUM(optimization_applied), 0) AS optimized_ops
                FROM token_usage {where}
                """,
                tuple(params),
            )
            tokens_used = totals_row["tokens_used"] if totals_row else 0
            tokens_saved = totals_row["tokens_saved"] if totals_row else 0
            operations = totals_row["operations"] if totals_row else 0
            optimized_ops = totals_row["optimized_ops"] if totals_row else 0

            by_op_rows = await self.db.fetchall(
                f"""
                SELECT
                    operation_type,
                    COALESCE(SUM(tokens_used), 0)  AS tokens_used,
                    COALESCE(SUM(tokens_saved), 0) AS tokens_saved,
                    COUNT(*)                       AS operations
                FROM token_usage {where}
                GROUP BY operation_type
                ORDER BY tokens_saved DESC
                """,
                tuple(params),
            )

            daily_rows = await self.db.fetchall(
                f"""
                SELECT
                    DATE(created_at)               AS date,
                    COALESCE(SUM(tokens_saved), 0) AS tokens_saved,
                    COALESCE(SUM(tokens_used), 0)  AS tokens_used
                FROM token_usage {where}
                GROUP BY DATE(created_at)
                ORDER BY date
                """,
                tuple(params),
            )

            gross = tokens_used + tokens_saved
            return {
                "tokens_used": tokens_used,
                "tokens_saved": tokens_saved,
                "operations": operations,
                "optimized_ops": optimized_ops,
                "optimization_rate": (
                    round(optimized_ops / operations, 4) if operations else 0.0
                ),
                "savings_rate": (round(tokens_saved / gross, 4) if gross else 0.0),
                "avg_saved_per_op": (
                    round(tokens_saved / operations, 2) if operations else 0.0
                ),
                "by_operation": [
                    {
                        "operation_type": row["operation_type"] or "unknown",
                        "tokens_used": row["tokens_used"],
                        "tokens_saved": row["tokens_saved"],
                        "operations": row["operations"],
                    }
                    for row in by_op_rows
                ],
                "daily": [
                    {
                        "date": row["date"],
                        "tokens_saved": row["tokens_saved"],
                        "tokens_used": row["tokens_used"],
                    }
                    for row in daily_rows
                ],
            }
        except Exception as e:
            logger.error(f"Failed to get token economics: {e}")
            raise

    async def get_kb_health(
        self, project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """지식베이스 건강도 (나이 분포 / stale / 고아 / 그래프 밀도)."""
        try:
            where, params = self._memory_filters(project_id, None, None)
            and_or_where = (where + " AND ") if where else "WHERE "

            total_row = await self.db.fetchone(
                f"SELECT COUNT(*) AS c FROM memories {where}", tuple(params)
            )
            total = total_row["c"] if total_row else 0

            age_row = await self.db.fetchone(
                f"""
                SELECT
                    SUM(CASE WHEN age <= 1 THEN 1 ELSE 0 END)               AS d1,
                    SUM(CASE WHEN age > 1 AND age <= 7 THEN 1 ELSE 0 END)   AS d7,
                    SUM(CASE WHEN age > 7 AND age <= 30 THEN 1 ELSE 0 END)  AS d30,
                    SUM(CASE WHEN age > 30 AND age <= 90 THEN 1 ELSE 0 END) AS d90,
                    SUM(CASE WHEN age > 90 THEN 1 ELSE 0 END)               AS older
                FROM (
                    SELECT julianday('now') - julianday(created_at) AS age
                    FROM memories {where}
                )
                """,
                tuple(params),
            )

            stale_row = await self.db.fetchone(
                f"""
                SELECT COUNT(*) AS c FROM memories
                {and_or_where} julianday('now') - julianday(updated_at) > 90
                """,
                tuple(params),
            )
            stale = stale_row["c"] if stale_row else 0

            orphan_row = await self.db.fetchone(
                f"""
                SELECT COUNT(*) AS c FROM memories
                {and_or_where} NOT EXISTS (
                    SELECT 1 FROM memory_relations r
                    WHERE r.source_id = memories.id OR r.target_id = memories.id
                )
                """,
                tuple(params),
            )
            orphans = orphan_row["c"] if orphan_row else 0

            # Relations touching the filtered memory set (global when no filter).
            id_subq = f"SELECT id FROM memories {where}"
            rel_row = await self.db.fetchone(
                f"""
                SELECT COUNT(*) AS c FROM memory_relations r
                WHERE r.source_id IN ({id_subq})
                   OR r.target_id IN ({id_subq})
                """,
                tuple(params) + tuple(params),
            )
            total_relations = rel_row["c"] if rel_row else 0

            # Most connected nodes (degree = appearances as source or target).
            top_connected_rows = await self.db.fetchall(
                f"""
                SELECT m.id AS id, SUBSTR(m.content, 1, 80) AS snippet,
                       m.category AS category, deg.degree AS degree
                FROM (
                    SELECT mid, COUNT(*) AS degree FROM (
                        SELECT source_id AS mid FROM memory_relations
                        UNION ALL
                        SELECT target_id AS mid FROM memory_relations
                    ) GROUP BY mid
                ) deg
                JOIN memories m ON m.id = deg.mid
                {("WHERE m.project_id = ?" if project_id else "")}
                ORDER BY deg.degree DESC
                LIMIT 10
                """,
                (project_id,) if project_id else (),
            )

            return {
                "total_memories": total,
                "age_distribution": {
                    "le_1d": (age_row["d1"] or 0) if age_row else 0,
                    "le_7d": (age_row["d7"] or 0) if age_row else 0,
                    "le_30d": (age_row["d30"] or 0) if age_row else 0,
                    "le_90d": (age_row["d90"] or 0) if age_row else 0,
                    "older": (age_row["older"] or 0) if age_row else 0,
                },
                "stale_count": stale,
                "stale_ratio": (round(stale / total, 4) if total else 0.0),
                "orphan_count": orphans,
                "orphan_ratio": (round(orphans / total, 4) if total else 0.0),
                "total_relations": total_relations,
                "graph_density": (round(total_relations / total, 4) if total else 0.0),
                "top_connected": [
                    {
                        "id": row["id"],
                        "snippet": row["snippet"],
                        "category": row["category"],
                        "degree": row["degree"],
                    }
                    for row in top_connected_rows
                ],
            }
        except Exception as e:
            logger.error(f"Failed to get KB health: {e}")
            raise

    async def get_recall_stats(
        self, project_id: Optional[str] = None, limit: int = 10
    ) -> Dict[str, Any]:
        """리콜/활용도 통계 (most-recalled / dead memory / 접근 분포)."""
        try:
            where, params = self._memory_filters(project_id, None, None)
            and_or_where = (where + " AND ") if where else "WHERE "

            summary_row = await self.db.fetchone(
                f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN COALESCE(access_count, 0) = 0 THEN 1 ELSE 0 END) AS dead,
                    SUM(CASE WHEN COALESCE(access_count, 0) > 0 THEN 1 ELSE 0 END) AS recalled,
                    COALESCE(SUM(access_count), 0) AS total_accesses,
                    COALESCE(AVG(access_count), 0)  AS avg_access
                FROM memories {where}
                """,
                tuple(params),
            )
            total = summary_row["total"] if summary_row else 0
            dead = summary_row["dead"] if summary_row else 0
            recalled = summary_row["recalled"] if summary_row else 0

            dist_row = await self.db.fetchone(
                f"""
                SELECT
                    SUM(CASE WHEN COALESCE(access_count,0) = 0 THEN 1 ELSE 0 END)  AS b0,
                    SUM(CASE WHEN access_count BETWEEN 1 AND 2 THEN 1 ELSE 0 END)  AS b1,
                    SUM(CASE WHEN access_count BETWEEN 3 AND 5 THEN 1 ELSE 0 END)  AS b3,
                    SUM(CASE WHEN access_count BETWEEN 6 AND 10 THEN 1 ELSE 0 END) AS b6,
                    SUM(CASE WHEN access_count > 10 THEN 1 ELSE 0 END)             AS b10
                FROM memories {where}
                """,
                tuple(params),
            )

            top_rows = await self.db.fetchall(
                f"""
                SELECT id, SUBSTR(content, 1, 80) AS snippet, category,
                       COALESCE(access_count, 0) AS access_count, last_accessed_at
                FROM memories
                {and_or_where} COALESCE(access_count, 0) > 0
                ORDER BY access_count DESC, last_accessed_at DESC
                LIMIT ?
                """,
                tuple(params) + (limit,),
            )

            return {
                "total_memories": total,
                "recalled_count": recalled,
                "dead_count": dead,
                "dead_ratio": (round(dead / total, 4) if total else 0.0),
                "recall_ratio": (round(recalled / total, 4) if total else 0.0),
                "total_accesses": (
                    summary_row["total_accesses"] if summary_row else 0
                ),
                "avg_access": (
                    round(summary_row["avg_access"], 2) if summary_row else 0.0
                ),
                "distribution": {
                    "never": (dist_row["b0"] or 0) if dist_row else 0,
                    "1_2": (dist_row["b1"] or 0) if dist_row else 0,
                    "3_5": (dist_row["b3"] or 0) if dist_row else 0,
                    "6_10": (dist_row["b6"] or 0) if dist_row else 0,
                    "gt_10": (dist_row["b10"] or 0) if dist_row else 0,
                },
                "most_recalled": [
                    {
                        "id": row["id"],
                        "snippet": row["snippet"],
                        "category": row["category"],
                        "access_count": row["access_count"],
                        "last_accessed_at": row["last_accessed_at"],
                    }
                    for row in top_rows
                ],
            }
        except Exception as e:
            logger.error(f"Failed to get recall stats: {e}")
            raise

    async def get_activity_trend(
        self,
        project_id: Optional[str] = None,
        days: int = 30,
        dimension: str = "client",
    ) -> Dict[str, Any]:
        """일별 활동 추이를 클라이언트/소스 차원으로 분해 (stacked 시계열).

        dimension: 'client' 또는 'source'. 그 외 값은 client로 처리.
        """
        try:
            col = "source" if dimension == "source" else "client"

            conds = ["DATE(created_at) >= DATE('now', ?)"]
            params: list = [f"-{int(days)} days"]
            if project_id:
                conds.append("project_id = ?")
                params.append(project_id)
            where = "WHERE " + " AND ".join(conds)

            rows = await self.db.fetchall(
                f"""
                SELECT DATE(created_at) AS date,
                       COALESCE({col}, 'unknown') AS key,
                       COUNT(*) AS count
                FROM memories
                {where}
                GROUP BY DATE(created_at), {col}
                ORDER BY date
                """,
                tuple(params),
            )

            # Pivot to {dates: [...], series: {key: [counts aligned to dates]}}.
            counts: Dict[str, Dict[str, int]] = defaultdict(dict)
            keys: list = []
            for row in rows:
                d, k, c = row["date"], row["key"], row["count"]
                counts[d][k] = c
                if k not in keys:
                    keys.append(k)

            dates = sorted(counts.keys())
            series = {
                k: [counts[d].get(k, 0) for d in dates] for k in keys
            }

            return {
                "dimension": col,
                "dates": dates,
                "series": series,
                "totals": {k: sum(series[k]) for k in keys},
            }
        except Exception as e:
            logger.error(f"Failed to get activity trend: {e}")
            raise
