"""anchored_path 스코프 검색 + context 배치 드릴다운 테스트.

anchored_path는 anchors.file_paths 프리픽스로 검색 범위를 좁히는 필터다:
- SQL 절 헬퍼(anchored_path_filter_clause)의 경계/이스케이프 규칙
- SearchParams/normalize_anchored_path 검증 (상대 경로, '..' 금지, 정규화)
- UnifiedSearchService 전 모드(빈 쿼리/exact/semantic/fuzzy) 필터 적용
- 손상된 anchors JSON 행이 있어도 쿼리가 죽지 않아야 함 (json_valid 가드)
- 캐시 우회: 필터 검색이 무필터 캐시를 읽거나 오염시키지 않아야 함
- context(ids=[...]) 배치: id별 found/not_found, 상한, 인자 검증
"""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.database.base import Database, anchored_path_filter_clause
from app.core.schemas.requests import (
    SearchParams,
    normalize_anchored_path,
)
from app.core.services.memory import MemoryService
from app.core.services.search import SearchService
from app.core.services.unified_search import (
    UnifiedSearchService,
    _matches_anchored_path,
)
from app.mcp_common.tools import MCPToolHandlers

# 100자 이상: quality gate 통과용 본문
CORE_CONTENT = (
    "Decision about the embedding service internals — long enough fixture content "
    "to pass the quality gate. Documents why the core module was restructured."
)
WEB_CONTENT = (
    "Bug fixed in the web dashboard route handling — long enough fixture content "
    "to pass the quality gate. Describes the reproduction and the final patch."
)
NO_ANCHOR_CONTENT = (
    "General idea without any git anchors attached — long enough fixture content "
    "to pass the quality gate. Should never appear in anchored-path searches."
)

CORE_ANCHORS = {
    "commit_hash": "a1b2c3d",
    "file_paths": ["app/core/embeddings/service.py", "app/core/config.py"],
    "branch": "develop",
}
WEB_ANCHORS = {
    "commit_hash": "d4e5f6a",
    "file_paths": ["app/web/dashboard/routes.py"],
    "branch": "develop",
}


@pytest.fixture
async def temp_db():
    """임시 데이터베이스 픽스처"""
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
    """core 앵커 1건 + web 앵커 1건 + 무앵커 1건"""
    core = await memory_service.create(
        content=CORE_CONTENT, category="decision", source="test", anchors=CORE_ANCHORS
    )
    web = await memory_service.create(
        content=WEB_CONTENT, category="bug", source="test", anchors=WEB_ANCHORS
    )
    plain = await memory_service.create(
        content=NO_ANCHOR_CONTENT, category="idea", source="test"
    )
    return core, web, plain


class TestAnchoredPathFilterClause:
    """anchored_path_filter_clause 헬퍼 단위 테스트"""

    def test_none_returns_empty(self):
        assert anchored_path_filter_clause(None) == ("", [])

    def test_empty_string_returns_empty(self):
        assert anchored_path_filter_clause("") == ("", [])

    def test_slash_only_returns_empty(self):
        assert anchored_path_filter_clause("/") == ("", [])

    def test_basic_prefix_params(self):
        cond, params = anchored_path_filter_clause("app/core")
        assert "json_valid(anchors)" in cond
        assert "json_each(anchors, '$.file_paths')" in cond
        # 등호 비교 + substr 프리픽스 (경계 '/' 포함, 대소문자 구분)
        assert params == ["app/core", len("app/core") + 1, "app/core/"]

    def test_trailing_slash_stripped(self):
        _, params = anchored_path_filter_clause("app/core/")
        assert params == ["app/core", len("app/core") + 1, "app/core/"]

    def test_backslashes_normalized(self):
        _, params = anchored_path_filter_clause("app\\core")
        assert params == ["app/core", len("app/core") + 1, "app/core/"]

    def test_wildcards_are_literal(self):
        # substr 비교라 %/_는 리터럴 — LIKE 이스케이프가 아예 필요 없다
        _, params = anchored_path_filter_clause("a%b_c")
        assert params == ["a%b_c", len("a%b_c") + 1, "a%b_c/"]

    def test_stored_values_backslash_normalized_in_sql(self):
        # 레거시 행(Windows 클라이언트)의 백슬래시 저장값도 매치되도록 REPLACE
        cond, _ = anchored_path_filter_clause("app")
        assert "REPLACE(json_each.value, '\\', '/')" in cond

    def test_custom_column(self):
        cond, _ = anchored_path_filter_clause("app", column="m.anchors")
        assert "m.anchors IS NOT NULL" in cond
        assert "json_each(m.anchors, '$.file_paths')" in cond


class TestMatchesAnchoredPathMirror:
    """_matches_anchored_path — SQL 절의 Python 미러 (id 쇼트컷 경로용)"""

    def test_exact_file_match(self):
        assert _matches_anchored_path(CORE_ANCHORS, "app/core/embeddings/service.py")

    def test_directory_prefix_match(self):
        assert _matches_anchored_path(CORE_ANCHORS, "app/core")
        assert _matches_anchored_path(CORE_ANCHORS, "app/core/")

    def test_directory_boundary_not_substring(self):
        # 'app/co'는 'app/core/...'의 부분 문자열이지만 디렉토리 경계가 아니다
        assert not _matches_anchored_path(CORE_ANCHORS, "app/co")

    def test_no_anchors(self):
        assert not _matches_anchored_path(None, "app/core")
        assert not _matches_anchored_path({}, "app/core")
        assert not _matches_anchored_path({"commit_hash": "a1b2c3d"}, "app/core")


class TestAnchoredPathValidation:
    """normalize_anchored_path / SearchParams.anchored_path 검증"""

    def test_none_passthrough(self):
        assert normalize_anchored_path(None) is None

    def test_empty_normalizes_to_none(self):
        assert normalize_anchored_path("") is None
        assert normalize_anchored_path("  ") is None
        assert normalize_anchored_path("/") is None

    def test_normalization(self):
        assert normalize_anchored_path("app\\core\\") == "app/core"
        assert normalize_anchored_path("app/core/") == "app/core"

    @pytest.mark.parametrize("bad", ["/etc/passwd", "C:/Windows", "../x", "a/../b"])
    def test_rejects_absolute_and_traversal(self, bad):
        with pytest.raises(ValueError):
            normalize_anchored_path(bad)

    def test_search_params_field(self):
        assert SearchParams(query="q", anchored_path="app/core/").anchored_path == (
            "app/core"
        )
        assert SearchParams(query="q").anchored_path is None


class TestUnifiedAnchoredSearch:
    """UnifiedSearchService 전 모드 anchored_path 필터"""

    @pytest.mark.asyncio
    async def test_empty_query_filters_by_prefix(self, memory_service, unified_service):
        core, _, _ = await _seed(memory_service)
        result = await unified_service.search(query="", anchored_path="app/core")
        assert [r.id for r in result.results] == [core.id]

    @pytest.mark.asyncio
    async def test_exact_file_path_match(self, memory_service, unified_service):
        core, _, _ = await _seed(memory_service)
        result = await unified_service.search(
            query="", anchored_path="app/core/config.py"
        )
        assert [r.id for r in result.results] == [core.id]

    @pytest.mark.asyncio
    async def test_directory_boundary_excludes_lookalike(
        self, memory_service, unified_service
    ):
        """'app/core'가 'app/core_utils/...' 앵커에 매치되면 안 된다"""
        await memory_service.create(
            content=NO_ANCHOR_CONTENT,
            category="idea",
            source="test",
            anchors={"file_paths": ["app/core_utils/helper.py"]},
        )
        result = await unified_service.search(query="", anchored_path="app/core")
        assert result.results == []

    @pytest.mark.asyncio
    async def test_exact_mode_applies_filter(self, memory_service, unified_service):
        _, web, _ = await _seed(memory_service)
        result = await unified_service.search(
            query="dashboard", search_mode="exact", anchored_path="app/web"
        )
        assert [r.id for r in result.results] == [web.id]
        # 같은 쿼리라도 다른 프리픽스에서는 0건
        result = await unified_service.search(
            query="dashboard", search_mode="exact", anchored_path="app/core"
        )
        assert result.results == []

    @pytest.mark.asyncio
    async def test_semantic_mode_applies_filter(self, memory_service, unified_service):
        core, _, _ = await _seed(memory_service)
        result = await unified_service.search(
            query="embedding decision", search_mode="semantic", anchored_path="app/core"
        )
        assert {r.id for r in result.results} == {core.id}

    @pytest.mark.asyncio
    async def test_fuzzy_mode_applies_filter(self, memory_service, unified_service):
        _, web, _ = await _seed(memory_service)
        result = await unified_service.search(
            query="dashbord route", search_mode="fuzzy", anchored_path="app/web"
        )
        assert {r.id for r in result.results} <= {web.id}

    @pytest.mark.asyncio
    async def test_legacy_backslash_anchor_row_still_matches(
        self, memory_service, unified_service, temp_db
    ):
        """쓰기 정규화 이전에 저장된 백슬래시 경로도 SQL REPLACE로 매치돼야 한다"""
        core, _, _ = await _seed(memory_service)
        # validate_anchors를 우회해 레거시 형태(백슬래시)를 직접 주입
        await temp_db.execute(
            "UPDATE memories SET anchors = ? WHERE id = ?",
            (json.dumps({"file_paths": ["app\\core\\legacy.py"]}), core.id),
        )
        result = await unified_service.search(query="", anchored_path="app/core")
        assert [r.id for r in result.results] == [core.id]

    @pytest.mark.asyncio
    async def test_case_sensitive_in_sql_and_mirror(
        self, memory_service, unified_service
    ):
        """대소문자 구분이 SQL(substr)과 Python 미러에서 동일해야 한다"""
        await memory_service.create(
            content=NO_ANCHOR_CONTENT,
            category="idea",
            source="test",
            anchors={"file_paths": ["App/Core/z.py"]},
        )
        result = await unified_service.search(query="", anchored_path="app/core")
        assert result.results == []
        assert not _matches_anchored_path({"file_paths": ["App/Core/z.py"]}, "app/core")

    @pytest.mark.asyncio
    async def test_corrupt_anchors_row_does_not_break_query(
        self, memory_service, unified_service, temp_db
    ):
        """손상된 anchors JSON이 있어도 (json_valid 가드) 쿼리는 성공해야 한다"""
        core, _, _ = await _seed(memory_service)
        await temp_db.execute(
            "UPDATE memories SET anchors = ? WHERE id != ?",
            ("{not-valid-json", core.id),
        )
        result = await unified_service.search(query="", anchored_path="app/core")
        assert [r.id for r in result.results] == [core.id]

    @pytest.mark.asyncio
    async def test_anchored_search_bypasses_cache(
        self, memory_service, unified_service
    ):
        """필터 검색이 무필터 캐시를 읽지도, 오염시키지도 않아야 한다"""
        core, web, plain = await _seed(memory_service)

        # 1. 무필터 검색 → 캐시에 저장됨 (모든 결과)
        unfiltered = await unified_service.search(query="fixture content")
        unfiltered_ids = {r.id for r in unfiltered.results}
        assert core.id in unfiltered_ids and web.id in unfiltered_ids

        # 2. 같은 쿼리 + anchored_path → 캐시 히트가 아니라 필터된 결과
        filtered = await unified_service.search(
            query="fixture content", anchored_path="app/core"
        )
        assert {r.id for r in filtered.results} == {core.id}

        # 3. 다시 무필터 → 여전히 전체 결과 (필터 결과로 오염되지 않음)
        again = await unified_service.search(query="fixture content")
        assert {r.id for r in again.results} == unfiltered_ids


class TestLegacyAnchoredSearch:
    """레거시 SearchService (use_unified_search=False / BatchOperationHandler 경로)"""

    @pytest.mark.asyncio
    async def test_empty_query_filters_by_prefix(self, memory_service, legacy_service):
        core, _, _ = await _seed(memory_service)
        result = await legacy_service.search(query="", anchored_path="app/core")
        assert [r.id for r in result.results] == [core.id]
        assert result.total == 1

    @pytest.mark.asyncio
    async def test_exact_mode_applies_filter(self, memory_service, legacy_service):
        _, web, _ = await _seed(memory_service)
        result = await legacy_service.search(
            query="dashboard", search_mode="exact", anchored_path="app/web"
        )
        assert [r.id for r in result.results] == [web.id]


class TestContextBatch:
    """context(ids=[...]) 배치 드릴다운 (MCPToolHandlers 레벨)"""

    def _handlers(self, found_ids):
        """storage.get_context를 mock — found_ids만 성공"""
        from app.core.errors import ContextNotFoundError

        storage = MagicMock()

        async def fake_get_context(memory_id, depth, project_id):
            if memory_id not in found_ids:
                raise ContextNotFoundError(f"not found: {memory_id}")
            response = MagicMock()
            response.model_dump.return_value = {
                "primary_memory": {"id": memory_id},
                "related_memories": [],
            }
            response.related_memories = []
            return response

        storage.get_context = AsyncMock(side_effect=fake_get_context)
        return MCPToolHandlers(storage, notifier=None, enable_compression=False)

    @pytest.mark.asyncio
    async def test_batch_found_and_not_found(self):
        handlers = self._handlers(found_ids={"id-1", "id-3"})
        result = await handlers.context(ids=["id-1", "id-2", "id-3"])
        assert result["batch"] is True
        assert [m["primary_memory"]["id"] for m in result["memories"]] == [
            "id-1",
            "id-3",
        ]
        assert result["not_found"] == ["id-2"]

    @pytest.mark.asyncio
    async def test_batch_over_cap_rejected(self):
        from app.core.errors import ValidationError

        handlers = self._handlers(found_ids=set())
        with pytest.raises(ValidationError):
            await handlers.context(ids=[f"id-{i}" for i in range(11)])

    @pytest.mark.asyncio
    async def test_batch_empty_list_rejected(self):
        from app.core.errors import ValidationError

        handlers = self._handlers(found_ids=set())
        with pytest.raises(ValidationError):
            await handlers.context(ids=[])

    @pytest.mark.asyncio
    async def test_neither_memory_id_nor_ids_rejected(self):
        from app.core.errors import ValidationError

        handlers = self._handlers(found_ids=set())
        with pytest.raises(ValidationError):
            await handlers.context()

    @pytest.mark.asyncio
    async def test_string_ids_rejected_not_iterated(self):
        """문자열 ids가 문자 단위로 순회되면 안 된다 (Pure MCP 무검증 경로)"""
        from app.core.errors import ValidationError

        handlers = self._handlers(found_ids=set())
        with pytest.raises(ValidationError):
            await handlers.context(ids="f9732f1e")

    @pytest.mark.asyncio
    async def test_infra_failure_propagates_not_swallowed(self):
        """인프라 장애(RuntimeError)는 not_found로 위장되지 않고 전파돼야 한다"""
        storage = MagicMock()
        storage.get_context = AsyncMock(
            side_effect=RuntimeError("Failed to get context: connection refused")
        )
        handlers = MCPToolHandlers(storage, notifier=None, enable_compression=False)
        with pytest.raises(RuntimeError):
            await handlers.context(ids=["id-1", "id-2"])

    @pytest.mark.asyncio
    async def test_single_id_mode_unchanged(self):
        handlers = self._handlers(found_ids={"id-1"})
        result = await handlers.context(memory_id="id-1")
        assert result["primary_memory"]["id"] == "id-1"
        assert "batch" not in result


class TestDispatcherForwarding:
    """dispatcher가 새 파라미터를 핸들러까지 전달하는지"""

    @pytest.fixture
    def mock_handlers(self):
        handlers = MagicMock(spec=MCPToolHandlers)
        handlers.search = AsyncMock(return_value={"results": [], "total": 0})
        handlers.context = AsyncMock(
            return_value={"memories": [], "not_found": [], "batch": True}
        )
        return handlers

    @pytest.fixture
    def dispatcher(self, mock_handlers):
        from app.mcp_common.dispatcher import MCPDispatcher

        return MCPDispatcher(mock_handlers)

    @pytest.mark.asyncio
    async def test_dispatcher_passes_anchored_path_to_handlers(
        self, dispatcher, mock_handlers
    ):
        result = await dispatcher.dispatch(
            "search", {"query": "q", "anchored_path": "app/core"}
        )
        assert result["isError"] is False
        assert mock_handlers.search.call_args.kwargs["anchored_path"] == "app/core"

    @pytest.mark.asyncio
    async def test_dispatcher_passes_ids_to_context(self, dispatcher, mock_handlers):
        result = await dispatcher.dispatch("context", {"ids": ["id-1", "id-2"]})
        assert result["isError"] is False
        assert mock_handlers.context.call_args.kwargs["ids"] == ["id-1", "id-2"]

    @pytest.mark.asyncio
    async def test_dispatcher_context_still_requires_id_or_ids(self, dispatcher):
        result = await dispatcher.dispatch("context", {"depth": 2})
        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert "memory_id" in response_data["error"].lower()


class TestSchemaExposure:
    """MCP tool 스키마 노출 (Pure stdio / SSE 트랜스포트)"""

    def test_search_schema_exposes_anchored_path(self):
        from app.mcp_common.schemas import get_tool_schemas

        by_name = {s["name"]: s for s in get_tool_schemas()}
        props = by_name["search"]["inputSchema"]["properties"]
        assert "anchored_path" in props

    def test_context_schema_exposes_ids_and_relaxed_required(self):
        from app.mcp_common.schemas import get_tool_schemas

        by_name = {s["name"]: s for s in get_tool_schemas()}
        schema = by_name["context"]["inputSchema"]
        assert "ids" in schema["properties"]
        assert schema["properties"]["ids"]["maxItems"] == 10
        # memory_id 단독 필수가 아니라 memory_id-또는-ids
        # (배타 제약은 tools.context()가 런타임 검증 — 스키마에 넣으면 안 된다)
        assert "required" not in schema

    def test_no_top_level_combinators_in_any_tool_schema(self):
        """Anthropic API는 input_schema top-level의 anyOf/oneOf/allOf를 400으로 거부한다."""
        from app.mcp_common.schemas import get_all_tool_schemas

        violations = [
            (s["name"], key)
            for s in get_all_tool_schemas()
            for key in ("anyOf", "oneOf", "allOf")
            if key in s["inputSchema"]
        ]
        assert violations == []

    def test_anchors_schema_exposes_file_hashes(self):
        from app.mcp_common.schemas import ANCHORS_SCHEMA

        assert "file_hashes" in ANCHORS_SCHEMA["properties"]
        assert ANCHORS_SCHEMA["properties"]["file_hashes"]["maxProperties"] == 20
