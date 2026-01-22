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
        
        # MCP 도구 핸들러 설정 (notifier 없이)
        sse.set_tool_handlers(MCPToolHandlers(mcp_storage, notifier=None))
        
        logger.info("MCP SSE Server initialized successfully")
        
        yield
        
    except Exception as e:
        logger.error("Failed to initialize MCP server", error=str(e))
        raise
    finally:
        logger.info("Shutting down MCP SSE Server...")
        
        if mcp_storage:
            try:
                await mcp_storage.shutdown()
                logger.debug("MCP storage shutdown complete")
            except Exception as e:
                logger.warning("Error shutting down MCP storage", error=str(e))
        
        mcp_storage = None
        logger.info("MCP Server shutdown complete")
