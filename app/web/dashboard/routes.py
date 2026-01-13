"""
Dashboard REST API 라우터.

메모리 관리, 검색, 통계, 임베딩 관리 등의 API 엔드포인트를 제공합니다.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends

from app.core.services.memory import MemoryService, MemoryNotFoundError
from app.core.services.search import SearchService
from app.core.services.context import ContextService, ContextNotFoundError
from app.core.services.stats import StatsService
from app.core.services.embedding_manager import EmbeddingManagerService
from app.core.schemas.requests import AddParams, SearchParams, UpdateParams
from app.core.schemas.responses import (
    AddResponse, SearchResponse, ContextResponse, 
    UpdateResponse, DeleteResponse, StatsResponse
)
from ..common.dependencies import (
    get_memory_service, get_search_service, get_context_service,
    get_stats_service, get_embedding_manager
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
        return await service.create(
            content=params.content,
            project_id=params.project_id,
            category=params.category,
            source=params.source or "api",
            tags=params.tags
        )
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
        return await service.update(
            memory_id=memory_id,
            content=params.content,
            category=params.category,
            tags=params.tags
        )
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
        return await service.delete(memory_id)
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