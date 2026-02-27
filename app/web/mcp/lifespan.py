"""
MCP 전용 애플리케이션 생명주기 관리.

MCP SSE 서버에 필요한 최소한의 서비스만 초기화합니다.
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from fastapi import FastAPI
from dotenv import load_dotenv

from app.core.config import Settings
from app.core.storage.direct import DirectStorageBackend
from app.mcp_common.tools import MCPToolHandlers
from app.core.utils.logger import get_logger
from app.web.mcp import sse


logger = None

# 전역 서비스 인스턴스
mcp_storage: Optional[DirectStorageBackend] = None


@asynccontextmanager
async def mcp_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """MCP 전용 애플리케이션 생명주기 관리"""
    global mcp_storage, logger
    
    load_dotenv()
    
    from app.core.utils.logger import setup_logging
    setup_logging()
    logger = get_logger("mem-mesh-mcp")
    
    logger.info("Starting mem-mesh MCP SSE Server...")
    
    try:
        settings = Settings()
        
        # 설정 정보 출력
        log_level = os.getenv("MEM_MESH_LOG_LEVEL", "INFO")
        log_file = os.getenv("MEM_MESH_LOG_FILE", "")
        
        print("\n" + "="*60)
        print("  mem-mesh MCP SSE Server Starting")
        print("="*60)
        print(f"  Database Path:   {settings.database_path}")
        print(f"  LOG_LEVEL:       {log_level}")
        print(f"  Embedding Model: {settings.embedding_model}")
        print(f"  MCP SSE:         /mcp/sse")
        print("="*60 + "\n")
        
        # MCP 스토리지 초기화
        logger.info("Initializing MCP storage", database_path=settings.database_path)
        mcp_storage = DirectStorageBackend(settings.database_path)
        await mcp_storage.initialize()
        
        # BatchOperationHandler 초기화
        batch_handler = None
        try:
            from app.core.database.base import Database
            from app.core.embeddings.service import EmbeddingService
            from app.core.services.memory import MemoryService
            from app.core.services.search import SearchService
            from app.mcp_common.batch_tools import BatchOperationHandler

            db = Database(settings.database_path, embedding_dim=settings.embedding_dim)
            await db.connect()
            embedding_service = EmbeddingService(preload=False)
            memory_service = MemoryService(db, embedding_service)
            search_service = SearchService(db, embedding_service)

            batch_handler = BatchOperationHandler(
                memory_service=memory_service,
                search_service=search_service,
                embedding_service=embedding_service,
                db=db,
            )
            logger.info("BatchOperationHandler initialized for MCP SSE")
        except Exception as e:
            logger.warning("BatchOperationHandler init failed, using fallback", error=str(e))

        # MCP 도구 핸들러 설정 (notifier 없이)
        sse.set_tool_handlers(MCPToolHandlers(mcp_storage, notifier=None), batch_handler=batch_handler)
        
        logger.info("MCP SSE Server initialized successfully")
        
        yield
        
    except Exception as e:
        logger.error("Failed to initialize MCP server", error=str(e))
        raise
    finally:
        logger.info("Shutting down MCP SSE Server...")
        
        if batch_handler is not None:
            try:
                if hasattr(batch_handler, 'db') and batch_handler.db is not None:
                    await batch_handler.db.disconnect()
                    logger.debug("Batch handler DB disconnected")
            except Exception as e:
                logger.warning("Error closing batch handler DB", error=str(e))
        
        if mcp_storage:
            try:
                await mcp_storage.shutdown()
                logger.debug("MCP storage shutdown complete")
            except Exception as e:
                logger.warning("Error shutting down MCP storage", error=str(e))
        
        mcp_storage = None
        logger.info("MCP Server shutdown complete")
