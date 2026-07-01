"""다중 카테고리 검색의 요청 스키마/라우트 계층 테스트

- SearchParams.categories 밸리데이터 (item 3)
- 라우트 _do_search 의 categories 정제(dedupe + valid-only + cap) (item 4)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.core.schemas.requests import SearchParams
from app.core.schemas.responses import SearchResponse
from app.web.dashboard.route_modules.search import _do_search


class TestSearchParamsCategories:
    """SearchParams.categories 밸리데이터 테스트"""

    def test_valid_multi_categories_accepted(self):
        params = SearchParams(query="", categories=["bug", "idea"])
        assert params.categories == ["bug", "idea"]

    def test_invalid_category_in_list_rejected(self):
        with pytest.raises(ValidationError):
            SearchParams(query="", categories=["bug", "bogus"])

    def test_categories_default_none(self):
        params = SearchParams(query="")
        assert params.categories is None

    def test_single_category_backward_compat(self):
        params = SearchParams(query="", category="bug")
        assert params.category == "bug"
        assert params.categories is None

    def test_single_invalid_category_rejected(self):
        with pytest.raises(ValidationError):
            SearchParams(query="", category="bogus")


class TestDoSearchCategorySanitization:
    """_do_search 의 categories 정제 로직 테스트 (mock service)"""

    def _mock_service(self):
        service = MagicMock()
        service.search = AsyncMock(return_value=SearchResponse(results=[]))
        return service

    async def _call(self, service, categories):
        return await _do_search(
            query="",
            project_id="test-project",
            category=None,
            source=None,
            tag=None,
            limit=25,
            offset=0,
            sort_by="created_at",
            sort_direction="desc",
            recency_weight=0.0,
            search_mode="hybrid",
            service=service,
            categories=categories,
        )

    @pytest.mark.asyncio
    async def test_dedupe_and_drop_invalid(self):
        """중복 제거 + 유효하지 않은 카테고리 제거 (순서 보존)"""
        service = self._mock_service()

        # bug 중복, bogus 무효 → ["bug", "incident"]
        await self._call(service, ["bug", "bug", "bogus", "incident"])

        assert service.search.await_count == 1
        passed = service.search.await_args.kwargs["categories"]
        assert passed == ["bug", "incident"]

    @pytest.mark.asyncio
    async def test_all_invalid_becomes_none(self):
        """유효한 값이 하나도 없으면 None 으로 (전체 필터 무효화)"""
        service = self._mock_service()

        await self._call(service, ["bogus", "nope"])

        passed = service.search.await_args.kwargs["categories"]
        assert passed is None

    @pytest.mark.asyncio
    async def test_valid_categories_passthrough(self):
        """유효한 카테고리는 순서 유지하여 그대로 전달"""
        service = self._mock_service()

        await self._call(service, ["idea", "task"])

        passed = service.search.await_args.kwargs["categories"]
        assert passed == ["idea", "task"]
