"""
FastAPI 의존성 함수들.

각 서비스에 대한 의존성 주입을 제공합니다.
"""

from fastapi import HTTPException

from app.core.database.base import Database
from app.core.services.context import ContextService
from app.core.services.embedding_manager import EmbeddingManagerService
from app.core.services.memory import MemoryService
from app.core.services.pin import PinService
from app.core.services.project import ProjectService
from app.core.services.relation import RelationService
from app.core.services.session import SessionService
from app.core.services.stats import StatsService
from app.core.services.unified_search import UnifiedSearchService

from ..lifespan import get_services


def get_database() -> Database:
    """데이터베이스 의존성"""
    services = get_services()
    if services["db"] is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    return services["db"]


def get_memory_service() -> MemoryService:
    """메모리 서비스 의존성"""
    services = get_services()
    if services["memory_service"] is None:
        raise HTTPException(status_code=500, detail="Memory service not initialized")
    return services["memory_service"]


def get_search_service() -> UnifiedSearchService:
    """검색 서비스 의존성"""
    services = get_services()
    if services["search_service"] is None:
        raise HTTPException(status_code=500, detail="Search service not initialized")
    return services["search_service"]


def get_context_service() -> ContextService:
    """컨텍스트 서비스 의존성"""
    services = get_services()
    if services["context_service"] is None:
        raise HTTPException(status_code=500, detail="Context service not initialized")
    return services["context_service"]


def get_stats_service() -> StatsService:
    """통계 서비스 의존성"""
    services = get_services()
    if services["stats_service"] is None:
        raise HTTPException(status_code=500, detail="Stats service not initialized")
    return services["stats_service"]


def get_embedding_manager() -> EmbeddingManagerService:
    """임베딩 매니저 서비스 의존성"""
    services = get_services()
    if services["embedding_manager"] is None:
        raise HTTPException(status_code=500, detail="Embedding manager not initialized")
    return services["embedding_manager"]


def get_project_service() -> ProjectService:
    """프로젝트 서비스 의존성"""
    services = get_services()
    if services["project_service"] is None:
        raise HTTPException(status_code=500, detail="Project service not initialized")
    return services["project_service"]


def get_session_service() -> SessionService:
    """세션 서비스 의존성"""
    services = get_services()
    if services["session_service"] is None:
        raise HTTPException(status_code=500, detail="Session service not initialized")
    return services["session_service"]


def get_pin_service() -> PinService:
    """Pin 서비스 의존성"""
    services = get_services()
    if services["pin_service"] is None:
        raise HTTPException(status_code=500, detail="Pin service not initialized")
    return services["pin_service"]


def get_relation_service() -> RelationService:
    """관계 서비스 의존성"""
    services = get_services()
    if services.get("relation_service") is None:
        raise HTTPException(status_code=500, detail="Relation service not initialized")
    return services["relation_service"]
