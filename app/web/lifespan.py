"""
애플리케이션 생명주기 관리.

FastAPI 앱의 시작과 종료 시 필요한 초기화/정리 작업을 담당합니다.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.core.config import Settings
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.memory import MemoryService
from app.core.services.search import SearchService
from app.core.services.context import ContextService
from app.core.services.stats import StatsService
from app.core.services.embedding_manager import EmbeddingManagerService
from app.core.storage.direct import DirectStorageBackend
from app.mcp_common.tools import MCPToolHandlers
from .mcp import sse

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
    
    logger.info("Starting mem-mesh Web Server...")
    
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
        sse.set_tool_handlers(MCPToolHandlers(mcp_storage))
        
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


def get_services():
    """서비스 인스턴스들 반환"""
    return {
        'db': db,
        'embedding_service': embedding_service,
        'memory_service': memory_service,
        'search_service': search_service,
        'context_service': context_service,
        'stats_service': stats_service,
        'embedding_manager': embedding_manager,
        'mcp_storage': mcp_storage
    }