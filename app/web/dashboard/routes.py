"""
Dashboard REST API 라우터.

메모리 관리, 검색, 통계, 임베딩 관리 등의 API 엔드포인트를 제공합니다.
"""

import json
import logging
from fastapi import APIRouter, HTTPException, Depends

from app.core.services.memory import MemoryService, MemoryNotFoundError
from app.core.services.search import SearchService
from app.core.services.context import ContextService, ContextNotFoundError
from app.core.services.stats import StatsService
from app.core.services.embedding_manager import EmbeddingManagerService
from app.core.services.project import ProjectService
from app.core.services.session import SessionService, NoActiveSessionError
from app.core.services.pin import PinService, PinNotFoundError, InvalidStatusTransitionError
from app.core.schemas.requests import AddParams, SearchParams, UpdateParams
from app.core.schemas.pins import PinCreate, PinUpdate
from app.core.schemas.projects import ProjectUpdate
from app.core.schemas.responses import (
    AddResponse, SearchResponse, ContextResponse, 
    UpdateResponse, DeleteResponse, StatsResponse
)
from ..common.dependencies import (
    get_memory_service, get_search_service, get_context_service,
    get_stats_service, get_embedding_manager,
    get_project_service, get_session_service, get_pin_service
)

logger = logging.getLogger(__name__)

# API 라우터 생성
router = APIRouter(prefix="/api", tags=["Dashboard API"])


@router.get("/")
async def api_root():
    """API 루트 엔드포인트"""
    return {
        "name": "mem-mesh",
        "description": "Central memory server with vector search",
        "version": "1.0.0",
        "status": "running"
    }


@router.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy", "timestamp": "2026-01-11T12:30:00Z"}


@router.post("/memories", response_model=AddResponse)
async def add_memory(
    params: AddParams,
    service: MemoryService = Depends(get_memory_service)
) -> AddResponse:
    """메모리 추가"""
    try:
        result = await service.create(
            content=params.content,
            project_id=params.project_id,
            category=params.category,
            source=params.source or "api",
            tags=params.tags
        )
        
        # WebSocket 실시간 알림 전송 - 완전한 메모리 데이터 조회 후 전송
        try:
            from ..websocket.realtime import notifier
            # 생성된 메모리의 완전한 데이터 조회
            memory = await service.get(result.id)
            if memory:
                memory_data = {
                    "id": memory.id,
                    "content": memory.content,
                    "project_id": memory.project_id,
                    "category": memory.category,
                    "tags": json.loads(memory.tags) if memory.tags else [],
                    "source": memory.source,
                    "created_at": memory.created_at,
                    "updated_at": memory.updated_at
                }
                await notifier.notify_memory_created(memory_data)
        except Exception as e:
            logger.warning(f"Failed to send WebSocket notification: {e}")
        
        return result
    except Exception as e:
        logger.error(f"Add memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/search", response_model=SearchResponse)
async def search_memories(
    query: str,
    project_id: str = None,
    category: str = None,
    source: str = None,
    tag: str = None,
    limit: int = 25,
    offset: int = 0,
    sort_by: str = "created_at",
    sort_direction: str = "desc",
    recency_weight: float = 0.0,
    search_mode: str = "hybrid",
    service: SearchService = Depends(get_search_service)
) -> SearchResponse:
    """
    메모리 검색
    
    search_mode 옵션:
    - hybrid: 벡터 + 텍스트 결합 검색 (기본값)
    - exact: 정확한 텍스트 매칭만
    - semantic: 의미 기반 벡터 검색만
    - fuzzy: 오타 허용 퍼지 검색
    
    정렬 옵션:
    - sort_by: created_at, updated_at, category, project, size
    - sort_direction: asc, desc
    """
    try:
        return await service.search(
            query=query,
            project_id=project_id,
            category=category,
            source=source,
            tag=tag,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_direction=sort_direction,
            recency_weight=recency_weight,
            search_mode=search_mode
        )
    except Exception as e:
        logger.error(f"Search memories error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/stats", response_model=StatsResponse)
async def get_memory_stats(
    project_id: str = None,
    start_date: str = None,
    end_date: str = None,
    service: StatsService = Depends(get_stats_service)
) -> StatsResponse:
    """메모리 통계 조회"""
    try:
        stats = await service.get_overall_stats(
            project_id=project_id,
            start_date=start_date,
            end_date=end_date
        )
        return StatsResponse(**stats)
    except Exception as e:
        logger.error(f"Get stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects")
async def get_projects(
    service: StatsService = Depends(get_stats_service)
):
    """
    프로젝트 목록 및 상세 통계 조회
    
    서버에서 SQL GROUP BY로 집계하여 반환하므로 효율적입니다.
    모든 메모리를 다운로드하지 않고 집계된 결과만 반환합니다.
    
    Returns:
        - projects: 프로젝트 상세 정보 리스트
        - total_projects: 총 프로젝트 수
        - total_memories: 총 메모리 수
    """
    try:
        projects = await service.get_projects_detail()
        
        total_memories = sum(p['memory_count'] for p in projects)
        
        return {
            'projects': projects,
            'total_projects': len(projects),
            'total_memories': total_memories,
            'avg_per_project': total_memories // len(projects) if len(projects) > 0 else 0
        }
    except Exception as e:
        logger.error(f"Get projects error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/{memory_id}")
async def get_memory(
    memory_id: str,
    service: MemoryService = Depends(get_memory_service)
):
    """개별 메모리 조회"""
    try:
        memory = await service.get(memory_id)
        if memory is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        
        return {
            "id": memory.id,
            "content": memory.content,
            "project_id": memory.project_id,
            "category": memory.category,
            "tags": memory.tags,
            "source": memory.source,
            "created_at": memory.created_at,
            "updated_at": memory.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/{memory_id}/context", response_model=ContextResponse)
async def get_memory_context(
    memory_id: str,
    depth: int = 2,
    project_id: str = None,
    service: ContextService = Depends(get_context_service)
) -> ContextResponse:
    """메모리 맥락 조회"""
    try:
        return await service.get_context(
            memory_id=memory_id,
            depth=depth,
            project_id=project_id
        )
    except ContextNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Get context error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/memories/{memory_id}", response_model=UpdateResponse)
async def update_memory(
    memory_id: str,
    params: UpdateParams,
    service: MemoryService = Depends(get_memory_service)
) -> UpdateResponse:
    """메모리 업데이트"""
    try:
        result = await service.update(
            memory_id=memory_id,
            content=params.content,
            category=params.category,
            tags=params.tags
        )
        
        # WebSocket 실시간 알림 전송 - 완전한 메모리 데이터 조회 후 전송
        try:
            from ..websocket.realtime import notifier
            # 업데이트된 메모리의 완전한 데이터 조회
            memory = await service.get(memory_id)
            if memory:
                memory_data = {
                    "id": memory.id,
                    "content": memory.content,
                    "project_id": memory.project_id,
                    "category": memory.category,
                    "tags": json.loads(memory.tags) if memory.tags else [],
                    "source": memory.source,
                    "created_at": memory.created_at,
                    "updated_at": memory.updated_at
                }
                await notifier.notify_memory_updated(memory_id, memory_data)
        except Exception as e:
            logger.warning(f"Failed to send WebSocket notification: {e}")
        
        return result
    except MemoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Update memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/memories/{memory_id}", response_model=DeleteResponse)
async def delete_memory(
    memory_id: str,
    service: MemoryService = Depends(get_memory_service)
) -> DeleteResponse:
    """메모리 삭제"""
    try:
        # 삭제 전에 메모리 정보 조회 (프로젝트 ID 확인용)
        try:
            memory_info = await service.get_by_id(memory_id)
            project_id = memory_info.project_id if memory_info else None
        except:
            project_id = None
        
        result = await service.delete(memory_id)
        
        # WebSocket 실시간 알림 전송
        try:
            from ..websocket.realtime import notifier
            await notifier.notify_memory_deleted(memory_id, project_id)
        except Exception as e:
            logger.warning(f"Failed to send WebSocket notification: {e}")
        
        return result
    except MemoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Delete memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Embedding Management API =====

@router.get("/embeddings/status")
async def get_embedding_status(
    manager: EmbeddingManagerService = Depends(get_embedding_manager)
):
    """
    임베딩 모델 상태 조회
    
    Returns:
        - stored_model: DB에 저장된 모델명
        - stored_dimension: DB에 저장된 차원
        - current_model: 현재 설정된 모델명
        - current_dimension: 현재 설정된 차원
        - total_memories: 총 메모리 수
        - vector_count: 벡터 테이블 레코드 수
        - needs_migration: 마이그레이션 필요 여부
        - migration_in_progress: 마이그레이션 진행 중 여부
    """
    try:
        status = await manager.get_status()
        return status
    except Exception as e:
        logger.error(f"Get embedding status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/embeddings/migrate")
async def start_embedding_migration(
    force: bool = False,
    batch_size: int = 100,
    manager: EmbeddingManagerService = Depends(get_embedding_manager)
):
    """
    임베딩 마이그레이션 시작
    
    Args:
        force: 모델이 같아도 강제 재임베딩
        batch_size: 배치 크기 (기본: 100)
    
    Returns:
        마이그레이션 결과 또는 진행 상황
    """
    try:
        result = await manager.start_migration(force=force, batch_size=batch_size)
        return result
    except Exception as e:
        logger.error(f"Start migration error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/embeddings/migration/progress")
async def get_migration_progress(
    manager: EmbeddingManagerService = Depends(get_embedding_manager)
):
    """마이그레이션 진행 상황 조회"""
    try:
        progress = manager.get_migration_progress()
        return progress
    except Exception as e:
        logger.error(f"Get migration progress error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Work Tracking API (Pins, Sessions, Projects) =====

@router.get("/work/projects")
async def list_work_projects(
    service: ProjectService = Depends(get_project_service)
):
    """
    Work Tracking 프로젝트 목록 조회 (통계 포함)
    """
    try:
        projects = await service.list_projects_with_stats()
        return {
            "projects": [p.dict() for p in projects],
            "total": len(projects)
        }
    except Exception as e:
        logger.error(f"List work projects error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/work/projects/{project_id}")
async def get_work_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service)
):
    """개별 프로젝트 조회"""
    try:
        project = await service.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project.dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get work project error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/work/projects/{project_id}")
async def create_or_get_work_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service)
):
    """프로젝트 생성 또는 조회"""
    try:
        project = await service.get_or_create_project(project_id)
        return project.dict()
    except Exception as e:
        logger.error(f"Create work project error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/work/projects/{project_id}")
async def update_work_project(
    project_id: str,
    update: ProjectUpdate,
    service: ProjectService = Depends(get_project_service)
):
    """프로젝트 업데이트"""
    try:
        project = await service.update_project(project_id, update)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project.dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update work project error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/work/projects/{project_id}/stats")
async def get_work_project_stats(
    project_id: str,
    stats_service: StatsService = Depends(get_stats_service)
):
    """프로젝트 통계 조회 (Pin/Session 통계)"""
    try:
        pin_stats = await stats_service.get_pin_stats(project_id=project_id)
        session_stats = await stats_service.get_session_stats(project_id=project_id)
        daily_completions = await stats_service.get_daily_pin_completions(project_id=project_id)
        
        return {
            "project_id": project_id,
            "pins": pin_stats,
            "sessions": session_stats,
            "daily_completions": daily_completions
        }
    except Exception as e:
        logger.error(f"Get work project stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Session API =====

@router.get("/work/sessions/resume/{project_id}")
async def resume_session(
    project_id: str,
    expand: bool = False,
    limit: int = 10,
    user_id: str = None,
    session_service: SessionService = Depends(get_session_service)
):
    """
    마지막 세션 컨텍스트 로드
    
    Args:
        project_id: 프로젝트 ID
        expand: True면 전체 pin 내용 반환, False면 요약만
        limit: 반환할 pin 개수 (기본 10개)
        user_id: 사용자 ID (선택)
    """
    try:
        context = await session_service.resume_last_session(
            project_id=project_id,
            user_id=user_id,
            expand=expand,
            limit=limit
        )
        return context.dict()
    except NoActiveSessionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Resume session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/work/sessions/{session_id}/end")
async def end_session(
    session_id: str,
    summary: str = None,
    session_service: SessionService = Depends(get_session_service)
):
    """세션 종료"""
    try:
        session = await session_service.end_session(session_id, summary)
        return session.dict()
    except Exception as e:
        logger.error(f"End session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/work/sessions")
async def list_sessions(
    project_id: str = None,
    user_id: str = None,
    status: str = None,
    limit: int = 20,
    session_service: SessionService = Depends(get_session_service)
):
    """세션 목록 조회"""
    try:
        sessions = await session_service.list_sessions(
            project_id=project_id,
            user_id=user_id,
            status=status,
            limit=limit
        )
        return {
            "sessions": [s.dict() for s in sessions],
            "total": len(sessions)
        }
    except Exception as e:
        logger.error(f"List sessions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Pin API =====

@router.post("/work/pins")
async def create_pin(
    pin: PinCreate,
    pin_service: PinService = Depends(get_pin_service),
    session_service: SessionService = Depends(get_session_service)
):
    """
    새 Pin 생성
    
    세션이 없으면 자동으로 생성됩니다.
    """
    try:
        # 활성 세션 가져오기 (없으면 생성)
        session = await session_service.get_or_create_active_session(
            project_id=pin.project_id,
            user_id=pin.user_id
        )
        
        # Pin 생성
        created_pin = await pin_service.create_pin(
            project_id=pin.project_id,
            session_id=session.id,
            content=pin.content,
            importance=pin.importance,
            tags=pin.tags,
            user_id=pin.user_id
        )
        
        return created_pin.dict()
    except Exception as e:
        logger.error(f"Create pin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/work/pins")
async def list_pins(
    project_id: str = None,
    session_id: str = None,
    user_id: str = None,
    status: str = None,
    limit: int = 10,
    order_by_importance: bool = True,
    pin_service: PinService = Depends(get_pin_service)
):
    """Pin 목록 조회"""
    try:
        pins = await pin_service.get_pins(
            project_id=project_id,
            session_id=session_id,
            user_id=user_id,
            status=status,
            limit=limit,
            order_by_importance=order_by_importance
        )
        return {
            "pins": [p.dict() for p in pins],
            "total": len(pins)
        }
    except Exception as e:
        logger.error(f"List pins error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/work/pins/{pin_id}")
async def get_pin(
    pin_id: str,
    pin_service: PinService = Depends(get_pin_service)
):
    """개별 Pin 조회"""
    try:
        pin = await pin_service.get_pin(pin_id)
        if pin is None:
            raise HTTPException(status_code=404, detail="Pin not found")
        return pin.dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get pin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/work/pins/{pin_id}")
async def update_pin(
    pin_id: str,
    update: PinUpdate,
    pin_service: PinService = Depends(get_pin_service)
):
    """Pin 업데이트"""
    try:
        pin = await pin_service.update_pin(pin_id, update)
        return pin.dict()
    except PinNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidStatusTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Update pin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/work/pins/{pin_id}/complete")
async def complete_pin(
    pin_id: str,
    pin_service: PinService = Depends(get_pin_service)
):
    """
    Pin 완료 처리
    
    importance >= 4인 경우 Memory 승격 제안을 포함합니다.
    """
    try:
        pin = await pin_service.complete_pin(pin_id)
        result = pin.dict()
        
        # 중요도 4 이상이면 승격 제안
        if pin.importance >= 4:
            result["suggest_promotion"] = True
            result["promotion_message"] = f"이 Pin의 중요도가 {pin.importance}입니다. Memory로 승격하시겠습니까?"
        
        return result
    except PinNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidStatusTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Complete pin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/work/pins/{pin_id}/promote")
async def promote_pin(
    pin_id: str,
    pin_service: PinService = Depends(get_pin_service)
):
    """
    Pin을 Memory로 승격
    
    content, tags를 복사하고 embedding을 생성합니다.
    """
    try:
        memory = await pin_service.promote_to_memory(pin_id)
        return {
            "success": True,
            "memory_id": memory.id,
            "message": "Pin이 Memory로 승격되었습니다."
        }
    except PinNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Promote pin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/work/pins/{pin_id}")
async def delete_pin(
    pin_id: str,
    pin_service: PinService = Depends(get_pin_service)
):
    """Pin 삭제"""
    try:
        success = await pin_service.delete_pin(pin_id)
        return {"success": success, "deleted_id": pin_id}
    except PinNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Delete pin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
