"""WS3 (R2): 대시보드 검색 API scope — 기본 무영향·위임·병합·offset 가드."""

import pytest

import app.core.services.federated_search as fed_mod
from app.core.schemas.responses import SearchResponse
from app.web.dashboard.route_modules.search import _do_search


class _FakeService:
    """UnifiedSearchService stand-in: records local search calls, exposes .db."""

    def __init__(self, db=None):
        self.db = db if db is not None else object()
        self.calls = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return SearchResponse(results=[], total=0)


async def _call(service, **overrides):
    params = dict(
        query="q",
        project_id=None,
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
    )
    params.update(overrides)
    return await _do_search(**params)


@pytest.mark.asyncio
async def test_scope_local_is_default_and_bypasses_federation(monkeypatch):
    called = {"fed": False}

    class _Boom:
        def __init__(self, *a, **k):
            called["fed"] = True

    monkeypatch.setattr(fed_mod, "FederatedHubSearch", _Boom)
    svc = _FakeService()
    await _call(svc, scope="local")
    assert called["fed"] is False
    assert len(svc.calls) == 1  # single local search, unchanged behavior


@pytest.mark.asyncio
async def test_unknown_scope_falls_back_to_local(monkeypatch):
    called = {"fed": False}

    class _Boom:
        def __init__(self, *a, **k):
            called["fed"] = True

    monkeypatch.setattr(fed_mod, "FederatedHubSearch", _Boom)
    svc = _FakeService()
    await _call(svc, scope="bogus")
    assert called["fed"] is False
    assert len(svc.calls) == 1


@pytest.mark.asyncio
async def test_scope_all_delegates_and_merges_single_category(monkeypatch):
    captured = {}

    class _FakeFed:
        def __init__(self, db, settings, http_client=None):
            captured["db"] = db

        async def search(self, *, scope, query, limit, local_search, categories=None):
            captured["scope"] = scope
            captured["categories"] = categories
            return await local_search()

    monkeypatch.setattr(fed_mod, "FederatedHubSearch", _FakeFed)
    svc = _FakeService()
    await _call(svc, scope="all", category="decision")
    assert captured["scope"] == "all"
    assert captured["categories"] == ["decision"]  # D8: single→merged list
    assert captured["db"] is svc.db


@pytest.mark.asyncio
async def test_scope_all_offset_paginates_locally_without_hub(monkeypatch):
    captured = {}

    class _FakeFed:
        def __init__(self, *a, **k):
            captured["constructed"] = True

    monkeypatch.setattr(fed_mod, "FederatedHubSearch", _FakeFed)
    svc = _FakeService()
    await _call(svc, scope="all", offset=25)
    assert "constructed" not in captured  # hub not re-queried on Load more
    assert len(svc.calls) == 1  # local continuation only


@pytest.mark.asyncio
async def test_scope_hub_without_db_returns_skipped():
    svc = _FakeService(db=None)  # API-backed storage shape, no local DB
    out = await _call(svc, scope="hub")
    assert out.hub_status == "skipped"
    assert out.results == []
    assert len(svc.calls) == 0  # never answered with local results
