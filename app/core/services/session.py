"""Session 서비스 - 세션 관리 비즈니스 로직"""

import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from uuid import uuid4

from app.core.database.base import Database
from app.core.services.project import ProjectService
from app.core.schemas.sessions import (
    SessionResponse,
    SessionContext,
)
from app.core.schemas.pins import PinResponse
from app.core.utils.user import get_current_user

logger = logging.getLogger(__name__)


class NoActiveSessionError(Exception):
    """활성 세션이 없을 때 발생하는 예외"""

    # Exception subclass - no additional implementation needed


class SessionService:
    """세션 관리 서비스"""

    def __init__(self, db: Database, project_service: Optional[ProjectService] = None):
        self.db = db
        self.project_service = project_service or ProjectService(db)

    async def get_or_create_active_session(
        self, project_id: str, user_id: Optional[str] = None
    ) -> SessionResponse:
        """
        활성 세션 조회 또는 생성.

        Args:
            project_id: 프로젝트 ID
            user_id: 사용자 ID (None이면 자동 감지)

        Returns:
            SessionResponse
        """
        effective_user_id = user_id or get_current_user()

        # 프로젝트 자동 생성
        await self.project_service.get_or_create_project(project_id)

        # 기존 활성 세션 조회
        row = await self.db.fetchone(
            """
            SELECT * FROM sessions 
            WHERE project_id = ? AND user_id = ? AND status = 'active'
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (project_id, effective_user_id),
        )

        if row:
            return self._row_to_response(row)

        # 새 세션 생성
        session_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        await self.db.execute(
            """
            INSERT INTO sessions (id, project_id, user_id, started_at, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            (session_id, project_id, effective_user_id, now, now, now),
        )
        self.db.connection.commit()

        logger.info(f"Created new session: {session_id} for project: {project_id}")

        return SessionResponse(
            id=session_id,
            project_id=project_id,
            user_id=effective_user_id,
            started_at=now,
            ended_at=None,
            status="active",
            summary=None,
            created_at=now,
            updated_at=now,
        )

    async def get_session(self, session_id: str) -> Optional[SessionResponse]:
        """세션 조회"""
        row = await self.db.fetchone(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )

        if not row:
            return None

        return self._row_to_response(row)

    async def resume_last_session(
        self,
        project_id: str,
        user_id: Optional[str] = None,
        expand: bool = False,
        limit: int = 10,
    ) -> Optional[SessionContext]:
        """
        마지막 세션 컨텍스트 로드.

        Args:
            project_id: 프로젝트 ID
            user_id: 사용자 ID
            expand: True면 전체 pin 내용 반환
            limit: 반환할 pin 개수 (기본 10개)

        Returns:
            SessionContext 또는 None
        """
        effective_user_id = user_id or get_current_user()

        # 가장 최근 세션 조회 (활성 또는 일시정지)
        row = await self.db.fetchone(
            """
            SELECT * FROM sessions 
            WHERE project_id = ? AND user_id = ? AND status IN ('active', 'paused')
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (project_id, effective_user_id),
        )

        if not row:
            return None

        session = self._row_to_response(row)

        # 세션이 paused 상태면 active로 변경
        if session.status == "paused":
            now = datetime.now(timezone.utc).isoformat()
            await self.db.execute(
                "UPDATE sessions SET status = 'active', updated_at = ? WHERE id = ?",
                (now, session.id),
            )
            self.db.connection.commit()
            session.status = "active"

        # Pin 통계 조회
        stats_row = await self.db.fetchone(
            """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open_count,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_count
            FROM pins
            WHERE session_id = ?
            """,
            (session.id,),
        )

        pins_count = stats_row["total"] or 0
        open_pins = stats_row["open_count"] or 0
        completed_pins = stats_row["completed_count"] or 0

        # Pin 목록 조회 (importance 순)
        pins = []
        if expand:
            pin_rows = await self.db.fetchall(
                """
                SELECT * FROM pins
                WHERE session_id = ?
                ORDER BY importance DESC, created_at DESC
                LIMIT ?
                """,
                (session.id, limit),
            )
            pins = [self._pin_row_to_response(r) for r in pin_rows]

        return SessionContext(
            session_id=session.id,
            project_id=session.project_id,
            user_id=session.user_id,
            status=session.status,
            started_at=session.started_at,
            summary=session.summary,
            pins_count=pins_count,
            open_pins=open_pins,
            completed_pins=completed_pins,
            pins=pins,
        )

    async def end_session(
        self, session_id: str, summary: Optional[str] = None
    ) -> Optional[SessionResponse]:
        """
        세션 종료.

        Args:
            session_id: 세션 ID
            summary: 세션 요약 (None이면 자동 생성 가능)

        Returns:
            SessionResponse 또는 None
        """
        session = await self.get_session(session_id)
        if not session:
            return None

        if session.status == "completed":
            logger.warning(f"Session {session_id} is already completed")
            return session

        now = datetime.now(timezone.utc).isoformat()

        # 요약이 없으면 간단한 자동 요약 생성
        if not summary:
            stats_row = await self.db.fetchone(
                """
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed
                FROM pins
                WHERE session_id = ?
                """,
                (session_id,),
            )
            total = stats_row["total"] or 0
            completed = stats_row["completed"] or 0
            summary = f"세션 완료: {completed}/{total} pins 완료"

        await self.db.execute(
            """
            UPDATE sessions 
            SET status = 'completed', ended_at = ?, summary = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, summary, now, session_id),
        )
        self.db.connection.commit()

        logger.info(f"Ended session: {session_id}")

        return await self.get_session(session_id)

    async def pause_inactive_sessions(self, inactive_hours: int = 4) -> int:
        """
        비활성 세션 일시정지.

        Args:
            inactive_hours: 비활성 기준 시간 (기본 4시간)

        Returns:
            일시정지된 세션 수
        """
        cutoff_time = (
            datetime.now(timezone.utc) - timedelta(hours=inactive_hours)
        ).isoformat()

        cursor = await self.db.execute(
            """
            UPDATE sessions 
            SET status = 'paused', updated_at = ?
            WHERE status = 'active' AND updated_at < ?
            """,
            (datetime.now(timezone.utc).isoformat(), cutoff_time),
        )
        self.db.connection.commit()

        count = cursor.rowcount
        if count > 0:
            logger.info(f"Paused {count} inactive sessions")

        return count

    async def list_sessions(
        self,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[SessionResponse]:
        """세션 목록 조회"""
        query = "SELECT * FROM sessions WHERE 1=1"
        params = []

        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)

        rows = await self.db.fetchall(query, tuple(params))
        return [self._row_to_response(row) for row in rows]

    def _row_to_response(self, row) -> SessionResponse:
        """DB row를 SessionResponse로 변환"""
        return SessionResponse(
            id=row["id"],
            project_id=row["project_id"],
            user_id=row["user_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            status=row["status"],
            summary=row["summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _pin_row_to_response(self, row) -> PinResponse:
        """DB row를 PinResponse로 변환"""
        tags = []
        if row["tags"]:
            try:
                tags = json.loads(row["tags"])
            except json.JSONDecodeError:
                tags = []

        # lead_time 계산
        lead_time_hours = None
        if row["completed_at"] and row["created_at"]:
            try:
                created = datetime.fromisoformat(
                    row["created_at"].replace("Z", "+00:00")
                )
                completed = datetime.fromisoformat(
                    row["completed_at"].replace("Z", "+00:00")
                )
                lead_time_hours = (completed - created).total_seconds() / 3600
            except Exception:
                # Silently ignore errors when calculating lead time - use None if calculation fails
                pass

        return PinResponse(
            id=row["id"],
            session_id=row["session_id"],
            project_id=row["project_id"],
            user_id=row["user_id"],
            content=row["content"],
            importance=row["importance"],
            status=row["status"],
            tags=tags,
            completed_at=row["completed_at"],
            lead_time_hours=lead_time_hours,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
