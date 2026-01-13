"""
FastAPI 애플리케이션 메인 모듈
mem-mesh 서버의 FastAPI 앱 설정 및 초기화
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from ..core.config import Settings
from ..core.database.base import Database
from ..core.embeddings.service import EmbeddingService
from ..core.services.memory import MemoryService, MemoryNotFoundError, DatabaseError
from ..core.services.search import SearchService
from ..core.services.context import ContextService, ContextNotFoundError
from ..core.services.stats import StatsService
from ..core.services.embedding_manager import EmbeddingManagerService
from ..core.schemas.requests import AddParams, SearchParams, ContextParams, UpdateParams, DeleteParams, StatsParams
from ..core.schemas.responses import (
    AddResponse, SearchResponse, ContextResponse, 
    UpdateResponse, DeleteResponse, StatsResponse, ErrorResponse
)
from ..core.storage.direct import DirectStorageBackend
from ..mcp_common.tools import MCPToolHandlers
from . import mcp_sse

logger = logging.getLogger(__name__)

# 전역 서비스 인스턴스들
db: Database = None
embedding_service: EmbeddingService = None
memory_service: MemoryService = None
search_service: SearchService = None
context_service: ContextService = None
stats_service: StatsService = None
embedding_manager: EmbeddingManagerService = None
mcp_storage: DirectStorageBackend = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """애플리케이션 생명주기 관리"""
    global db, embedding_service, memory_service, search_service, context_service, stats_service, embedding_manager, mcp_storage
    
    logger.info("Starting mem-mesh FastAPI application...")
    
    try:
        # 설정 로드
        settings = Settings()
        
        # 설정 정보 출력
        print("\n" + "="*60)
        print("  mem-mesh Web Server Starting")
        print("="*60)
        print(f"  Database Path:   {settings.database_path}")
        print(f"  Storage Mode:    {settings.storage_mode}")
        print(f"  API Base URL:    {settings.api_base_url}")
        print(f"  Embedding Model: {settings.embedding_model}")
        print(f"  MCP SSE:         /mcp/sse")
        print("="*60 + "\n")
        
        # 데이터베이스 연결
        db = Database(settings.database_path)
        await db.connect()
        
        # 임베딩 서비스 초기화 (모델 미리 로드)
        embedding_service = EmbeddingService(
            model_name=settings.embedding_model,
            preload=True
        )
        
        # 비즈니스 서비스들 초기화
        memory_service = MemoryService(db, embedding_service)
        search_service = SearchService(db, embedding_service)
        context_service = ContextService(db, embedding_service)
        stats_service = StatsService(db)
        embedding_manager = EmbeddingManagerService(db, embedding_service)
        
        # MCP SSE용 스토리지 및 핸들러 초기화
        mcp_storage = DirectStorageBackend(settings.database_path)
        await mcp_storage.initialize()
        mcp_sse.set_tool_handlers(MCPToolHandlers(mcp_storage))
        
        logger.info("mem-mesh application initialized successfully")
        
        yield
        
    except Exception as e:
        logger.error(f"Failed to initialize application: {e}")
        raise
    finally:
        # 정리 작업
        logger.info("Shutting down mem-mesh application...")
        if mcp_storage:
            await mcp_storage.shutdown()
        if db:
            await db.close()
        logger.info("Application shutdown complete")


# FastAPI 앱 생성
app = FastAPI(
    title="mem-mesh",
    description="Central memory server with vector search and context retrieval",
    version="1.0.0",
    lifespan=lifespan
)

# MCP SSE 라우터 등록
app.include_router(mcp_sse.router)

# 정적 파일 서빙 설정
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발용, 운영에서는 제한 필요
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 의존성 함수들
def get_memory_service() -> MemoryService:
    """메모리 서비스 의존성"""
    if memory_service is None:
        raise HTTPException(status_code=500, detail="Memory service not initialized")
    return memory_service


def get_search_service() -> SearchService:
    """검색 서비스 의존성"""
    if search_service is None:
        raise HTTPException(status_code=500, detail="Search service not initialized")
    return search_service


def get_context_service() -> ContextService:
    """컨텍스트 서비스 의존성"""
    if context_service is None:
        raise HTTPException(status_code=500, detail="Context service not initialized")
    return context_service


def get_stats_service() -> StatsService:
    """통계 서비스 의존성"""
    if stats_service is None:
        raise HTTPException(status_code=500, detail="Stats service not initialized")
    return stats_service


def get_embedding_manager() -> EmbeddingManagerService:
    """임베딩 매니저 서비스 의존성"""
    if embedding_manager is None:
        raise HTTPException(status_code=500, detail="Embedding manager not initialized")
    return embedding_manager


# API 엔드포인트들

@app.get("/")
async def serve_web_ui():
    """웹 UI 서빙"""
    return FileResponse("static/index.html")


@app.get("/about")
async def serve_about_page():
    """About 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@app.get("/dashboard")
async def serve_dashboard_page():
    """Dashboard 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@app.get("/search")
async def serve_search_page():
    """검색 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@app.get("/memory/{memory_id}")
async def serve_memory_page(memory_id: str):
    """메모리 상세 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@app.get("/create")
async def serve_create_page():
    """메모리 생성 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@app.get("/edit/{memory_id}")
async def serve_edit_page(memory_id: str):
    """메모리 편집 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@app.get("/projects")
async def serve_projects_page():
    """프로젝트 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@app.get("/project/{project_id}")
async def serve_project_page(project_id: str):
    """프로젝트 상세 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@app.get("/test")
async def serve_test_page():
    """테스트 페이지 서빙"""
    return FileResponse("test_web_ui.html")


@app.get("/analytics")
async def serve_analytics_page():
    """분석 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@app.get("/api")
async def api_root():
    """API 루트 엔드포인트"""
    return {
        "name": "mem-mesh",
        "description": "Central memory server with vector search",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/api/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy", "timestamp": "2026-01-11T12:30:00Z"}


@app.post("/api/memories", response_model=AddResponse)
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


@app.get("/api/memories/search", response_model=SearchResponse)
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


@app.get("/api/memories/stats", response_model=StatsResponse)
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


@app.get("/api/projects")
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


@app.get("/api/memories/{memory_id}")
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


@app.get("/api/memories/{memory_id}/context", response_model=ContextResponse)
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


@app.put("/api/memories/{memory_id}", response_model=UpdateResponse)
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


@app.delete("/api/memories/{memory_id}", response_model=DeleteResponse)
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

@app.get("/api/embeddings/status")
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


@app.post("/api/embeddings/migrate")
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


@app.get("/api/embeddings/migration/progress")
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


@app.get("/settings")
async def serve_settings_page():
    """설정 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")



# Catch-all route for SPA routing (must be last)
@app.get("/{path:path}")
async def serve_spa_routes(path: str):
    """SPA 라우팅을 위한 catch-all 라우트"""
    # API 경로는 제외
    if path.startswith("api"):
        raise HTTPException(status_code=404, detail="Not Found")
    
    # 정적 파일 경로는 제외 (이미 /static으로 마운트됨)
    if path.startswith("static"):
        raise HTTPException(status_code=404, detail="Not Found")
    
    # docs 경로는 제외 (FastAPI 자동 문서)
    if path in ["docs", "redoc", "openapi.json"]:
        raise HTTPException(status_code=404, detail="Not Found")
    
    # 모든 다른 경로는 index.html로 서빙 (SPA 라우팅)
    return FileResponse("static/index.html")


# 에러 핸들러
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    """HTTP 예외 핸들러"""
    error_response = ErrorResponse(
        error=f"HTTP_{exc.status_code}",
        message=exc.detail
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    """일반 예외 핸들러"""
    logger.error(f"Unhandled exception: {exc}")
    error_response = ErrorResponse(
        error="INTERNAL_ERROR",
        message="Internal server error"
    )
    return JSONResponse(
        status_code=500,
        content=error_response.model_dump()
    )


if __name__ == "__main__":
    import uvicorn
    
    # 개발용 서버 실행
    uvicorn.run(
        "app.web.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )