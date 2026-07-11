"""starred_only 검색 필터 테스트.

anchored_path에서 실증된 두 부류의 버그를 여기서 못 박는다:
- 캐시 오염: starred_only가 캐시 키에 없으므로 우회하지 않으면 필터/무필터 결과가
  교차 오염된다 (F5)
- 전 트랜스포트 드리프트: 파라미터가 한 계층만 빠져도 그 트랜스포트에서 조용히 무시된다
"""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.database.base import Database
from app.core.schemas.requests import SearchParams
from app.core.services.cache_manager import get_cache_manager
from app.core.services.memory import MemoryService
from app.core.services.search import SearchService
from app.core.services.unified_search import UnifiedSearchService

STARRED = (
    "Architecture decision the user starred for later reference — long enough "
    "fixture content to pass the quality gate and match the shared search query."
)
PLAIN = (
    "Routine note nobody starred — long enough fixture content to pass the "
    "quality gate and match the shared search query just like the starred one."
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
    starred = await memory_service.create(
        content=STARRED, category="decision", source="test"
    )
    plain = await memory_service.create(content=PLAIN, category="task", source="test")
    await memory_service.set_starred(starred.id, True)
    return starred, plain


class TestStarredOnlyFilter:
    """UnifiedSearchService — 전 모드에서 필터가 걸려야 한다"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "mode,query",
        [
            ("hybrid", "fixture content"),
            ("exact", "starred"),
            ("semantic", "architecture decision"),
            ("fuzzy", "architecure decison"),  # 오타
        ],
    )
    async def test_filter_applies_in_every_mode(
        self, memory_service, unified_service, mode, query
    ):
        starred, plain = await _seed(memory_service)
        result = await unified_service.search(
            query=query, search_mode=mode, starred_only=True, limit=20
        )
        ids = {r.id for r in result.results}
        assert plain.id not in ids, f"{mode} leaked an unstarred memory"
        assert all(r.is_starred for r in result.results)

    @pytest.mark.asyncio
    async def test_empty_query_recent_path_filters(
        self, memory_service, unified_service
    ):
        starred, plain = await _seed(memory_service)
        result = await unified_service.search(query="", starred_only=True, limit=20)
        assert [r.id for r in result.results] == [starred.id]

    @pytest.mark.asyncio
    async def test_no_starred_returns_empty_not_fallback(
        self, memory_service, unified_service
    ):
        """F4: 별표 0건이면 빈 결과 — 무필터 결과로 fallback하면 안 된다"""
        await memory_service.create(content=PLAIN, category="task", source="test")

        result = await unified_service.search(query="", starred_only=True, limit=20)
        assert result.results == []
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_id_prefix_shortcut_respects_filter(
        self, memory_service, unified_service
    ):
        """id 쇼트컷은 filters dict를 우회한다 — 별도 후필터가 필요"""
        starred, plain = await _seed(memory_service)

        # 별표된 id는 통과
        result = await unified_service.search(
            query=starred.id[:8], starred_only=True, limit=20
        )
        assert [r.id for r in result.results] == [starred.id]

        # 무별표 id는 필터에 걸려 이 경로로 새면 안 된다
        result = await unified_service.search(
            query=plain.id[:8], starred_only=True, limit=20
        )
        assert plain.id not in {r.id for r in result.results}

    @pytest.mark.asyncio
    async def test_cache_is_not_poisoned_across_filtered_and_unfiltered(
        self, memory_service, unified_service
    ):
        """F5: 무필터 → 필터 → 무필터 순서에서 캐시가 교차 오염되면 안 된다"""
        get_cache_manager().clear_all_caches()
        starred, plain = await _seed(memory_service)

        unfiltered = await unified_service.search(query="fixture content", limit=20)
        unfiltered_ids = {r.id for r in unfiltered.results}
        assert {starred.id, plain.id} <= unfiltered_ids

        filtered = await unified_service.search(
            query="fixture content", starred_only=True, limit=20
        )
        assert {r.id for r in filtered.results} == {starred.id}

        # 다시 무필터 — 필터 결과가 캐시를 덮어쓰지 않았어야 한다
        again = await unified_service.search(query="fixture content", limit=20)
        assert {r.id for r in again.results} == unfiltered_ids

    @pytest.mark.asyncio
    async def test_count_matches_filtered_results(
        self, memory_service, unified_service
    ):
        """count/pagination 총계가 필터와 어긋나면 '더 보기'가 깨진다"""
        starred, _ = await _seed(memory_service)
        result = await unified_service.search(query="", starred_only=True, limit=20)
        assert result.total == len(result.results) == 1


class TestLegacyStarredOnly:
    """레거시 SearchService (use_unified_search=False / batch 경로)"""

    @pytest.mark.asyncio
    async def test_empty_query_filters(self, memory_service, legacy_service):
        starred, plain = await _seed(memory_service)
        result = await legacy_service.search(query="", starred_only=True, limit=20)
        assert [r.id for r in result.results] == [starred.id]

    @pytest.mark.asyncio
    async def test_exact_mode_filters(self, memory_service, legacy_service):
        starred, plain = await _seed(memory_service)
        result = await legacy_service.search(
            query="starred", search_mode="exact", starred_only=True, limit=20
        )
        assert plain.id not in {r.id for r in result.results}


class TestTransportWiring:
    """전 트랜스포트 파라미터 전달 — 한 계층만 빠져도 조용히 무시된다"""

    def test_search_params_accepts_starred_only(self):
        assert SearchParams(query="q", starred_only=True).starred_only is True
        assert SearchParams(query="q").starred_only is False

    def test_mcp_search_schema_exposes_starred_only(self):
        from app.mcp_common.schemas import get_tool_schemas

        by_name = {s["name"]: s for s in get_tool_schemas()}
        props = by_name["search"]["inputSchema"]["properties"]
        assert props["starred_only"]["type"] == "boolean"

    def test_batch_search_op_schema_exposes_starred_only(self):
        """batch op 스키마는 search 프로퍼티의 별도 사본이다 (둘 다 닫혀 있음)"""
        from app.mcp_common.schemas import get_all_tool_schemas

        by_name = {s["name"]: s for s in get_all_tool_schemas()}
        op_props = by_name["batch_operations"]["inputSchema"]["properties"][
            "operations"
        ]["items"]["properties"]
        assert "starred_only" in op_props

    @pytest.mark.asyncio
    async def test_dispatcher_passes_starred_only(self):
        from app.mcp_common.dispatcher import MCPDispatcher
        from app.mcp_common.tools import MCPToolHandlers

        handlers = MagicMock(spec=MCPToolHandlers)
        handlers.search = AsyncMock(return_value={"results": [], "total": 0})
        dispatcher = MCPDispatcher(handlers)

        result = await dispatcher.dispatch(
            "search", {"query": "q", "starred_only": True}
        )
        assert result["isError"] is False
        assert handlers.search.call_args.kwargs["starred_only"] is True

    @pytest.mark.asyncio
    async def test_starred_only_forces_local_scope(self):
        """hub 행은 별표될 수 없다 — fan-out하면 무필터 hub 행만 새어 든다"""
        from app.core.schemas.responses import SearchResponse
        from app.mcp_common.tools import MCPToolHandlers

        storage = MagicMock()
        storage.search_memories = AsyncMock(
            return_value=SearchResponse(results=[], total=0)
        )
        storage.db = MagicMock()  # federation 가능한 것처럼 보이게

        handlers = MCPToolHandlers(storage, notifier=None, enable_compression=False)
        # scope='all'을 요청해도 starred_only면 hub로 나가면 안 된다
        result = await handlers.search(query="q", scope="all", starred_only=True)
        # federated 경로를 탔다면 hub_status가 붙는다 — local 강제면 안 붙음
        assert result.get("hub_status") is None

    def test_web_route_forwards_starred_only(self):
        import inspect

        from app.web.dashboard.route_modules.search import _do_search, search_memories

        assert "starred_only" in inspect.signature(_do_search).parameters
        assert "starred_only" in inspect.signature(search_memories).parameters

    def test_fastmcp_search_accepts_starred_only(self):
        import inspect

        from app.mcp_stdio import server

        fn = server.search.fn if hasattr(server.search, "fn") else server.search
        assert "starred_only" in inspect.signature(fn).parameters

    def test_api_storage_forwards_starred_only(self):
        import inspect

        from app.core.storage.api import APIStorageBackend

        src = inspect.getsource(APIStorageBackend.search_memories)
        assert "starred_only" in src, "APIStorageBackend silently drops starred_only"
