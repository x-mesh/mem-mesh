"""is_starred 읽기 노출 테스트 — 전 검색 경로 + MCP 직렬화.

SearchResult 빌드 사이트가 15곳이라 한 곳만 빠져도 그 모드에서만 조용히 별표가
사라진다. 여기서 모든 모드를 못 박고, 컬럼 없는 행(hub/레거시 SELECT)이 예외를
내지 않고 False로 읽히는지도 확인한다.
"""

import os
import sqlite3
import tempfile

import pytest

from app.core.database.base import Database
from app.core.schemas.responses import SearchResult
from app.core.services.memory import MemoryService
from app.core.services.search import SearchService
from app.core.services.search import _parse_starred as legacy_parse_starred
from app.core.services.unified_search import UnifiedSearchService

STARRED_CONTENT = (
    "Decision about the embedding rollout that the user starred — long enough "
    "fixture content to pass the quality gate and be found by every search mode."
)
PLAIN_CONTENT = (
    "Routine note nobody starred — long enough fixture content to pass the "
    "quality gate and be found by every search mode alongside the starred one."
)


@pytest.fixture
async def temp_db():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    db = Database(db_path)
    await db.connect()
    yield db
    await db.close()

    for ext in ["", "-wal", "-shm"]:
        p = db_path + ext
        if os.path.exists(p):
            os.unlink(p)


@pytest.fixture
async def memory_service(temp_db, mock_embedding_service):
    return MemoryService(temp_db, mock_embedding_service)


@pytest.fixture
async def unified_service(temp_db, mock_embedding_service):
    return UnifiedSearchService(
        db=temp_db,
        embedding_service=mock_embedding_service,
        enable_quality_features=False,
        enable_korean_optimization=False,
        enable_noise_filter=False,
        enable_score_normalization=False,
    )


@pytest.fixture
async def legacy_service(temp_db, mock_embedding_service):
    return SearchService(temp_db, mock_embedding_service)


async def _seed(memory_service):
    """별표 1건 + 무별표 1건"""
    starred = await memory_service.create(
        content=STARRED_CONTENT, category="decision", source="test"
    )
    plain = await memory_service.create(
        content=PLAIN_CONTENT, category="task", source="test"
    )
    await memory_service.set_starred(starred.id, True)
    return starred, plain


def _starred_map(response):
    return {r.id: r.is_starred for r in response.results}


class TestUnifiedReadExposure:
    """UnifiedSearchService — 전 모드에서 is_starred가 실려야 한다"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "mode,query",
        [
            ("hybrid", "embedding rollout"),
            ("exact", "starred"),
            ("semantic", "embedding rollout"),
            ("fuzzy", "embeding rollout"),  # 오타 — fuzzy 경로
        ],
    )
    async def test_search_modes_carry_is_starred(
        self, memory_service, unified_service, mode, query
    ):
        starred, _ = await _seed(memory_service)
        result = await unified_service.search(query=query, search_mode=mode, limit=20)
        flags = _starred_map(result)
        assert flags, f"{mode} returned no results"
        assert flags.get(starred.id) is True, f"{mode} lost is_starred"

    @pytest.mark.asyncio
    async def test_empty_query_recent_carries_is_starred(
        self, memory_service, unified_service
    ):
        starred, plain = await _seed(memory_service)
        result = await unified_service.search(query="", limit=20)
        flags = _starred_map(result)
        assert flags[starred.id] is True
        assert flags[plain.id] is False

    @pytest.mark.asyncio
    async def test_id_prefix_shortcut_carries_is_starred(
        self, memory_service, unified_service
    ):
        """id 쇼트컷은 filters dict를 우회하는 별도 경로다"""
        starred, _ = await _seed(memory_service)
        result = await unified_service.search(query=starred.id[:8], limit=20)
        assert _starred_map(result).get(starred.id) is True

    @pytest.mark.asyncio
    async def test_quality_scoring_path_carries_is_starred(
        self, temp_db, mock_embedding_service, memory_service
    ):
        """_apply_quality_scoring은 Row가 아니라 dict를 만든다 — 놓치기 쉬운 경로"""
        starred, _ = await _seed(memory_service)
        service = UnifiedSearchService(
            db=temp_db,
            embedding_service=mock_embedding_service,
            enable_quality_features=True,  # dict 경로 활성화
            enable_korean_optimization=False,
            enable_noise_filter=False,
            enable_score_normalization=False,
        )
        result = await service.search(query="embedding rollout", limit=20)
        flags = _starred_map(result)
        if starred.id in flags:  # quality gate가 걸러내지 않았다면
            assert flags[starred.id] is True


class TestLegacyReadExposure:
    """레거시 SearchService (use_unified_search=False / BatchOperationHandler 경로)"""

    @pytest.mark.asyncio
    async def test_empty_query_carries_is_starred(self, memory_service, legacy_service):
        starred, plain = await _seed(memory_service)
        result = await legacy_service.search(query="", limit=20)
        flags = _starred_map(result)
        assert flags[starred.id] is True
        assert flags[plain.id] is False

    @pytest.mark.asyncio
    async def test_exact_mode_carries_is_starred(self, memory_service, legacy_service):
        starred, _ = await _seed(memory_service)
        result = await legacy_service.search(
            query="starred", search_mode="exact", limit=20
        )
        assert _starred_map(result).get(starred.id) is True


class TestTolerantParse:
    """컬럼 없는 행(hub 결과, 레거시 명시 SELECT)이 예외를 내면 안 된다"""

    def test_parse_starred_missing_column_is_false(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT 'x' AS id").fetchone()
        assert legacy_parse_starred(row) is False
        conn.close()

    def test_parse_starred_reads_int(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        assert legacy_parse_starred(conn.execute("SELECT 1 AS is_starred").fetchone())
        assert not legacy_parse_starred(
            conn.execute("SELECT 0 AS is_starred").fetchone()
        )
        conn.close()

    def test_search_result_defaults_false_for_hub_rows(self):
        """hub/federated 행은 컬럼 자체가 없다 — validation 에러 나면 안 됨"""
        r = SearchResult(
            id="hub-1",
            content="from the team hub",
            similarity_score=0.9,
            created_at="2026-01-01T00:00:00Z",
            project_id=None,
            category="decision",
            source="hub",
        )
        assert r.is_starred is False


class TestMcpSerialization:
    """MCP 응답은 수작업 직렬화 — SearchResult 필드만으론 클라이언트에 안 간다"""

    @pytest.mark.asyncio
    async def test_standard_format_exposes_is_starred(self, temp_db, memory_service):
        from app.core.storage.direct import DirectStorageBackend
        from app.mcp_common.tools import MCPToolHandlers

        starred, plain = await _seed(memory_service)

        storage = DirectStorageBackend(temp_db.db_path)
        await storage.initialize()
        handlers = MCPToolHandlers(storage, notifier=None, enable_compression=True)

        # limit은 노이즈 필터 때문에 내부에서 2배가 되고 SearchParams 상한이 20이다
        resp = await handlers.search(query="", limit=10, response_format="standard")
        by_id = {r["id"]: r for r in resp["results"]}

        assert by_id[starred.id].get("is_starred") is True
        # 무별표 행은 키 자체를 싣지 않는다 (토큰 절약)
        assert "is_starred" not in by_id[plain.id]
