"""
공통 테스트 픽스처.

모든 테스트에서 재사용 가능한 픽스처를 제공합니다.
"""

import os
import tempfile
from pathlib import Path

# manual/과 benchmarks/ 하위 테스트는 자동 수집에서 제외 (수동 실행용)
collect_ignore = [
    str(Path(__file__).parent / "manual"),
    str(Path(__file__).parent / "benchmarks"),
]
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService


# ---------------------------------------------------------------------------
# temp_db: 임시 DB 경로 반환 (path-only)
# ---------------------------------------------------------------------------
@pytest.fixture
def temp_db_path():
    """임시 SQLite DB 파일 경로 (테스트 후 자동 정리)"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    for ext in ["", "-wal", "-shm"]:
        p = path + ext
        if os.path.exists(p):
            os.unlink(p)


# ---------------------------------------------------------------------------
# temp_db: Database 인스턴스 반환 (async)
# ---------------------------------------------------------------------------
@pytest.fixture
async def temp_db(temp_db_path) -> AsyncGenerator[Database, None]:
    """초기화된 임시 Database 인스턴스"""
    database = Database(temp_db_path)
    await database.connect()
    yield database
    await database.close()


# ---------------------------------------------------------------------------
# mock_embedding_service: 단위 테스트용 임베딩 Mock
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_embedding_service():
    """임베딩 서비스 Mock (384차원, 동기)"""
    service = Mock(spec=EmbeddingService)
    service.embed.return_value = [0.1] * 384
    service.to_bytes.return_value = b"\x00" * (384 * 4)
    service.from_bytes.return_value = [0.1] * 384
    service.embed_batch.return_value = [[0.1] * 384]
    return service


# ---------------------------------------------------------------------------
# embedding_service: 실제 EmbeddingService (통합 테스트용)
# ---------------------------------------------------------------------------
@pytest.fixture
def embedding_service():
    """실제 EmbeddingService (모델 preload 안 함)"""
    return EmbeddingService(preload=False)


# ---------------------------------------------------------------------------
# 서비스 픽스처
# ---------------------------------------------------------------------------
@pytest.fixture
async def memory_service(temp_db, embedding_service):
    """MemoryService 인스턴스"""
    from app.core.services.memory import MemoryService

    return MemoryService(temp_db, embedding_service)


@pytest.fixture
async def memory_service_mocked(temp_db, mock_embedding_service):
    """MemoryService with mocked embeddings"""
    from app.core.services.memory import MemoryService

    return MemoryService(temp_db, mock_embedding_service)


@pytest.fixture
async def search_service(temp_db, embedding_service):
    """SearchService 인스턴스 (legacy)"""
    from app.core.services.search import SearchService

    return SearchService(temp_db, embedding_service)


@pytest.fixture
async def context_service(temp_db, embedding_service):
    """ContextService 인스턴스"""
    from app.core.services.context import ContextService

    return ContextService(temp_db, embedding_service)


@pytest.fixture
async def stats_service(temp_db):
    """StatsService 인스턴스"""
    from app.core.services.stats import StatsService

    return StatsService(temp_db)


@pytest.fixture
async def pin_service(temp_db):
    """PinService 인스턴스"""
    from app.core.services.pin import PinService

    return PinService(temp_db)


@pytest.fixture
async def session_service(temp_db):
    """SessionService 인스턴스"""
    from app.core.services.session import SessionService

    return SessionService(temp_db)


# ---------------------------------------------------------------------------
# mock_db: MagicMock DB (순수 단위 테스트용)
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_db():
    """MagicMock Database (async 메서드 포함)"""
    db = MagicMock(spec=Database)
    db.execute = AsyncMock()
    db.fetchone = AsyncMock(return_value=None)
    db.fetchall = AsyncMock(return_value=[])
    db.vector_search = AsyncMock(return_value=[])
    return db


# ---------------------------------------------------------------------------
# MCP 관련 픽스처
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_tool_handlers():
    """MCPToolHandlers Mock"""
    from app.mcp_common.tools import MCPToolHandlers

    handlers = MagicMock(spec=MCPToolHandlers)
    handlers.add = AsyncMock(
        return_value={"id": "test-id", "status": "saved", "created_at": "2026-01-01T00:00:00Z"}
    )
    handlers.search = AsyncMock(
        return_value={"results": [], "total": 0, "format": "standard"}
    )
    handlers.context = AsyncMock(
        return_value={"memory": None, "related_memories": []}
    )
    handlers.update = AsyncMock(
        return_value={"id": "test-id", "status": "updated"}
    )
    handlers.delete = AsyncMock(
        return_value={"id": "test-id", "status": "deleted"}
    )
    handlers.stats = AsyncMock(
        return_value={"total_memories": 0, "categories_breakdown": {}}
    )
    handlers.pin_add = AsyncMock(
        return_value={"id": "pin-1", "status": "created"}
    )
    handlers.pin_complete = AsyncMock(
        return_value={"id": "pin-1", "status": "completed", "suggest_promotion": False}
    )
    handlers.pin_promote = AsyncMock(
        return_value={"id": "pin-1", "memory_id": "mem-1"}
    )
    handlers.session_resume = AsyncMock(
        return_value={"session_id": "sess-1", "pins": [], "token_info": {}}
    )
    handlers.session_end = AsyncMock(
        return_value={"session_id": "sess-1", "status": "ended"}
    )
    handlers.link = AsyncMock(
        return_value={"id": "rel-1", "created": True, "message": "Linked"}
    )
    handlers.unlink = AsyncMock(
        return_value={"success": True, "deleted_count": 1}
    )
    handlers.get_links = AsyncMock(
        return_value={"relations": [], "total": 0}
    )
    return handlers
