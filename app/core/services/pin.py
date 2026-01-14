"""Pin 서비스 - Pin 관리 비즈니스 로직"""

import logging
import json
from datetime import datetime, timezone
from typing import Optional, List
from uuid import uuid4

from app.core.database.base import Database
from app.core.schemas.pins import PinCreate, PinUpdate, PinResponse
from app.core.utils.user import get_current_user

logger = logging.getLogger(__name__)


class InvalidStatusTransitionError(Exception):
    """유효하지 않은 상태 전이"""
    pass


class PinNotFoundError(Exception):
    """Pin을 찾을 수 없음"""
    pass


class PinAlreadyCompletedError(Exception):
    """이미 완료된 Pin"""
    pass


# 유효한 상태 전이 정의
VALID_TRANSITIONS = {
    "open": {"open", "in_progress"},
    "in_progress": {"in_progress", "completed"},
    "completed": {"completed"},
}


class PinService:
    """Pin 관리 서비스"""
    
    def __init__(self, db: Database):
        self.db = db
        # SessionService는 순환 참조 방지를 위해 lazy import
        self._session_service = None
    
    @property
    def session_service(self):
        if self._session_service is None:
            from app.core.services.session import SessionService
            self._session_service = SessionService(self.db)
        return self._session_service
    
    async def create_pin(
        self,
        project_id: str,
        content: str,
        importance: Optional[int] = None,
        tags: Optional[List[str]] = None,
        user_id: Optional[str] = None
    ) -> PinResponse:
        """
        새 Pin 생성.
        
        Args:
            project_id: 프로젝트 ID
            content: Pin 내용
            importance: 중요도 (1-5, None이면 기본값 3)
            tags: 태그 목록
            user_id: 사용자 ID
            
        Returns:
            PinResponse
        """
        effective_user_id = user_id or get_current_user()
        
        # 활성 세션 가져오기 (없으면 자동 생성)
        session = await self.session_service.get_or_create_active_session(
            project_id, effective_user_id
        )
        
        # 중요도 기본값
        effective_importance = importance if importance is not None else 3
        
        pin_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        tags_json = json.dumps(tags) if tags else None
        
        await self.db.execute(
            """
            INSERT INTO pins (
                id, session_id, project_id, user_id, content, 
                importance, status, tags, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (pin_id, session.id, project_id, effective_user_id, content,
             effective_importance, tags_json, now, now)
        )
        self.db.connection.commit()
        
        logger.info(f"Created pin: {pin_id} in session: {session.id}")
        
        return PinResponse(
            id=pin_id,
            session_id=session.id,
            project_id=project_id,
            user_id=effective_user_id,
            content=content,
            importance=effective_importance,
            status="open",
            tags=tags or [],
            completed_at=None,
            lead_time_hours=None,
            created_at=now,
            updated_at=now,
        )
    
    async def get_pin(self, pin_id: str) -> Optional[PinResponse]:
        """Pin 조회"""
        row = await self.db.fetchone(
            "SELECT * FROM pins WHERE id = ?",
            (pin_id,)
        )
        
        if not row:
            return None
        
        return self._row_to_response(row)
    
    async def update_pin(
        self,
        pin_id: str,
        update: PinUpdate
    ) -> Optional[PinResponse]:
        """Pin 업데이트"""
        pin = await self.get_pin(pin_id)
        if not pin:
            return None
        
        # 상태 전이 검증
        if update.status and update.status != pin.status:
            if update.status not in VALID_TRANSITIONS.get(pin.status, set()):
                raise InvalidStatusTransitionError(
                    f"Cannot transition from '{pin.status}' to '{update.status}'"
                )
        
        updates = []
        params = []
        
        update_data = update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                if field == "tags":
                    updates.append("tags = ?")
                    params.append(json.dumps(value))
                else:
                    updates.append(f"{field} = ?")
                    params.append(value)
        
        if not updates:
            return pin
        
        now = datetime.now(timezone.utc).isoformat()
        updates.append("updated_at = ?")
        params.append(now)
        params.append(pin_id)
        
        await self.db.execute(
            f"UPDATE pins SET {', '.join(updates)} WHERE id = ?",
            tuple(params)
        )
        self.db.connection.commit()
        
        return await self.get_pin(pin_id)
    
    async def complete_pin(self, pin_id: str) -> PinResponse:
        """
        Pin 완료 처리.
        
        Args:
            pin_id: Pin ID
            
        Returns:
            PinResponse (suggest_promotion 포함)
            
        Raises:
            PinNotFoundError: Pin이 없을 때
            PinAlreadyCompletedError: 이미 완료된 Pin
            InvalidStatusTransitionError: 유효하지 않은 전이
        """
        pin = await self.get_pin(pin_id)
        if not pin:
            raise PinNotFoundError(f"Pin not found: {pin_id}")
        
        if pin.status == "completed":
            raise PinAlreadyCompletedError(f"Pin already completed: {pin_id}")
        
        # open → completed는 허용 (in_progress 건너뛰기)
        if pin.status not in ("open", "in_progress"):
            raise InvalidStatusTransitionError(
                f"Cannot complete pin with status '{pin.status}'"
            )
        
        now = datetime.now(timezone.utc).isoformat()
        
        await self.db.execute(
            """
            UPDATE pins 
            SET status = 'completed', completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, pin_id)
        )
        self.db.connection.commit()
        
        logger.info(f"Completed pin: {pin_id}")
        
        return await self.get_pin(pin_id)
    
    async def promote_to_memory(self, pin_id: str) -> dict:
        """
        Pin을 Memory로 승격.
        
        Args:
            pin_id: Pin ID
            
        Returns:
            {"memory_id": str, "pin_deleted": bool}
        """
        pin = await self.get_pin(pin_id)
        if not pin:
            raise PinNotFoundError(f"Pin not found: {pin_id}")
        
        # Memory 생성 (MemoryService 사용)
        from app.core.services.memory import MemoryService
        from app.core.embeddings.service import EmbeddingService
        from app.core.config import get_settings
        
        settings = get_settings()
        embedding_service = EmbeddingService(settings)
        memory_service = MemoryService(self.db, embedding_service)
        
        # Memory 생성
        memory_response = await memory_service.create(
            content=pin.content,
            project_id=pin.project_id,
            category="task",  # Pin은 기본적으로 task
            source="pin_promotion",
            tags=pin.tags,
        )
        
        # Pin 삭제
        await self.delete_pin(pin_id)
        
        logger.info(f"Promoted pin {pin_id} to memory {memory_response.id}")
        
        return {
            "memory_id": memory_response.id,
            "pin_deleted": True,
        }
    
    async def delete_pin(self, pin_id: str) -> bool:
        """Pin 삭제"""
        pin = await self.get_pin(pin_id)
        if not pin:
            return False
        
        await self.db.execute(
            "DELETE FROM pins WHERE id = ?",
            (pin_id,)
        )
        self.db.connection.commit()
        
        logger.info(f"Deleted pin: {pin_id}")
        return True
    
    async def get_pins_by_session(
        self,
        session_id: str,
        limit: int = 10,
        order_by_importance: bool = True
    ) -> List[PinResponse]:
        """세션별 Pin 목록 조회"""
        order = "importance DESC, created_at DESC" if order_by_importance else "created_at DESC"
        
        rows = await self.db.fetchall(
            f"""
            SELECT * FROM pins
            WHERE session_id = ?
            ORDER BY {order}
            LIMIT ?
            """,
            (session_id, limit)
        )
        
        return [self._row_to_response(row) for row in rows]
    
    async def get_pins_by_project(
        self,
        project_id: str,
        status: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 10,
        order_by_importance: bool = True
    ) -> List[PinResponse]:
        """프로젝트별 Pin 목록 조회"""
        query = "SELECT * FROM pins WHERE project_id = ?"
        params = [project_id]
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        
        order = "importance DESC, created_at DESC" if order_by_importance else "created_at DESC"
        query += f" ORDER BY {order} LIMIT ?"
        params.append(limit)
        
        rows = await self.db.fetchall(query, tuple(params))
        return [self._row_to_response(row) for row in rows]
    
    async def get_pins(
        self,
        project_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        order_by_importance: bool = True
    ) -> List[PinResponse]:
        """범용 Pin 목록 조회"""
        query = "SELECT * FROM pins WHERE 1=1"
        params = []
        
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        order = "importance DESC, created_at DESC" if order_by_importance else "created_at DESC"
        query += f" ORDER BY {order} LIMIT ?"
        params.append(limit)
        
        rows = await self.db.fetchall(query, tuple(params))
        return [self._row_to_response(row) for row in rows]
    
    def _row_to_response(self, row) -> PinResponse:
        """DB row를 PinResponse로 변환"""
        tags = []
        if row['tags']:
            try:
                tags = json.loads(row['tags'])
            except json.JSONDecodeError:
                tags = []
        
        # lead_time 계산
        lead_time_hours = None
        if row['completed_at'] and row['created_at']:
            try:
                created = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
                completed = datetime.fromisoformat(row['completed_at'].replace('Z', '+00:00'))
                lead_time_hours = (completed - created).total_seconds() / 3600
            except Exception:
                pass
        
        return PinResponse(
            id=row['id'],
            session_id=row['session_id'],
            project_id=row['project_id'],
            user_id=row['user_id'],
            content=row['content'],
            importance=row['importance'],
            status=row['status'],
            tags=tags,
            completed_at=row['completed_at'],
            lead_time_hours=lead_time_hours,
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )
    
    def should_suggest_promotion(self, pin: PinResponse) -> bool:
        """승격 제안 여부 판단"""
        return pin.status == "completed" and pin.importance >= 4
