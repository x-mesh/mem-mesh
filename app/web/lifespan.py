"""
애플리케이션 생명주기 관리.

FastAPI 앱의 시작과 종료 시 필요한 초기화/정리 작업을 담당합니다.
"""

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI

from app.core.auth.service import OAuthService
from app.core.config import Settings
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService, is_model_cached
from app.core.services.context import ContextService
from app.core.services.embedding_manager import EmbeddingManagerService
from app.core.services.memory import MemoryService
from app.core.services.metrics_collector import MetricsCollector
from app.core.services.pin import PinService
from app.core.services.project import ProjectService
from app.core.services.relation import RelationService
from app.core.services.session import SessionService
from app.core.services.stats import StatsService
from app.core.services.unified_search import UnifiedSearchService
from app.core.storage.direct import DirectStorageBackend
from app.core.utils.logger import get_logger
from app.mcp_common.tools import MCPToolHandlers

from .mcp import sse

# Logging system initialized inside the lifespan function
logger = None

db: Optional[Database] = None
embedding_service: Optional[EmbeddingService] = None
memory_service: Optional[MemoryService] = None
search_service: Optional[UnifiedSearchService] = None
context_service: Optional[ContextService] = None
stats_service: Optional[StatsService] = None
embedding_manager: Optional[EmbeddingManagerService] = None
project_service: Optional[ProjectService] = None
session_service: Optional[SessionService] = None
pin_service: Optional[PinService] = None
metrics_collector: Optional[MetricsCollector] = None
relation_service: Optional[RelationService] = None
mcp_storage: Optional[DirectStorageBackend] = None
oauth_service: Optional[OAuthService] = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """애플리케이션 생명주기 관리"""
    global db, embedding_service, memory_service, search_service, context_service, stats_service, embedding_manager, project_service, session_service, pin_service, metrics_collector, relation_service, mcp_storage, oauth_service, logger

    # Load .env file (highest priority)
    load_dotenv()

    # Initialize logging system (after .env load)
    from app.core.utils.logger import setup_logging

    setup_logging()
    logger = get_logger("mem-mesh-web")

    # Debug info to verify logger level
    current_level = logger.logger.getEffectiveLevel()
    logger.info(
        "Starting mem-mesh Web Server...",
        effective_log_level=current_level,
        level_name=logger.logger.level,
    )
    logger.debug("Lifespan event triggered - DEBUG logging is working!")

    try:
        # Load settings
        settings = Settings()

        # Print logging config info (after .env file load)
        log_level = os.getenv("MEM_MESH_LOG_LEVEL", os.getenv("MCP_LOG_LEVEL", "INFO"))
        log_file = os.getenv("MEM_MESH_LOG_FILE", os.getenv("MCP_LOG_FILE", ""))
        log_format = os.getenv(
            "MEM_MESH_LOG_FORMAT", os.getenv("MCP_LOG_FORMAT", "text")
        )
        os.getenv("MEM_MESH_LOG_OUTPUT", os.getenv("MCP_LOG_OUTPUT", "console"))

        logger.debug(
            "Environment variables loaded",
            log_level=log_level,
            log_file=log_file,
            log_format=log_format,
        )

        # Settings info (banner printed in __main__.py; only log here)
        from app.core.version import __VERSION__

        logger.info(
            "Worker starting",
            version=__VERSION__,
            pid=os.getpid(),
            database_path=settings.database_path,
            embedding_model=settings.embedding_model,
            storage_mode=settings.storage_mode,
        )

        logger.info(
            "Initializing database connection", database_path=settings.database_path
        )

        # Connect to database
        db = Database(settings.database_path, embedding_dim=settings.embedding_dim)
        await db.connect()

        logger.info("Database connected successfully")

        # Initialize embedding service (deferred loading — server starts immediately)
        # Priority: target_embedding_model (onboarding choice) > embedding_model (DB) > settings
        embedding_model = settings.embedding_model
        target_model = None
        db_model = None
        try:
            target_model = await db._migrator.get_embedding_metadata("target_embedding_model")
            db_model = await db._migrator.get_embedding_metadata("embedding_model")
            if target_model:
                if target_model != embedding_model:
                    logger.info(
                        "Using target model from onboarding selection",
                        target_model=target_model,
                        settings_model=embedding_model,
                    )
                embedding_model = target_model
            elif db_model and db_model != embedding_model:
                logger.info(
                    "Using model from DB metadata",
                    db_model=db_model,
                    settings_model=embedding_model,
                )
                embedding_model = db_model
        except Exception as e:
            logger.debug(f"DB not ready or metadata table missing: {e}")

        model_cached = is_model_cached(embedding_model)
        logger.info(
            "Initializing embedding service",
            model=embedding_model,
            cached=model_cached,
        )
        embedding_service = EmbeddingService(
            model_name=embedding_model, preload=False, defer_loading=True
        )

        # If a model has been selected before (target_model or db_model),
        # start background loading/download regardless of cache status
        _has_configured_model = bool(target_model or db_model)

        if model_cached or _has_configured_model:
            if model_cached:
                logger.info("Model cached, loading in background")
                embedding_service._status = "loading"
            else:
                logger.info(
                    "Model previously selected but not cached, downloading in background",
                    model=embedding_model,
                )
                embedding_service._status = "downloading"

            _bg_model_name = embedding_model

            def _on_model_progress(progress: float, status: str) -> None:
                from .websocket.realtime import notifier
                import asyncio

                try:
                    loop = asyncio.get_running_loop()
                    loop.call_soon_threadsafe(
                        asyncio.ensure_future,
                        notifier.broadcast(
                            "model_download",
                            {"progress": progress, "status": status, "model": _bg_model_name},
                        ),
                    )
                except Exception as e:
                    logger.debug(f"WebSocket not ready yet during startup: {e}")

            embedding_service.load_model_background(on_progress=_on_model_progress)
        else:
            logger.info("No model configured, waiting for user selection via onboarding")

        # Initialize business services
        logger.info("Initializing business services")

        # Initialize MetricsCollector (before SearchService)
        metrics_collector = MetricsCollector(database=db)
        await metrics_collector.start()  # Start background flush task

        memory_service = MemoryService(db, embedding_service)
        search_service = UnifiedSearchService(
            db=db,
            embedding_service=embedding_service,
            metrics_collector=metrics_collector,
            enable_quality_features=settings.enable_quality_features,
            enable_korean_optimization=settings.enable_korean_optimization,
            enable_noise_filter=settings.enable_noise_filter,
            enable_score_normalization=settings.enable_score_normalization,
            score_normalization_method=settings.score_normalization_method,
            cache_embedding_ttl=settings.cache_embedding_ttl,
            cache_search_ttl=settings.cache_search_ttl,
            cache_context_ttl=settings.cache_context_ttl,
        )
        context_service = ContextService(db, embedding_service)
        stats_service = StatsService(db)
        embedding_manager = EmbeddingManagerService(db, embedding_service)

        # Initialize Work Tracking services
        project_service = ProjectService(db)
        session_service = SessionService(db, embedding_service=embedding_service)
        pin_service = PinService(db, embedding_service)
        relation_service = RelationService(db)

        # Initialize OAuth service
        logger.info("Initializing OAuth service")
        oauth_service = OAuthService(db)
        app.state.oauth_service = oauth_service

        # Connect DB to Basic Auth session store
        from .oauth.basic_auth import session_store

        session_store.set_database(db)

        # Initialize storage and handlers for MCP SSE
        logger.info("Initializing MCP SSE handlers")
        mcp_storage = DirectStorageBackend(settings.database_path)
        await mcp_storage.initialize()

        # Initialize BatchOperationHandler (reuse existing db/embedding)
        batch_handler = None
        try:
            from app.core.services.search import SearchService as LegacySearchService
            from app.mcp_common.batch_tools import BatchOperationHandler

            legacy_search = LegacySearchService(db, embedding_service)
            batch_handler = BatchOperationHandler(
                memory_service=memory_service,
                search_service=legacy_search,
                embedding_service=embedding_service,
                db=db,
            )
            logger.info("BatchOperationHandler initialized for main web MCP")
        except Exception as e:
            logger.warning(
                "BatchOperationHandler init failed, using fallback", error=str(e)
            )

        # Get WebSocket notifier
        from .websocket.realtime import notifier

        # Inject notifier into BatchOperationHandler
        if batch_handler:
            batch_handler._notifier = notifier

        # Inject notifier into MCP tool handler
        sse.set_tool_handlers(
            MCPToolHandlers(mcp_storage, notifier), batch_handler=batch_handler
        )

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
        # Cleanup tasks (order matters!)
        logger.info("Shutting down mem-mesh application...")

        # Clean up MetricsCollector (flush buffer and stop background task)
        if metrics_collector:
            try:
                await metrics_collector.stop()
                logger.debug("MetricsCollector stopped and flushed")
            except Exception as e:
                logger.warning("Error stopping MetricsCollector", error=str(e))

        # Clean up WebSocket connections
        try:
            from .websocket.realtime import connection_manager

            await connection_manager.disconnect_all()
        except Exception as e:
            logger.warning("Error disconnecting WebSocket connections", error=str(e))

        # Clean up MCP storage
        if mcp_storage:
            try:
                await mcp_storage.shutdown()
                logger.debug("MCP storage shutdown complete")
            except Exception as e:
                logger.warning("Error shutting down MCP storage", error=str(e))

        # Clean up database connection
        if db:
            try:
                await db.close()
                logger.debug("Database connection closed")
            except Exception as e:
                logger.warning("Error closing database connection", error=str(e))

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
        relation_service = None
        mcp_storage = None
        oauth_service = None

        logger.info("Application shutdown complete")


def get_services() -> Dict[str, Any]:
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
        "relation_service": relation_service,
        "mcp_storage": mcp_storage,
        "oauth_service": oauth_service,
    }
