"""Project 서비스 - 프로젝트 관리 비즈니스 로직"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from app.core.database.base import Database
from app.core.schemas.projects import (
    ProjectResponse,
    ProjectUpdate,
    ProjectWithStats,
)

logger = logging.getLogger(__name__)


class ProjectService:
    """프로젝트 관리 서비스"""

    def __init__(self, db: Database):
        self.db = db

    async def get_or_create_project(self, project_id: str) -> ProjectResponse:
        """
        프로젝트 조회 또는 자동 생성.

        Args:
            project_id: 프로젝트 ID

        Returns:
            ProjectResponse
        """
        # Query existing project
        row = await self.db.fetchone(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        )

        if row:
            return self._row_to_response(row)

        # Auto-create new project
        now = datetime.now(timezone.utc).isoformat()

        await self.db.execute(
            """
            INSERT INTO projects (id, name, description, tech_stack, global_rules, global_context, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, project_id, None, None, None, None, now, now),
        )
        self.db.connection.commit()

        logger.info(f"Auto-created project: {project_id}")

        return ProjectResponse(
            id=project_id,
            name=project_id,
            description=None,
            tech_stack=None,
            global_rules=None,
            global_context=None,
            created_at=now,
            updated_at=now,
        )

    async def get_project(self, project_id: str) -> Optional[ProjectResponse]:
        """프로젝트 조회"""
        row = await self.db.fetchone(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        )

        if not row:
            return None

        return self._row_to_response(row)

    async def update_project(
        self, project_id: str, update: ProjectUpdate
    ) -> Optional[ProjectResponse]:
        """프로젝트 업데이트"""
        # Check existing project
        existing = await self.get_project(project_id)
        if not existing:
            return None

        # Collect fields to update
        updates = []
        params = []

        update_data = update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                updates.append(f"{field} = ?")
                params.append(value)

        if not updates:
            return existing

        # Add updated_at
        now = datetime.now(timezone.utc).isoformat()
        updates.append("updated_at = ?")
        params.append(now)
        params.append(project_id)

        await self.db.execute(
            f"UPDATE projects SET {', '.join(updates)} WHERE id = ?", tuple(params)
        )
        self.db.connection.commit()

        logger.info(f"Updated project: {project_id}")

        return await self.get_project(project_id)

    async def list_projects(self) -> List[ProjectResponse]:
        """모든 프로젝트 목록 조회"""
        rows = await self.db.fetchall("SELECT * FROM projects ORDER BY updated_at DESC")

        return [self._row_to_response(row) for row in rows]

    async def list_projects_with_stats(self) -> List[ProjectWithStats]:
        """프로젝트 목록 조회 (통계 포함)"""
        rows = await self.db.fetchall("""
            SELECT 
                p.*,
                COALESCE(m.memory_count, 0) as memory_count,
                COALESCE(pin.pin_count, 0) as pin_count,
                s.id as active_session,
                COALESCE(lt.avg_lead_time, 0) as avg_lead_time_hours
            FROM projects p
            LEFT JOIN (
                SELECT project_id, COUNT(*) as memory_count
                FROM memories
                GROUP BY project_id
            ) m ON p.id = m.project_id
            LEFT JOIN (
                SELECT project_id, COUNT(*) as pin_count
                FROM pins
                GROUP BY project_id
            ) pin ON p.id = pin.project_id
            LEFT JOIN (
                SELECT project_id, id
                FROM sessions
                WHERE status = 'active'
            ) s ON p.id = s.project_id
            LEFT JOIN (
                SELECT 
                    project_id,
                    AVG(
                        (julianday(completed_at) - julianday(created_at)) * 24
                    ) as avg_lead_time
                FROM pins
                WHERE status = 'completed' AND completed_at IS NOT NULL
                GROUP BY project_id
            ) lt ON p.id = lt.project_id
            ORDER BY p.updated_at DESC
            """)

        return [self._row_to_stats_response(row) for row in rows]

    async def delete_project(self, project_id: str) -> bool:
        """프로젝트 삭제 (관련 세션, 핀도 삭제)"""
        existing = await self.get_project(project_id)
        if not existing:
            return False

        # Delete related pins
        await self.db.execute("DELETE FROM pins WHERE project_id = ?", (project_id,))

        # Delete related sessions
        await self.db.execute(
            "DELETE FROM sessions WHERE project_id = ?", (project_id,)
        )

        # Delete project
        await self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self.db.connection.commit()

        logger.info(f"Deleted project: {project_id}")
        return True

    def _row_to_response(self, row) -> ProjectResponse:
        """DB row를 ProjectResponse로 변환"""
        return ProjectResponse(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            tech_stack=row["tech_stack"],
            global_rules=row["global_rules"],
            global_context=row["global_context"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_stats_response(self, row) -> ProjectWithStats:
        """DB row를 ProjectWithStats로 변환"""
        return ProjectWithStats(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            tech_stack=row["tech_stack"],
            global_rules=row["global_rules"],
            memory_count=row["memory_count"] or 0,
            pin_count=row["pin_count"] or 0,
            active_session=row["active_session"],
            avg_lead_time_hours=row["avg_lead_time_hours"],
        )
