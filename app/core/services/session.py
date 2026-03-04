"""Session 서비스 - 세션 관리 비즈니스 로직"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from app.core.database.base import Database
from app.core.schemas.pins import PinResponse
from app.core.services.pin import _parse_tags
from app.core.schemas.sessions import (
    SessionContext,
    SessionResponse,
)
from app.core.services.project import ProjectService
from app.core.utils.user import get_current_user

logger = logging.getLogger(__name__)


class NoActiveSessionError(Exception):
    """활성 세션이 없을 때 발생하는 예외"""

    # Exception subclass - no additional implementation needed


class SessionService:
    """세션 관리 서비스"""

    def __init__(
        self,
        db: Database,
        project_service: Optional[ProjectService] = None,
        embedding_service=None,
    ):
        self.db = db
        self.project_service = project_service or ProjectService(db)
        self._embedding_service = embedding_service

    async def get_or_create_active_session(
        self,
        project_id: str,
        user_id: Optional[str] = None,
        ide_session_id: Optional[str] = None,
        client_type: Optional[str] = None,
    ) -> SessionResponse:
        """
        활성 세션 조회 또는 생성.

        Args:
            project_id: 프로젝트 ID
            user_id: 사용자 ID (None이면 자동 감지)
            ide_session_id: IDE 네이티브 세션 ID (Claude Code session_id 등)
            client_type: IDE/도구 유형 (claude-ai, Cursor, Windsurf 등)

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
            session = self._row_to_response(row)
            # ide_session_id가 제공되었고 기존 세션에 없으면 업데이트
            if ide_session_id and not session.ide_session_id:
                now = datetime.now(timezone.utc).isoformat()
                await self.db.execute(
                    """
                    UPDATE sessions SET ide_session_id = ?, client_type = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (ide_session_id, client_type, now, session.id),
                )
                self.db.connection.commit()
                session.ide_session_id = ide_session_id
                session.client_type = client_type
            return session

        # 새 세션 생성
        session_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        await self.db.execute(
            """
            INSERT INTO sessions
                (id, project_id, user_id, ide_session_id, client_type,
                 started_at, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                session_id, project_id, effective_user_id,
                ide_session_id, client_type,
                now, now, now,
            ),
        )
        self.db.connection.commit()

        logger.info(
            f"Created new session: {session_id} for project: {project_id}"
            f" (ide_session={ide_session_id}, client={client_type})"
        )

        return SessionResponse(
            id=session_id,
            project_id=project_id,
            user_id=effective_user_id,
            ide_session_id=ide_session_id,
            client_type=client_type,
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
        expand: Union[bool, str] = False,
        limit: int = 10,
    ) -> Optional[SessionContext]:
        """
        마지막 세션 컨텍스트 로드.

        흐름:
        1. 활성/일시정지 세션이 있고 핀이 있으면 → 해당 세션 핀 반환
        2. 활성 세션은 있지만 핀이 없으면 → cross-session 핀을 병합하여 반환
        3. 활성 세션이 없으면 → cross-session fallback (최근 7일)
        4. 아무것도 없으면 → None

        Args:
            project_id: 프로젝트 ID
            user_id: 사용자 ID
            expand: True=전체, False=compact, "smart"=open/in_progress만 전체
            limit: 반환할 pin 개수 (기본 10개)

        Returns:
            SessionContext 또는 None
        """
        effective_user_id = user_id or get_current_user()

        # 가장 최근 세션 조회 (활성 또는 일시정지)
        active_row = await self.db.fetchone(
            """
            SELECT * FROM sessions
            WHERE project_id = ? AND user_id = ? AND status IN ('active', 'paused')
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (project_id, effective_user_id),
        )

        if active_row:
            session = self._row_to_response(active_row)

            # paused → active 전환
            if session.status == "paused":
                now = datetime.now(timezone.utc).isoformat()
                await self.db.execute(
                    "UPDATE sessions SET status = 'active', updated_at = ? WHERE id = ?",
                    (now, session.id),
                )
                self.db.connection.commit()
                session.status = "active"

            # 현재 세션의 핀 조회
            current_pins = await self._get_session_pins(session.id, limit)

            if current_pins["total"] > 0:
                # Case 1: 활성 세션 + 핀 있음 → 해당 세션 핀 반환
                return self._build_session_context(
                    session, current_pins, expand
                )

            # Case 2: 활성 세션 + 핀 없음 → cross-session 핀 병합
            cross_pins = await self._get_cross_session_pins(
                project_id, effective_user_id, session.id, limit
            )

            if cross_pins:
                pins = self._expand_pin_rows(cross_pins, expand)
                open_count = sum(
                    1 for r in cross_pins
                    if r["status"] in ("open", "in_progress")
                )
                completed_count = sum(
                    1 for r in cross_pins if r["status"] == "completed"
                )

                # 요약 생성
                open_contents = [
                    r["content"][:50] for r in cross_pins
                    if r["status"] in ("open", "in_progress")
                ][:3]
                summary = (
                    f"[이전 세션] 미완료: {', '.join(open_contents)}"
                    if open_contents
                    else "[이전 세션] 최근 작업 맥락 복원"
                )

                return SessionContext(
                    session_id=session.id,
                    project_id=session.project_id,
                    user_id=session.user_id,
                    status=session.status,
                    started_at=session.started_at,
                    summary=summary,
                    pins_count=len(cross_pins),
                    open_pins=open_count,
                    completed_pins=completed_count,
                    pins=pins,
                )

            # 활성 세션은 있지만 핀이 전혀 없음
            return SessionContext(
                session_id=session.id,
                project_id=session.project_id,
                user_id=session.user_id,
                status=session.status,
                started_at=session.started_at,
                summary=None,
                pins_count=0,
                open_pins=0,
                completed_pins=0,
                pins=[],
            )

        # Case 3: 활성 세션 없음 → cross-session fallback
        return await self._resume_cross_session(
            project_id, effective_user_id, expand, limit
        )

    async def _get_session_pins(
        self, session_id: str, limit: int
    ) -> Dict[str, Any]:
        """세션의 핀 통계 및 목록 조회."""
        stats_row = await self.db.fetchone(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status IN ('open', 'in_progress') THEN 1 ELSE 0 END) as open_count,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_count
            FROM pins
            WHERE session_id = ?
            """,
            (session_id,),
        )

        pin_rows = await self.db.fetchall(
            """
            SELECT * FROM pins
            WHERE session_id = ?
            ORDER BY importance DESC, created_at DESC
            LIMIT ?
            """,
            (session_id, limit),
        )

        return {
            "total": stats_row["total"] or 0,
            "open_count": stats_row["open_count"] or 0,
            "completed_count": stats_row["completed_count"] or 0,
            "rows": pin_rows,
        }

    async def _get_cross_session_pins(
        self,
        project_id: str,
        user_id: str,
        exclude_session_id: Optional[str] = None,
        limit: int = 10,
    ) -> list:
        """최근 7일 내 다른 세션의 핀 조회 (미완료 우선)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        if exclude_session_id:
            return await self.db.fetchall(
                """
                SELECT p.* FROM pins p
                JOIN sessions s ON p.session_id = s.id
                WHERE p.project_id = ? AND s.user_id = ?
                    AND p.created_at >= ? AND p.session_id != ?
                ORDER BY
                    CASE WHEN p.status IN ('open', 'in_progress') THEN 0 ELSE 1 END,
                    p.importance DESC,
                    p.created_at DESC
                LIMIT ?
                """,
                (project_id, user_id, cutoff, exclude_session_id, limit),
            )

        return await self.db.fetchall(
            """
            SELECT p.* FROM pins p
            JOIN sessions s ON p.session_id = s.id
            WHERE p.project_id = ? AND s.user_id = ? AND p.created_at >= ?
            ORDER BY
                CASE WHEN p.status IN ('open', 'in_progress') THEN 0 ELSE 1 END,
                p.importance DESC,
                p.created_at DESC
            LIMIT ?
            """,
            (project_id, user_id, cutoff, limit),
        )

    def _build_session_context(
        self,
        session: SessionResponse,
        pins_data: Dict[str, Any],
        expand: Union[bool, str],
    ) -> SessionContext:
        """세션과 핀 데이터로 SessionContext 빌드."""
        pins = self._expand_pin_rows(pins_data["rows"], expand)

        # 요약 자동 생성
        summary = session.summary
        if not summary and pins_data["open_count"] > 0:
            open_rows = [
                r for r in pins_data["rows"]
                if r["status"] in ("open", "in_progress")
            ][:3]
            if open_rows:
                open_tasks = [r["content"][:50] for r in open_rows]
                summary = f"진행 중: {', '.join(open_tasks)}"

        return SessionContext(
            session_id=session.id,
            project_id=session.project_id,
            user_id=session.user_id,
            status=session.status,
            started_at=session.started_at,
            summary=summary,
            pins_count=pins_data["total"],
            open_pins=pins_data["open_count"],
            completed_pins=pins_data["completed_count"],
            pins=pins,
        )

    async def _resume_cross_session(
        self,
        project_id: str,
        user_id: str,
        expand: Union[bool, str],
        limit: int,
    ) -> Optional[SessionContext]:
        """Cross-session fallback: 최근 7일 내 프로젝트 핀으로 맥락 복원.

        활성 세션이 없을 때 호출된다. 최근 종료된 세션들의 핀 중
        미완료(open/in_progress) 또는 중요도 높은 핀을 반환한다.
        """
        pin_rows = await self._get_cross_session_pins(
            project_id, user_id, limit=limit
        )

        if not pin_rows:
            return None

        pins = self._expand_pin_rows(pin_rows, expand)

        # 통계 계산
        open_count = sum(
            1 for r in pin_rows if r["status"] in ("open", "in_progress")
        )
        completed_count = sum(1 for r in pin_rows if r["status"] == "completed")

        # 요약 생성
        open_pin_contents = [
            r["content"][:50]
            for r in pin_rows
            if r["status"] in ("open", "in_progress")
        ][:3]
        summary = (
            f"[cross-session] 미완료: {', '.join(open_pin_contents)}"
            if open_pin_contents
            else "[cross-session] 최근 작업 맥락 복원"
        )

        # 가장 최근 종료된 세션 정보 사용
        last_session = await self.db.fetchone(
            """
            SELECT * FROM sessions
            WHERE project_id = ? AND user_id = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (project_id, user_id),
        )

        session_id = last_session["id"] if last_session else "cross-session"
        started_at = last_session["started_at"] if last_session else cutoff

        logger.info(
            f"Cross-session fallback for project={project_id}: "
            f"{len(pin_rows)} pins, {open_count} open"
        )

        return SessionContext(
            session_id=session_id,
            project_id=project_id,
            user_id=user_id,
            status="cross-session",
            started_at=started_at,
            summary=summary,
            pins_count=len(pin_rows),
            open_pins=open_count,
            completed_pins=completed_count,
            pins=pins,
        )

    def _expand_pin_rows(
        self, pin_rows: list, expand: Union[bool, str]
    ) -> list:
        """Pin rows를 expand 모드에 따라 변환."""
        if expand == "smart":
            return [self._pin_row_to_smart(r) for r in pin_rows]
        elif expand:
            return [self._pin_row_to_response(r) for r in pin_rows]
        else:
            return [self._pin_row_to_compact(r) for r in pin_rows]

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

        # 요약이 없으면 구조적 서사 요약 생성
        if not summary:
            summary = await self._generate_narrative_summary(session_id)

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

    async def end_session_by_project(
        self, project_id: str, summary: Optional[str] = None
    ) -> Optional[SessionResponse]:
        """End the most recent active session for a project.

        Used by SessionEnd/PreCompact hooks which only know the project_id,
        not the session_id.

        Args:
            project_id: Project identifier
            summary: Optional session summary

        Returns:
            SessionResponse or None if no active session found
        """
        effective_user_id = get_current_user()

        row = await self.db.fetchone(
            """
            SELECT id FROM sessions
            WHERE project_id = ? AND user_id = ? AND status = 'active'
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (project_id, effective_user_id),
        )

        if not row:
            logger.info(f"No active session found for project: {project_id}")
            return None

        return await self.end_session(row["id"], summary)

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
            ide_session_id=row["ide_session_id"] if "ide_session_id" in row.keys() else None,
            client_type=row["client_type"] if "client_type" in row.keys() else None,
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            status=row["status"],
            summary=row["summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _pin_row_to_response(self, row) -> PinResponse:
        """DB row를 PinResponse로 변환"""
        tags = _parse_tags(row["tags"])

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

    def _pin_row_to_compact(self, row) -> Dict[str, Any]:
        """
        DB row를 컴팩트 핀 정보로 변환 (토큰 절약용).

        expand=false일 때 사용. 맥락 유지에 필요한 최소 정보만 포함:
        - id: 핀 식별자 (complete/promote 호출용)
        - content: 80자로 제한된 내용 요약
        - importance: 중요도 (1-5)
        - status: 상태 (open/in_progress/completed)
        """
        content = row["content"] or ""
        truncated_content = content[:80] + "..." if len(content) > 80 else content

        return {
            "id": row["id"],
            "content": truncated_content,
            "importance": row["importance"],
            "status": row["status"],
        }

    def _pin_row_to_smart(self, row) -> Dict[str, Any]:
        """
        DB row를 Smart Expand 규칙에 따라 변환.

        status × importance 2축 매트릭스:
        - Tier 1: active + important(≥4) → full content + tags + created_at
        - Tier 2: active + normal(<4)    → content[:200] + tags
        - Tier 3: completed + important  → content[:80]
        - Tier 4: completed + normal     → id + importance + status만
        """
        status = row["status"]
        importance = row["importance"] or 3
        content = row["content"] or ""
        is_active = status in ("open", "in_progress")
        is_important = importance >= 4

        if is_active and is_important:
            # Tier 1: 진행 중 + 중요 → 전체 맥락 필요
            tags = json.loads(row["tags"]) if row["tags"] else []
            return {
                "id": row["id"],
                "content": content,
                "importance": importance,
                "status": status,
                "tags": tags,
                "created_at": row["created_at"],
                "_tier": 1,
            }

        if is_active:
            # Tier 2: 진행 중 + 일반 → 대략적 내용만
            tags = json.loads(row["tags"]) if row["tags"] else []
            return {
                "id": row["id"],
                "content": content[:200] + ("..." if len(content) > 200 else ""),
                "importance": importance,
                "status": status,
                "tags": tags,
                "_tier": 2,
            }

        if is_important:
            # Tier 3: 완료 + 중요 → 힌트 수준 내용
            return {
                "id": row["id"],
                "content": content[:80] + ("..." if len(content) > 80 else ""),
                "importance": importance,
                "status": status,
                "_tier": 3,
            }

        # Tier 4: 완료 + 일반 → 존재 여부만
        return self._pin_row_to_minimal(row)

    def _pin_row_to_minimal(self, row) -> Dict[str, Any]:
        """
        DB row를 최소 핀 정보로 변환 (smart expand에서 completed + 낮은 중요도 핀용).

        content를 포함하지 않아 토큰을 최대한 절약.
        """
        return {
            "id": row["id"],
            "importance": row["importance"],
            "status": row["status"],
            "_tier": 4,
        }

    async def _generate_narrative_summary(self, session_id: str) -> str:
        """세션 요약 생성 — 통계 + 주요 작업 미리보기"""
        stats_row = await self.db.fetchone(
            """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN importance >= 4 THEN 1 ELSE 0 END) as high_importance
            FROM pins
            WHERE session_id = ?
            """,
            (session_id,),
        )

        total = stats_row["total"] or 0
        completed = stats_row["completed"] or 0
        high_importance = stats_row["high_importance"] or 0

        if total == 0:
            return "세션 완료: 작업 없음"

        summary = f"세션 완료: {completed}/{total} pins 완료"
        if high_importance > 0:
            summary += f" (중요 작업 {high_importance}건 포함)"

        # 미완료 작업이 있으면 첫 번째만 표시
        if completed < total:
            incomplete_row = await self.db.fetchone(
                """
                SELECT content FROM pins
                WHERE session_id = ? AND status != 'completed'
                ORDER BY importance DESC
                LIMIT 1
                """,
                (session_id,),
            )
            if incomplete_row and incomplete_row["content"]:
                preview = incomplete_row["content"][:50]
                summary += f". 미완료: {preview}"

        return summary

    async def resume_with_token_tracking(
        self,
        project_id: str,
        user_id: Optional[str] = None,
        expand: Union[bool, str] = False,
        limit: int = 10,
    ) -> Tuple[Optional[SessionContext], Dict[str, int]]:
        """
        토큰 추적과 함께 세션 재개

        Args:
            project_id: 프로젝트 ID
            user_id: 사용자 ID
            expand: True=전체, False=compact, "smart"=open/in_progress만 전체
            limit: 반환할 pin 개수

        Returns:
            (session_context, token_info)
            token_info = {
                "loaded_tokens": int,
                "unloaded_tokens": int,
                "estimated_total": int
            }
        """
        from app.core.services.token_tracker import TokenTracker

        # 기존 resume_last_session 호출
        session_context = await self.resume_last_session(
            project_id=project_id, user_id=user_id, expand=expand, limit=limit
        )

        if not session_context:
            # 세션이 없으면 토큰 정보도 0으로 반환
            return None, {
                "loaded_tokens": 0,
                "unloaded_tokens": 0,
                "estimated_total": 0,
            }

        # TokenTracker 초기화
        token_tracker = TokenTracker(self.db)

        # 로드된 컨텐츠의 토큰 수 계산
        loaded_tokens = 0

        # 세션 요약 토큰
        if session_context.summary:
            loaded_tokens += await token_tracker.estimate_tokens(
                session_context.summary
            )

        # 핀 내용 토큰 계산 (expand 모드에 따라 다름)
        if expand == "smart" and session_context.pins:
            # smart: 각 Tier의 반환된 content 기준으로 loaded 토큰 계산
            for pin in session_context.pins:
                if isinstance(pin, dict):
                    content = pin.get("content", "")
                    if content:
                        loaded_tokens += await token_tracker.estimate_tokens(content)
                else:
                    loaded_tokens += await token_tracker.estimate_tokens(pin.content)
        elif expand and session_context.pins:
            for pin in session_context.pins:
                loaded_tokens += await token_tracker.estimate_tokens(pin.content)

        # 로드되지 않은 핀들의 예상 토큰 수 계산 (SQL 기반, 재쿼리 없음)
        unloaded_tokens = 0
        is_optimized = expand != True  # noqa: E712 — smart와 False 모두 최적화 적용

        if is_optimized and session_context.pins_count > 0:
            if expand == "smart":
                # SQL로 tier별 unloaded 문자 수 집계 (개별 row fetch 없이)
                row = await self.db.fetchone(
                    """
                    SELECT SUM(
                        CASE
                            WHEN status IN ('open','in_progress') AND COALESCE(importance,3) >= 4
                                THEN 0
                            WHEN status IN ('open','in_progress')
                                THEN MAX(0, LENGTH(content) - 200)
                            WHEN COALESCE(importance,3) >= 4
                                THEN MAX(0, LENGTH(content) - 80)
                            ELSE LENGTH(content)
                        END
                    ) as unloaded_chars
                    FROM pins WHERE session_id = ?
                    """,
                    (session_context.session_id,),
                )
                unloaded_chars = (
                    row["unloaded_chars"] if row and row["unloaded_chars"] else 0
                )
                # 문자 → 토큰 근사 (영문 ~4 chars/token, 한국어 ~2 chars/token, 혼합 ~3)
                unloaded_tokens = max(0, unloaded_chars // 3)
            else:
                # expand=false: 모든 핀의 full content를 unloaded로 카운트
                row = await self.db.fetchone(
                    """
                    SELECT SUM(LENGTH(content)) as total_chars
                    FROM pins WHERE session_id = ?
                    """,
                    (session_context.session_id,),
                )
                total_chars = row["total_chars"] if row and row["total_chars"] else 0
                unloaded_tokens = max(0, total_chars // 3)

        estimated_total = loaded_tokens + unloaded_tokens

        # 토큰 사용량 기록
        await token_tracker.record_session_tokens(
            session_id=session_context.session_id,
            loaded_tokens=loaded_tokens,
            unloaded_tokens=unloaded_tokens,
            event_type="resume",
            context_depth=limit,
        )

        # token_usage 테이블에도 기록
        await token_tracker.record_token_usage(
            project_id=project_id,
            operation_type="session_resume",
            tokens_used=loaded_tokens,
            session_id=session_context.session_id,
            tokens_saved=unloaded_tokens,
            optimization_applied=is_optimized,
        )

        token_info = {
            "loaded_tokens": loaded_tokens,
            "unloaded_tokens": unloaded_tokens,
            "estimated_total": estimated_total,
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
        auto_promote_threshold: int = 4,
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
        from app.core.services.pin import PinService
        from app.core.services.token_tracker import TokenTracker

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
                    "savings_rate": 0.0,
                },
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
            (session_id, auto_promote_threshold),
        )

        # 핀 승격 처리
        pin_service = PinService(self.db, self._embedding_service)
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
            session_id=session_id, loaded_tokens=0, unloaded_tokens=0, event_type="end"
        )

        logger.info(
            f"Session {session_id} ended with auto-promotion: "
            f"{len(promoted_pins)} pins promoted, "
            f"token savings: {token_savings['savings_rate']:.2%}"
        )

        return {
            "session": session,
            "promoted_pins": promoted_pins,
            "token_savings": token_savings,
        }

    async def get_session_statistics(
        self,
        project_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
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
            tuple(params),
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
            tuple(params),
        )

        total_pins = pin_stats["total_pins"] or 0
        sessions_with_pins = pin_stats["sessions_with_pins"] or 1  # 0으로 나누기 방지
        avg_pins_per_session = (
            total_pins / sessions_with_pins if sessions_with_pins > 0 else 0.0
        )

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
            tuple(params),
        )

        importance_distribution = {
            row["importance"]: row["count"] for row in importance_rows
        }

        # 4. 평균 토큰 절감률
        token_tracker = TokenTracker(self.db)

        # 프로젝트별 토큰 통계 조회
        if project_id:
            token_stats = await token_tracker.get_project_token_statistics(
                project_id=project_id, start_date=start_date, end_date=end_date
            )
            avg_token_savings_rate = token_stats.get("avg_savings_rate", 0.0)
        else:
            # 전체 프로젝트의 평균 계산
            all_sessions = await self.db.fetchall(
                f"""
                SELECT id FROM sessions s
                WHERE {where_clause}
                """,
                tuple(params),
            )

            if all_sessions:
                total_savings_rate = 0.0
                valid_sessions = 0

                for session_row in all_sessions:
                    try:
                        savings = await token_tracker.calculate_savings(
                            session_row["id"]
                        )
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
            "avg_token_savings_rate": round(avg_token_savings_rate, 4),
        }

        logger.info(
            f"Session statistics calculated: "
            f"total={total_sessions}, avg_duration={avg_duration_hours:.2f}h, "
            f"avg_pins={avg_pins_per_session:.2f}, avg_savings={avg_token_savings_rate:.2%}"
        )

        return result
