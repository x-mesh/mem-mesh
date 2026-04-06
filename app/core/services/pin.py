"""Pin 서비스 - Pin 관리 비즈니스 로직"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from app.core.services.session import SessionService

from uuid import uuid4

from app.core.database.base import Database
from app.core.errors import (
    InvalidStatusTransitionError,
    PinAlreadyCompletedError,
    PinNotFoundError,
)
from app.core.schemas.pins import PinResponse, PinUpdate
from app.core.utils.user import get_current_user

logger = logging.getLogger(__name__)


def _parse_tags(raw: object) -> List[str]:
    """DB에서 읽은 tags 값을 List[str]로 안전 변환.

    Cases:
      - None / empty → []
      - JSON array string '["a","b"]' → ["a", "b"]
      - JSON-encoded string '"a, b"'  → ["a", "b"]  (split by comma)
      - Plain string 'a, b'          → ["a", "b"]  (split by comma)
    """
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(t) for t in raw]
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = raw
    if isinstance(parsed, list):
        return [str(t) for t in parsed]
    if isinstance(parsed, str):
        return [t.strip() for t in parsed.split(",") if t.strip()]
    return []




# 유효한 상태 전이 정의 (Kanban 드래그 앤 드롭을 위해 모든 전이 허용)
VALID_TRANSITIONS = {
    "open": {"open", "in_progress", "completed"},
    "in_progress": {"open", "in_progress", "completed"},
    "completed": {"open", "in_progress", "completed"},
}


class PinService:
    """Pin 관리 서비스"""

    def __init__(self, db: Database, embedding_service=None):
        self.db = db
        self._embedding_service = embedding_service
        # SessionService는 순환 참조 방지를 위해 lazy import
        self._session_service = None

    @property
    def session_service(self) -> "SessionService":
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
        user_id: Optional[str] = None,
        auto_importance: bool = False,
        ide_session_id: Optional[str] = None,
        client_type: Optional[str] = None,
        client: Optional[str] = None,
        is_staging: bool = False,
    ) -> PinResponse:
        """
        새 Pin 생성.

        Args:
            project_id: 프로젝트 ID
            content: Pin 내용
            importance: 중요도 (1-5, None이면 기본값 3)
            tags: 태그 목록
            user_id: 사용자 ID
            auto_importance: 자동 중요도 추정 여부
            ide_session_id: IDE 네이티브 세션 ID
            client_type: IDE/도구 유형

        Returns:
            PinResponse
        """
        effective_user_id = user_id or get_current_user()

        if not client:
            client = os.environ.get("MEM_MESH_CLIENT") or client_type

        # 활성 세션 가져오기 (없으면 자동 생성)
        session = await self.session_service.get_or_create_active_session(
            project_id, effective_user_id,
            ide_session_id=ide_session_id,
            client_type=client_type,
        )

        # 중요도 기본값
        effective_importance = importance if importance is not None else 3

        pin_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        # Normalize tags: ensure it's always a list before storing
        normalized_tags = _parse_tags(tags) if tags else []
        tags_json = json.dumps(normalized_tags) if normalized_tags else None

        await self.db.execute(
            """
            INSERT INTO pins (
                id, session_id, project_id, user_id, content,
                importance, status, tags, auto_importance, client, is_staging, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'in_progress', ?, ?, ?, ?, ?, ?)
            """,
            (
                pin_id,
                session.id,
                project_id,
                effective_user_id,
                content,
                effective_importance,
                tags_json,
                1 if auto_importance else 0,
                client,
                1 if is_staging else 0,
                now,
                now,
            ),
        )
        self.db.connection.commit()

        logger.info(f"Created pin: {pin_id} in session: {session.id}")

        return PinResponse(
            id=pin_id,
            session_id=session.id,
            project_id=project_id,
            user_id=effective_user_id,
            client=client,
            content=content,
            importance=effective_importance,
            status="in_progress",
            tags=tags or [],
            completed_at=None,
            lead_time_hours=None,
            auto_importance=auto_importance,
            is_staging=is_staging,
            created_at=now,
            updated_at=now,
        )

    async def get_pin(self, pin_id: str) -> Optional[PinResponse]:
        """Pin 조회"""
        row = await self.db.fetchone("SELECT * FROM pins WHERE id = ?", (pin_id,))

        if not row:
            return None

        return self._row_to_response(row)

    async def update_pin(self, pin_id: str, update: PinUpdate) -> Optional[PinResponse]:
        """Pin 업데이트"""
        pin = await self.get_pin(pin_id)
        if not pin:
            return None

        # 상태 전이 검증
        if update.status and update.status != pin.status:
            if update.status not in VALID_TRANSITIONS.get(pin.status, set()):
                raise InvalidStatusTransitionError(pin.status, update.status)

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

        # status→completed: completed_at 자동 설정
        if update.status == "completed" and pin.status != "completed":
            now_ts = datetime.now(timezone.utc).isoformat()
            updates.append("completed_at = ?")
            params.append(now_ts)
        # completed→다른 상태: completed_at 클리어
        elif update.status and update.status != "completed" and pin.status == "completed":
            updates.append("completed_at = ?")
            params.append(None)

        if not updates:
            return pin

        now = datetime.now(timezone.utc).isoformat()
        updates.append("updated_at = ?")
        params.append(now)
        params.append(pin_id)

        await self.db.execute(
            f"UPDATE pins SET {', '.join(updates)} WHERE id = ?", tuple(params)
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
            raise InvalidStatusTransitionError(pin.status, "completed")

        now = datetime.now(timezone.utc).isoformat()

        await self.db.execute(
            """
            UPDATE pins
            SET status = 'completed', completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, pin_id),
        )
        self.db.connection.commit()

        logger.info(f"Completed pin: {pin_id}")

        # 재쿼리 없이 기존 pin 데이터로 응답 구성
        lead_time_hours = None
        if pin.created_at:
            try:
                created = datetime.fromisoformat(pin.created_at.replace("Z", "+00:00"))
                completed = datetime.fromisoformat(now.replace("Z", "+00:00"))
                lead_time_hours = (completed - created).total_seconds() / 3600
            except Exception:
                pass

        return PinResponse(
            id=pin.id,
            session_id=pin.session_id,
            project_id=pin.project_id,
            user_id=pin.user_id,
            client=pin.client,
            content=pin.content,
            importance=pin.importance,
            status="completed",
            tags=pin.tags,
            created_at=pin.created_at,
            completed_at=now,
            updated_at=now,
            lead_time_hours=lead_time_hours,
            estimated_tokens=pin.estimated_tokens,
            promoted_to_memory_id=pin.promoted_to_memory_id,
            auto_importance=pin.auto_importance,
        )

    async def promote_to_memory(self, pin_id: str, category: str = "task") -> dict:
        """
        Pin을 Memory로 승격.

        Args:
            pin_id: Pin ID
            category: Memory 카테고리 (task, decision, bug, incident, idea, code_snippet)

        Returns:
            {"memory_id": str, "pin_deleted": bool, "message": str, "already_promoted": bool}

        Raises:
            PinNotFoundError: Pin이 없을 때
        """
        pin = await self.get_pin(pin_id)
        if not pin:
            raise PinNotFoundError(f"Pin not found: {pin_id}")

        # 중복 승격 방지: 이미 승격된 핀인지 확인
        if pin.promoted_to_memory_id:
            logger.info(
                f"Pin {pin_id} already promoted to memory {pin.promoted_to_memory_id}"
            )
            return {
                "memory_id": pin.promoted_to_memory_id,
                "pin_deleted": False,
                "message": f"Pin이 이미 Memory로 승격되었습니다 (ID: {pin.promoted_to_memory_id})",
                "already_promoted": True,
            }

        # Memory 생성 (MemoryService 사용)
        from app.core.embeddings.service import EmbeddingService
        from app.core.services.memory import MemoryService

        # EmbeddingService: DI된 인스턴스 재사용, 없으면 새로 생성
        embedding_service = self._embedding_service or EmbeddingService(preload=False)
        memory_service = MemoryService(self.db, embedding_service)

        # importance를 tags에 보존 (Memory에는 importance 필드가 없음)
        promote_tags = list(pin.tags) if pin.tags else []
        promote_tags.append(f"importance:{pin.importance}")

        # Memory 생성 → Pin 업데이트 (Memory 생성 실패 시 Pin 변경 없음)
        now = datetime.now(timezone.utc).isoformat()
        memory_response = await memory_service.create(
            content=pin.content,
            project_id=pin.project_id,
            category=category,
            source="pin_promotion",
            tags=promote_tags,
            skip_quality_gate=True,
        )

        # Pin에 promoted_to_memory_id 기록 (삭제하지 않고 유지)
        await self.db.execute(
            """
            UPDATE pins
            SET promoted_to_memory_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (memory_response.id, now, pin_id),
        )
        self.db.connection.commit()

        logger.info(f"Promoted pin {pin_id} to memory {memory_response.id}")

        # 자동 관계 생성 (트랜잭션 밖 — 실패해도 승격은 유지)
        auto_linked = await self._auto_link_session_memories(
            pin.session_id, memory_response.id
        )
        if auto_linked > 0:
            logger.info(
                f"Auto-linked {auto_linked} related memories from session {pin.session_id}"
            )

        return {
            "memory_id": memory_response.id,
            "pin_deleted": False,
            "message": f"Pin이 Memory로 승격되었습니다 (ID: {memory_response.id})",
            "already_promoted": False,
        }

    async def _auto_link_session_memories(
        self, session_id: str, new_memory_id: str
    ) -> int:
        """같은 세션에서 이미 promote된 다른 pin의 memory와 자동 related 관계 생성"""
        try:
            rows = await self.db.fetchall(
                """
                SELECT promoted_to_memory_id FROM pins
                WHERE session_id = ?
                AND promoted_to_memory_id IS NOT NULL
                AND promoted_to_memory_id != ?
                """,
                (session_id, new_memory_id),
            )

            if not rows:
                return 0

            from app.core.schemas.relations import RelationCreate, RelationType
            from app.core.services.relation import RelationService

            relation_service = RelationService(self.db)
            linked_count = 0

            for row in rows:
                existing_memory_id = row["promoted_to_memory_id"]
                try:
                    _, created = await relation_service.find_or_create_relation(
                        RelationCreate(
                            source_id=new_memory_id,
                            target_id=existing_memory_id,
                            relation_type=RelationType.RELATED,
                            strength=0.8,
                            metadata={"auto_linked": True, "session_id": session_id},
                        )
                    )
                    if created:
                        linked_count += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to auto-link {new_memory_id} -> {existing_memory_id}: {e}"
                    )

            return linked_count
        except Exception as e:
            logger.warning(f"Auto-link session memories failed: {e}")
            return 0

    async def delete_pin(self, pin_id: str) -> bool:
        """Pin 삭제"""
        pin = await self.get_pin(pin_id)
        if not pin:
            return False

        await self.db.execute("DELETE FROM pins WHERE id = ?", (pin_id,))
        self.db.connection.commit()

        logger.info(f"Deleted pin: {pin_id}")
        return True

    async def get_pins_by_session(
        self, session_id: str, limit: int = 10, order_by_importance: bool = True
    ) -> List[PinResponse]:
        """세션별 Pin 목록 조회"""
        order = (
            "importance DESC, created_at DESC"
            if order_by_importance
            else "created_at DESC"
        )

        rows = await self.db.fetchall(
            f"""
            SELECT * FROM pins
            WHERE session_id = ?
            ORDER BY {order}
            LIMIT ?
            """,
            (session_id, limit),
        )

        return [self._row_to_response(row) for row in rows]

    async def get_pins_by_project(
        self,
        project_id: str,
        status: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 10,
        order_by_importance: bool = True,
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

        order = (
            "importance DESC, created_at DESC"
            if order_by_importance
            else "created_at DESC"
        )
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
        order_by_importance: bool = True,
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

        order = (
            "importance DESC, created_at DESC"
            if order_by_importance
            else "created_at DESC"
        )
        query += f" ORDER BY {order} LIMIT ?"
        params.append(limit)

        rows = await self.db.fetchall(query, tuple(params))
        return [self._row_to_response(row) for row in rows]

    def _row_to_response(self, row) -> PinResponse:
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

        # 새로운 컬럼 안전하게 접근
        try:
            estimated_tokens = (
                row["estimated_tokens"] if row["estimated_tokens"] is not None else 0
            )
        except (KeyError, IndexError):
            estimated_tokens = 0

        try:
            promoted_to_memory_id = row["promoted_to_memory_id"]
        except (KeyError, IndexError):
            promoted_to_memory_id = None

        try:
            auto_importance = bool(row["auto_importance"])
        except (KeyError, IndexError):
            auto_importance = False

        try:
            client = row["client"]
        except (KeyError, IndexError):
            client = None

        return PinResponse(
            id=row["id"],
            session_id=row["session_id"],
            project_id=row["project_id"],
            user_id=row["user_id"],
            client=client,
            content=row["content"],
            importance=row["importance"],
            status=row["status"],
            tags=tags,
            completed_at=row["completed_at"],
            lead_time_hours=lead_time_hours,
            estimated_tokens=estimated_tokens,
            promoted_to_memory_id=promoted_to_memory_id,
            auto_importance=auto_importance,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def should_suggest_promotion(self, pin: PinResponse) -> bool:
        """승격 제안 여부 판단"""
        return pin.status == "completed" and pin.importance >= 4

    async def get_pins_filtered(
        self,
        session_id: str,
        min_importance: Optional[int] = None,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[PinResponse]:
        """
        필터링된 핀 목록 조회.

        Args:
            session_id: 세션 ID
            min_importance: 최소 중요도 (1-5)
            status: 상태 필터 ('open', 'in_progress', 'completed')
            tags: 태그 필터 (AND 조건)
            limit: 결과 개수

        Returns:
            필터링된 핀 목록 (created_at 기준 내림차순)
        """
        query = "SELECT * FROM pins WHERE session_id = ?"
        params = [session_id]

        # importance 필터
        if min_importance is not None:
            query += " AND importance >= ?"
            params.append(min_importance)

        # status 필터
        if status:
            query += " AND status = ?"
            params.append(status)

        # tags 필터 (AND 조건)
        if tags:
            for tag in tags:
                # JSON 배열에서 태그 검색
                query += " AND tags LIKE ?"
                params.append(f'%"{tag}"%')

        # 정렬 및 제한
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = await self.db.fetchall(query, tuple(params))
        return [self._row_to_response(row) for row in rows]

    async def get_pin_statistics(self, session_id: str) -> dict:
        """
        세션의 핀 통계 조회 (SQL GROUP BY 최적화).

        Args:
            session_id: 세션 ID

        Returns:
            {
                "total": int,
                "by_status": {"open": int, "in_progress": int, "completed": int},
                "by_importance": {1: int, 2: int, 3: int, 4: int, 5: int},
                "avg_lead_time_hours": float,
                "promotion_candidates": int
            }
        """
        # 상태별 집계
        status_rows = await self.db.fetchall(
            "SELECT status, COUNT(*) as cnt FROM pins WHERE session_id = ? GROUP BY status",
            (session_id,),
        )
        by_status = {"open": 0, "in_progress": 0, "completed": 0}
        total = 0
        for row in status_rows:
            by_status[row["status"]] = row["cnt"]
            total += row["cnt"]

        # 중요도별 집계
        importance_rows = await self.db.fetchall(
            "SELECT importance, COUNT(*) as cnt FROM pins WHERE session_id = ? GROUP BY importance",
            (session_id,),
        )
        by_importance = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for row in importance_rows:
            by_importance[row["importance"]] = row["cnt"]

        # 평균 lead time + 승격 후보 (단일 쿼리)
        agg_row = await self.db.fetchone(
            """
            SELECT
                AVG(
                    CASE WHEN status = 'completed' AND completed_at IS NOT NULL
                    THEN (julianday(completed_at) - julianday(created_at)) * 24.0
                    END
                ) as avg_lead_time,
                SUM(CASE WHEN status = 'completed' AND importance >= 4
                    AND promoted_to_memory_id IS NULL THEN 1 ELSE 0 END) as promo_candidates
            FROM pins WHERE session_id = ?
            """,
            (session_id,),
        )

        avg_lead_time_hours = (
            agg_row["avg_lead_time"]
            if agg_row and agg_row["avg_lead_time"] is not None
            else None
        )
        promotion_candidates = (
            agg_row["promo_candidates"]
            if agg_row and agg_row["promo_candidates"] is not None
            else 0
        )

        return {
            "total": total,
            "by_status": by_status,
            "by_importance": by_importance,
            "avg_lead_time_hours": avg_lead_time_hours,
            "promotion_candidates": promotion_candidates,
        }
