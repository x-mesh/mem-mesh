"""Session 서비스 - 세션 관리 비즈니스 로직"""

import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from uuid import uuid4

from app.core.database.base import Database
from app.core.services.project import ProjectService
from app.core.schemas.sessions import (
    SessionResponse,
    SessionContext,
)
from app.core.schemas.pins import PinResponse
from app.core.schemas.optimization import TokenInfo
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

        # Pin 통계 조회 (open과 in_progress 모두 "열린" 핀으로 카운트)
        stats_row = await self.db.fetchone(
            """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status IN ('open', 'in_progress') THEN 1 ELSE 0 END) as open_count,
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
        
        # 세션 요약이 없으면 최근 열린 핀들로 자동 생성
        summary = session.summary
        if not summary and open_pins > 0:
            # 열린 핀들의 내용으로 간단한 요약 생성
            open_pin_rows = await self.db.fetchall(
                """
                SELECT content FROM pins
                WHERE session_id = ? AND status IN ('open', 'in_progress')
                ORDER BY importance DESC, created_at DESC
                LIMIT 3
                """,
                (session.id,),
            )
            if open_pin_rows:
                open_tasks = [r["content"][:50] for r in open_pin_rows]
                summary = f"진행 중: {', '.join(open_tasks)}"

        return SessionContext(
            session_id=session.id,
            project_id=session.project_id,
            user_id=session.user_id,
            status=session.status,
            started_at=session.started_at,
            summary=summary,  # 자동 생성된 요약 사용
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

    async def resume_with_token_tracking(
        self,
        project_id: str,
        user_id: Optional[str] = None,
        expand: bool = False,
        limit: int = 10
    ) -> Tuple[Optional[SessionContext], Dict[str, int]]:
        """
        토큰 추적과 함께 세션 재개
        
        Args:
            project_id: 프로젝트 ID
            user_id: 사용자 ID
            expand: True면 전체 pin 내용 반환
            limit: 반환할 pin 개수
            
        Returns:
            (session_context, token_info)
            token_info = {
                "loaded_tokens": int,
                "unloaded_tokens": int,
                "estimated_total": int
            }
            
        Requirements: 1.1, 1.2, 1.3, 1.5, 7.1, 7.2
        """
        from app.core.services.token_tracker import TokenTracker
        
        # 기존 resume_last_session 호출
        session_context = await self.resume_last_session(
            project_id=project_id,
            user_id=user_id,
            expand=expand,
            limit=limit
        )
        
        if not session_context:
            # 세션이 없으면 토큰 정보도 0으로 반환
            return None, {
                "loaded_tokens": 0,
                "unloaded_tokens": 0,
                "estimated_total": 0
            }
        
        # TokenTracker 초기화
        token_tracker = TokenTracker(self.db)
        
        # 로드된 컨텐츠의 토큰 수 계산
        loaded_tokens = 0
        
        # 세션 요약 토큰
        if session_context.summary:
            loaded_tokens += await token_tracker.estimate_tokens(session_context.summary)
        
        # expand=true일 때 핀 내용 토큰
        if expand and session_context.pins:
            for pin in session_context.pins:
                loaded_tokens += await token_tracker.estimate_tokens(pin.content)
        
        # 로드되지 않은 핀들의 예상 토큰 수 계산
        unloaded_tokens = 0
        if not expand and session_context.pins_count > 0:
            # 로드되지 않은 핀들의 내용 조회
            unloaded_pin_rows = await self.db.fetchall(
                """
                SELECT content FROM pins
                WHERE session_id = ?
                ORDER BY importance DESC, created_at DESC
                LIMIT -1 OFFSET ?
                """,
                (session_context.session_id, limit if expand else 0)
            )
            
            for row in unloaded_pin_rows:
                unloaded_tokens += await token_tracker.estimate_tokens(row["content"])
        
        estimated_total = loaded_tokens + unloaded_tokens
        
        # 토큰 사용량 기록
        await token_tracker.record_session_tokens(
            session_id=session_context.session_id,
            loaded_tokens=loaded_tokens,
            unloaded_tokens=unloaded_tokens,
            event_type="resume",
            context_depth=limit
        )
        
        # token_usage 테이블에도 기록
        await token_tracker.record_token_usage(
            project_id=project_id,
            operation_type="session_resume",
            tokens_used=loaded_tokens,
            session_id=session_context.session_id,
            tokens_saved=unloaded_tokens,
            optimization_applied=(not expand)
        )
        
        token_info = {
            "loaded_tokens": loaded_tokens,
            "unloaded_tokens": unloaded_tokens,
            "estimated_total": estimated_total
        }
        
        logger.info(
            f"Session resumed with token tracking: session={session_context.session_id}, "
            f"loaded={loaded_tokens}, unloaded={unloaded_tokens}"
        )
        
        return session_context, token_info

    async def end_with_auto_promotion(
        self,
        session_id: str,
        summary: Optional[str] = None,
        auto_promote_threshold: int = 4
    ) -> Dict[str, Any]:
        """
        자동 승격과 함께 세션 종료
        
        Args:
            session_id: 세션 ID
            summary: 세션 요약
            auto_promote_threshold: 자동 승격 중요도 임계값 (기본값: 4)
            
        Returns:
            {
                "session": SessionResponse,
                "promoted_pins": List[str],  # 승격된 핀 ID 목록
                "token_savings": Dict[str, Any]
            }
            
        Requirements: 5.4
        """
        from app.core.services.token_tracker import TokenTracker
        from app.core.services.pin import PinService
        
        # 세션 종료
        session = await self.end_session(session_id, summary)
        
        if not session:
            logger.warning(f"Session {session_id} not found for auto-promotion")
            return {
                "session": None,
                "promoted_pins": [],
                "token_savings": {
                    "total_tokens": 0,
                    "loaded_tokens": 0,
                    "saved_tokens": 0,
                    "savings_rate": 0.0
                }
            }
        
        # importance >= threshold인 완료된 핀 조회
        promotion_candidates = await self.db.fetchall(
            """
            SELECT id, importance, content FROM pins
            WHERE session_id = ? 
            AND status = 'completed'
            AND importance >= ?
            AND promoted_to_memory_id IS NULL
            ORDER BY importance DESC
            """,
            (session_id, auto_promote_threshold)
        )
        
        # 핀 승격 처리
        pin_service = PinService(self.db)
        promoted_pins = []
        
        for candidate in promotion_candidates:
            try:
                result = await pin_service.promote_to_memory(candidate["id"])
                if not result.get("already_promoted", False):
                    promoted_pins.append(candidate["id"])
                    logger.info(
                        f"Auto-promoted pin {candidate['id']} "
                        f"(importance={candidate['importance']}) to memory {result['memory_id']}"
                    )
            except Exception as e:
                logger.error(f"Failed to promote pin {candidate['id']}: {e}")
        
        # 토큰 절감 통계 계산
        token_tracker = TokenTracker(self.db)
        token_savings = await token_tracker.calculate_savings(session_id)
        
        # 세션 종료 이벤트 기록
        await token_tracker.record_session_tokens(
            session_id=session_id,
            loaded_tokens=0,
            unloaded_tokens=0,
            event_type="end"
        )
        
        logger.info(
            f"Session {session_id} ended with auto-promotion: "
            f"{len(promoted_pins)} pins promoted, "
            f"token savings: {token_savings['savings_rate']:.2%}"
        )
        
        return {
            "session": session,
            "promoted_pins": promoted_pins,
            "token_savings": token_savings
        }

    async def get_session_statistics(
        self,
        project_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        세션 통계 조회
        
        Args:
            project_id: 프로젝트 ID (None이면 전체)
            start_date: 시작 날짜 (ISO 형식, 선택적)
            end_date: 종료 날짜 (ISO 형식, 선택적)
            
        Returns:
            {
                "total_sessions": int,
                "avg_duration_hours": float,
                "avg_pins_per_session": float,
                "importance_distribution": Dict[int, int],
                "avg_token_savings_rate": float
            }
            
        Requirements: 9.1, 9.2, 9.3, 9.4, 9.5
        """
        from app.core.services.token_tracker import TokenTracker
        
        # 기본 쿼리 구성
        query_conditions = ["1=1"]
        params = []
        
        if project_id:
            query_conditions.append("s.project_id = ?")
            params.append(project_id)
        
        if start_date:
            query_conditions.append("s.started_at >= ?")
            params.append(start_date)
        
        if end_date:
            query_conditions.append("s.started_at <= ?")
            params.append(end_date)
        
        where_clause = " AND ".join(query_conditions)
        
        # 1. 총 세션 수 및 평균 지속 시간
        session_stats = await self.db.fetchone(
            f"""
            SELECT 
                COUNT(*) as total_sessions,
                AVG(
                    CASE 
                        WHEN ended_at IS NOT NULL THEN
                            (julianday(ended_at) - julianday(started_at)) * 24
                        ELSE NULL
                    END
                ) as avg_duration_hours
            FROM sessions s
            WHERE {where_clause}
            """,
            tuple(params)
        )
        
        total_sessions = session_stats["total_sessions"] or 0
        avg_duration_hours = session_stats["avg_duration_hours"] or 0.0
        
        # 2. 세션당 평균 핀 수
        pin_stats = await self.db.fetchone(
            f"""
            SELECT 
                COUNT(*) as total_pins,
                COUNT(DISTINCT p.session_id) as sessions_with_pins
            FROM pins p
            JOIN sessions s ON p.session_id = s.id
            WHERE {where_clause}
            """,
            tuple(params)
        )
        
        total_pins = pin_stats["total_pins"] or 0
        sessions_with_pins = pin_stats["sessions_with_pins"] or 1  # 0으로 나누기 방지
        avg_pins_per_session = total_pins / sessions_with_pins if sessions_with_pins > 0 else 0.0
        
        # 3. 중요도별 핀 분포
        importance_rows = await self.db.fetchall(
            f"""
            SELECT 
                p.importance,
                COUNT(*) as count
            FROM pins p
            JOIN sessions s ON p.session_id = s.id
            WHERE {where_clause}
            GROUP BY p.importance
            ORDER BY p.importance
            """,
            tuple(params)
        )
        
        importance_distribution = {row["importance"]: row["count"] for row in importance_rows}
        
        # 4. 평균 토큰 절감률
        token_tracker = TokenTracker(self.db)
        
        # 프로젝트별 토큰 통계 조회
        if project_id:
            token_stats = await token_tracker.get_project_token_statistics(
                project_id=project_id,
                start_date=start_date,
                end_date=end_date
            )
            avg_token_savings_rate = token_stats.get("avg_savings_rate", 0.0)
        else:
            # 전체 프로젝트의 평균 계산
            all_sessions = await self.db.fetchall(
                f"""
                SELECT id FROM sessions s
                WHERE {where_clause}
                """,
                tuple(params)
            )
            
            if all_sessions:
                total_savings_rate = 0.0
                valid_sessions = 0
                
                for session_row in all_sessions:
                    try:
                        savings = await token_tracker.calculate_savings(session_row["id"])
                        if savings["total_tokens"] > 0:
                            total_savings_rate += savings["savings_rate"]
                            valid_sessions += 1
                    except Exception:
                        continue
                
                avg_token_savings_rate = (
                    total_savings_rate / valid_sessions if valid_sessions > 0 else 0.0
                )
            else:
                avg_token_savings_rate = 0.0
        
        result = {
            "total_sessions": total_sessions,
            "avg_duration_hours": round(avg_duration_hours, 2),
            "avg_pins_per_session": round(avg_pins_per_session, 2),
            "importance_distribution": importance_distribution,
            "avg_token_savings_rate": round(avg_token_savings_rate, 4)
        }
        
        logger.info(
            f"Session statistics calculated: "
            f"total={total_sessions}, avg_duration={avg_duration_hours:.2f}h, "
            f"avg_pins={avg_pins_per_session:.2f}, avg_savings={avg_token_savings_rate:.2%}"
        )
        
        return result
