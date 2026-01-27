"""
애플리케이션 생명주기 관리.

FastAPI 앱의 시작과 종료 시 필요한 초기화/정리 작업을 담당합니다.
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from datetime import datetime

from fastapi import FastAPI
from dotenv import load_dotenv

from app.core.config import Settings
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.memory import MemoryService
from app.core.services.legacy.search import SearchService
from app.core.services.context import ContextService
from app.core.services.stats import StatsService
from app.core.services.embedding_manager import EmbeddingManagerService
from app.core.services.project import ProjectService
from app.core.services.session import SessionService
from app.core.services.pin import PinService
from app.core.services.metrics_collector import MetricsCollector
from app.core.storage.direct import DirectStorageBackend
from app.mcp_common.tools import MCPToolHandlers
from app.core.utils.logger import get_logger
from .mcp import sse

# 로깅 시스템은 lifespan 함수 내에서 초기화
logger = None

# 전역 서비스 인스턴스들
db: Optional[Database] = None
embedding_service: Optional[EmbeddingService] = None
memory_service: Optional[MemoryService] = None
search_service: Optional[SearchService] = None
context_service: Optional[ContextService] = None
stats_service: Optional[StatsService] = None
embedding_manager: Optional[EmbeddingManagerService] = None
project_service: Optional[ProjectService] = None
session_service: Optional[SessionService] = None
pin_service: Optional[PinService] = None
metrics_collector: Optional[MetricsCollector] = None
mcp_storage: Optional[DirectStorageBackend] = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """애플리케이션 생명주기 관리"""
    global \
        db, \
        embedding_service, \
        memory_service, \
        search_service, \
        context_service, \
        stats_service, \
        embedding_manager, \
        project_service, \
        session_service, \
        pin_service, \
        metrics_collector, \
        mcp_storage, \
        logger

    # .env 파일 로드 (최우선)
    load_dotenv()

    # 로깅 시스템 초기화 (.env 로드 후)
    from app.core.utils.logger import setup_logging

    setup_logging()
    logger = get_logger("mem-mesh-web")

    # 로거 레벨 확인을 위한 디버그 정보
    current_level = logger.logger.getEffectiveLevel()
    logger.info(
        "Starting mem-mesh Web Server...",
        effective_log_level=current_level,
        level_name=logger.logger.level,
    )
    logger.debug("Lifespan event triggered - DEBUG logging is working!")

    try:
        # 설정 로드
        settings = Settings()

        # 로깅 설정 정보 출력 (.env 파일 로드 후)
        log_level = os.getenv("MEM_MESH_LOG_LEVEL", os.getenv("MCP_LOG_LEVEL", "INFO"))
        log_file = os.getenv("MEM_MESH_LOG_FILE", os.getenv("MCP_LOG_FILE", ""))
        log_format = os.getenv(
            "MEM_MESH_LOG_FORMAT", os.getenv("MCP_LOG_FORMAT", "text")
        )
        log_output = os.getenv(
            "MEM_MESH_LOG_OUTPUT", os.getenv("MCP_LOG_OUTPUT", "console")
        )

        logger.debug(
            "Environment variables loaded",
            log_level=log_level,
            log_file=log_file,
            log_format=log_format,
        )

        # 설정 정보 출력
        print("\n" + "=" * 60)
        print("  mem-mesh Web Server Starting")
        print("=" * 60)
        print(f"  Database Path:   {settings.database_path}")
        print(f"  LOG_LEVEL:       {log_level}")
        print(f"  LOG_FILE:        {log_file if log_file else 'console only'}")
        print(f"  LOG_FORMAT:      {log_format}")
        print(f"  Storage Mode:    {settings.storage_mode}")
        print(f"  API Base URL:    {settings.api_base_url}")
        print(f"  Embedding Model: {settings.embedding_model}")
        print(f"  MCP SSE:         /mcp/sse")
        print("=" * 60 + "\n")

        logger.info(
            "Initializing database connection", database_path=settings.database_path
        )

        # 데이터베이스 연결
        db = Database(settings.database_path)
        await db.connect()

        logger.info("Database connected successfully")

        # 임베딩 서비스 초기화 (모델 미리 로드)
        logger.info("Loading embedding model", model=settings.embedding_model)
        embedding_service = EmbeddingService(
            model_name=settings.embedding_model, preload=True
        )

        # 비즈니스 서비스들 초기화
        logger.info("Initializing business services")

        # MetricsCollector 초기화 (SearchService보다 먼저)
        metrics_collector = MetricsCollector(database=db)
        await metrics_collector.start()  # 백그라운드 플러시 태스크 시작

        memory_service = MemoryService(db, embedding_service)
        search_service = SearchService(db, embedding_service, metrics_collector)
        context_service = ContextService(db, embedding_service)
        stats_service = StatsService(db)
        embedding_manager = EmbeddingManagerService(db, embedding_service)

        # Work Tracking 서비스들 초기화
        project_service = ProjectService(db)
        session_service = SessionService(db)
        pin_service = PinService(db)

        # MCP SSE용 스토리지 및 핸들러 초기화
        logger.info("Initializing MCP SSE handlers")
        mcp_storage = DirectStorageBackend(settings.database_path)
        await mcp_storage.initialize()

        # WebSocket notifier 가져오기
        from .websocket.realtime import notifier

        # MCP 도구 핸들러에 notifier 주입
        sse.set_tool_handlers(MCPToolHandlers(mcp_storage, notifier))

        logger.info(
            "mem-mesh application initialized successfully",
            log_file=log_file if log_file else "console_only",
            log_format=log_format,
        )

        yield

    except Exception as e:
        logger.error("Failed to initialize application", error=str(e))
        raise
    finally:
        # 정리 작업 (순서 중요!)
        logger.info("Shutting down mem-mesh application...")

        # MetricsCollector 정리 (버퍼 플러시 및 백그라운드 태스크 중지)
        if metrics_collector:
            try:
                await metrics_collector.stop()
                logger.debug("MetricsCollector stopped and flushed")
            except Exception as e:
                logger.warning("Error stopping MetricsCollector", error=str(e))

        # WebSocket 연결 정리
        try:
            from .websocket.realtime import connection_manager

            await connection_manager.disconnect_all()
        except Exception as e:
            logger.warning("Error disconnecting WebSocket connections", error=str(e))

        # MCP 스토리지 정리
        if mcp_storage:
            try:
                await mcp_storage.shutdown()
                logger.debug("MCP storage shutdown complete")
            except Exception as e:
                logger.warning("Error shutting down MCP storage", error=str(e))

        # 데이터베이스 연결 정리
        if db:
            try:
                await db.close()
                logger.debug("Database connection closed")
            except Exception as e:
                logger.warning("Error closing database connection", error=str(e))

        # 서비스 인스턴스 정리
        db = None
        embedding_service = None
        memory_service = None
        search_service = None
        context_service = None
        stats_service = None
        embedding_manager = None
        project_service = None
        session_service = None
        pin_service = None
        metrics_collector = None
        mcp_storage = None

        logger.info("Application shutdown complete")


def get_services():
    """서비스 인스턴스들 반환"""
    return {
        "db": db,
        "embedding_service": embedding_service,
        "memory_service": memory_service,
        "search_service": search_service,
        "context_service": context_service,
        "stats_service": stats_service,
        "embedding_manager": embedding_manager,
        "project_service": project_service,
        "session_service": session_service,
        "pin_service": pin_service,
        "metrics_collector": metrics_collector,
        "mcp_storage": mcp_storage,
    }
