"""검색 결과 enrichment 노출 테스트 (회귀 방지).

버그: 검색 서비스는 enrichment를 붙이지 않고, 병합 코드가 MCP 핸들러에만 있었다.
그래서 enrich된 메모리가 MCP에서는 title/abstract를 달고 나왔지만 대시보드 REST
검색에서는 맨몸으로 나와, 웹에서 보면 "auto-enrich가 안 돈 것처럼" 보였다.
(실제로는 enrich 파이프라인은 정상 작동 중이었다.)

=> 노출 계층은 전부 attach_enrichment_to_results를 거쳐야 한다.
"""

import json
import os
import tempfile

import pytest

from app.core.database.base import Database
from app.core.schemas.responses import SearchResult
from app.core.services.recall import attach_enrichment_to_results

LONG = (
    "Raw memory content that nobody wants to read in a dashboard row — long "
    "enough to pass the quality gate and to be visibly different from a title."
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


async def _seed_enrichment(db, memory_id, *, title, abstract, tags):
    from app.core.services.enrich_store import EnrichmentStore

    await EnrichmentStore(db).ensure_schema()
    await db.execute(
        "INSERT OR REPLACE INTO memory_enrichment "
        "(memory_id, title, abstract, tags, created_at) VALUES (?, ?, ?, ?, ?)",
        (memory_id, title, abstract, json.dumps(tags), "2026-07-11T00:00:00Z"),
    )


def _result(mid, **kw):
    return SearchResult(
        id=mid,
        content=LONG,
        similarity_score=0.9,
        created_at="2026-07-11T00:00:00Z",
        project_id="mem-mesh",
        category="decision",
        source="test",
        **kw,
    )


class TestAttachEnrichment:
    @pytest.mark.asyncio
    async def test_attaches_title_abstract_tags(self, temp_db):
        r = _result("m1")
        await _seed_enrichment(
            temp_db, "m1", title="별표 설계 결정", abstract="A안 채택", tags=["star"]
        )

        await attach_enrichment_to_results(temp_db, [r])

        assert r.title == "별표 설계 결정"
        assert r.abstract == "A안 채택"
        assert r.enrichment_tags == ["star"]

    @pytest.mark.asyncio
    async def test_unenriched_memory_untouched(self, temp_db):
        r = _result("m-none")
        await attach_enrichment_to_results(temp_db, [r])
        assert r.title is None and r.abstract is None
        assert r.enrichment_tags is None

    @pytest.mark.asyncio
    async def test_does_not_overwrite_hub_enrichment(self, temp_db):
        """hub 결과는 이미 title/abstract를 달고 온다 — 덮어쓰면 안 된다"""
        r = _result("m2", title="hub title", abstract="hub abstract", origin="hub")
        await _seed_enrichment(
            temp_db, "m2", title="local title", abstract="local abstract", tags=[]
        )

        await attach_enrichment_to_results(temp_db, [r])

        assert r.title == "hub title"
        assert r.abstract == "hub abstract"

    @pytest.mark.asyncio
    async def test_no_db_or_empty_is_graceful(self, temp_db):
        assert await attach_enrichment_to_results(None, [_result("x")]) == {}
        assert await attach_enrichment_to_results(temp_db, []) == {}


class TestRestSearchSurfacesEnrichment:
    """대시보드 REST 검색이 enrichment를 실제로 실어 보내는가 (이 버그의 본체)"""

    @pytest.mark.asyncio
    async def test_do_search_attaches_enrichment(self, temp_db):
        from unittest.mock import AsyncMock, MagicMock

        from app.core.schemas.responses import SearchResponse
        from app.web.dashboard.route_modules.search import _do_search

        await _seed_enrichment(
            temp_db,
            "m1",
            title="enriched title",
            abstract="enriched abstract",
            tags=["topic"],
        )

        service = MagicMock()
        service.db = temp_db
        service.search = AsyncMock(
            return_value=SearchResponse(results=[_result("m1")], total=1)
        )

        resp = await _do_search(
            query="",
            project_id=None,
            category=None,
            source=None,
            tag=None,
            limit=10,
            offset=0,
            sort_by="created_at",
            sort_direction="desc",
            recency_weight=0.0,
            search_mode="hybrid",
            service=service,
        )

        assert resp.results[0].title == "enriched title"
        assert resp.results[0].abstract == "enriched abstract"
        assert resp.results[0].enrichment_tags == ["topic"]


class TestMcpSearchSurfacesEnrichment:
    """MCP 경로도 같은 헬퍼를 쓴다 (두 경로가 갈라지면 또 이 버그가 난다)"""

    @pytest.mark.asyncio
    async def test_mcp_search_attaches_enrichment(self, temp_db):
        from unittest.mock import AsyncMock, MagicMock

        from app.core.schemas.responses import SearchResponse
        from app.mcp_common.tools import MCPToolHandlers

        await _seed_enrichment(
            temp_db, "m1", title="mcp title", abstract="mcp abstract", tags=["t"]
        )

        storage = MagicMock()
        storage.db = temp_db
        storage.search_memories = AsyncMock(
            return_value=SearchResponse(results=[_result("m1")], total=1)
        )

        handlers = MCPToolHandlers(storage, notifier=None, enable_compression=False)
        out = await handlers.search(query="", limit=10, enable_noise_filter=False)

        assert out["results"][0]["title"] == "mcp title"
        assert out["results"][0]["enrichment_tags"] == ["t"]

    def test_both_surfaces_use_the_shared_helper(self):
        """구현이 다시 갈라지지 않도록 못 박는다"""
        import inspect

        from app.mcp_common import tools
        from app.web.dashboard.route_modules import search as search_route

        assert "attach_enrichment_to_results" in inspect.getsource(
            tools.MCPToolHandlers.search
        )
        assert "attach_enrichment_to_results" in inspect.getsource(
            search_route._do_search
        )
