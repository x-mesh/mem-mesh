"""
Statistics service for mem-mesh.

This module provides statistics and analytics for stored memories,
including counts by project, category, source, and date ranges.
"""

import logging
import time
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
            # 기본 필터 조건 구성
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

            # 총 메모리 수 조회
            total_query = f"SELECT COUNT(*) as total FROM memories {where_clause}"
            total_result = await self.db.fetchone(total_query, tuple(params))
            total_memories = total_result["total"] if total_result else 0

            # 고유 프로젝트 수 조회
            unique_projects_query = f"""
                SELECT COUNT(DISTINCT project_id) as unique_projects 
                FROM memories 
                {where_clause}
            """
            unique_result = await self.db.fetchone(unique_projects_query, tuple(params))
            unique_projects = unique_result["unique_projects"] if unique_result else 0

            # 카테고리별 분포
            categories_breakdown = await self.get_category_stats(
                project_id, start_date, end_date
            )

            # 소스별 분포
            sources_breakdown = await self.get_source_stats(
                project_id, start_date, end_date
            )

            # 클라이언트 도구별 분포
            clients_breakdown = await self.get_client_stats(
                project_id, start_date, end_date
            )

            # 프로젝트별 분포 (project_id 필터가 없는 경우에만)
            projects_breakdown = {}
            if not project_id:
                projects_breakdown = await self.get_project_stats(
                    None, start_date, end_date
                )

            # 날짜 범위 정보
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
            # 프로젝트별 기본 통계
            query = """
                SELECT
                    COALESCE(project_id, 'default') as project_id,
                    COUNT(*) as memory_count,
                    SUM(LENGTH(content)) as total_size,
                    MIN(created_at) as created_at,
                    MAX(created_at) as updated_at
                FROM memories
                GROUP BY COALESCE(project_id, 'default')
                ORDER BY memory_count DESC
            """

            projects = await self.db.fetchall(query, ())

            # 각 프로젝트의 카테고리와 태그 집계
            result = []
            for project in projects:
                pid = project["project_id"]

                # 카테고리 조회
                cat_query = """
                    SELECT DISTINCT category 
                    FROM memories 
                    WHERE COALESCE(project_id, 'default') = ?
                """
                categories = await self.db.fetchall(cat_query, (pid,))

                # 태그 조회
                tag_query = """
                    SELECT DISTINCT value as tag
                    FROM memories m, json_each(CASE 
                        WHEN m.tags IS NULL OR m.tags = '' THEN '[]'
                        ELSE m.tags 
                    END) 
                    WHERE COALESCE(m.project_id, 'default') = ?
                """
                tags = await self.db.fetchall(tag_query, (pid,))

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
                        "categories": [c["category"] for c in categories],
                        "tags": [t["tag"] for t in tags],
                        "created_at": project["created_at"],
                        "updated_at": project["updated_at"],
                    }
                )

            return result

        except Exception as e:
            logger.error(f"Failed to get projects detail: {e}")
            raise

    # ===== Work Tracking System 통계 =====

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

            # 상태별 Pin 수
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

            # 총 Pin 수
            total_pins = sum(status_breakdown.values())

            # 평균 Lead Time (완료된 Pin만)
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

            # 중요도별 분포
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

            # 상태별 Session 수
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

            # 총 Session 수
            total_sessions = sum(status_breakdown.values())

            # 평균 세션 시간 (완료된 세션만)
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
