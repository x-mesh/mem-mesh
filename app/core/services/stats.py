"""
Statistics service for mem-mesh.

This module provides statistics and analytics for stored memories,
including counts by project, category, source, and date ranges.
"""

import logging
from typing import Dict, Optional, Any, List, Tuple
from datetime import datetime, timezone
import time

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
        end_date: Optional[str] = None
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
            total_memories = total_result['total'] if total_result else 0
            
            # 고유 프로젝트 수 조회
            unique_projects_query = f"""
                SELECT COUNT(DISTINCT project_id) as unique_projects 
                FROM memories 
                {where_clause}
            """
            unique_result = await self.db.fetchone(unique_projects_query, tuple(params))
            unique_projects = unique_result['unique_projects'] if unique_result else 0
            
            # 카테고리별 분포
            categories_breakdown = await self.get_category_stats(project_id, start_date, end_date)
            
            # 소스별 분포
            sources_breakdown = await self.get_source_stats(project_id, start_date, end_date)
            
            # 프로젝트별 분포 (project_id 필터가 없는 경우에만)
            projects_breakdown = {}
            if not project_id:
                projects_breakdown = await self.get_project_stats(None, start_date, end_date)
            
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
                "date_range": date_range,
                "query_time_ms": round(query_time_ms, 2)
            }
            
        except Exception as e:
            logger.error(f"Failed to get overall stats: {e}")
            raise
    
    async def get_project_stats(
        self, 
        project_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
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
            
            return {
                row['project_name']: row['count'] 
                for row in results
            }
            
        except Exception as e:
            logger.error(f"Failed to get project stats: {e}")
            raise
    
    async def get_category_stats(
        self, 
        project_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
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
            
            return {
                row['category']: row['count'] 
                for row in results
            }
            
        except Exception as e:
            logger.error(f"Failed to get category stats: {e}")
            raise
    
    async def get_source_stats(
        self, 
        project_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
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
            
            return {
                row['source']: row['count'] 
                for row in results
            }
            
        except Exception as e:
            logger.error(f"Failed to get source stats: {e}")
            raise
    
    async def get_date_range_stats(
        self, 
        start_date: str, 
        end_date: str,
        project_id: Optional[str] = None
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
            
            return {
                row['date']: row['count'] 
                for row in results
            }
            
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
                GROUP BY project_id
                ORDER BY memory_count DESC
            """
            
            projects = await self.db.fetchall(query, ())
            
            # 각 프로젝트의 카테고리와 태그 집계
            result = []
            for project in projects:
                pid = project['project_id']
                
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
                
                result.append({
                    'id': pid,
                    'name': 'Default Project' if pid == 'default' else pid,
                    'memory_count': project['memory_count'],
                    'total_size': project['total_size'] or 0,
                    'avg_memory_size': (project['total_size'] or 0) // project['memory_count'] if project['memory_count'] > 0 else 0,
                    'categories': [c['category'] for c in categories],
                    'tags': [t['tag'] for t in tags],
                    'created_at': project['created_at'],
                    'updated_at': project['updated_at']
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get projects detail: {e}")
            raise