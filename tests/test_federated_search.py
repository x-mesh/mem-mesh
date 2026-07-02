"""FederatedHubSearch unit tests — scope routing, degrade, own-node filtering."""

from types import SimpleNamespace
from typing import Optional

import pytest

from app.core.schemas.relay import RelaySearchResponse, RelaySearchResult
from app.core.schemas.responses import SearchResponse, SearchResult
from app.core.services.federated_search import (
    HUB_OK,
    HUB_SKIPPED,
    HUB_UNAVAILABLE,
    FederatedHubSearch,
)


def _settings(timeout: float = 2.5, hub_weight: float = 0.75) -> SimpleNamespace:
    return SimpleNamespace(
        relay_federated_timeout=timeout,
        relay_federated_hub_weight=hub_weight,
    )


def _local_result(memory_id: str) -> SearchResult:
    return SearchResult(
        id=memory_id,
        content=f"local content {memory_id}",
        similarity_score=0.9,
        created_at="2026-07-01T00:00:00Z",
        project_id="proj",
        category="decision",
        source="mcp",
    )


def _hub_item(
    memory_id: str, *, source_node_id: str = "node-2", score: float = 0.8
) -> RelaySearchResult:
    return RelaySearchResult(
        id=memory_id,
        content=f"hub content {memory_id}",
        team_project_id="team-proj",
        source_node_id=source_node_id,
        source_memory_id=f"src-{memory_id}",
        source_version=1,
        kind="decision",
        status="active",
        tags=["relay"],
        title=f"Title {memory_id}",
        abstract=None,
        rank=1,
        score=score,
        updated_at="2026-07-01T01:00:00Z",
    )


class _FakeRelayHTTPClient:
    """send_search stub: returns a canned response or raises."""

    def __init__(
        self,
        response: Optional[RelaySearchResponse] = None,
        error: Optional[Exception] = None,
    ):
        self.response = response
        self.error = error
        self.calls = []

    async def send_search(self, *, target_hub, bearer_token, payload, timeout=None):
        self.calls.append(
            {
                "target_hub": target_hub,
                "bearer_token": bearer_token,
                "payload": payload,
                "timeout": timeout,
            }
        )
        if self.error is not None:
            raise self.error
        return self.response


def _federated(
    monkeypatch,
    *,
    client: _FakeRelayHTTPClient,
    cfg: Optional[dict] = None,
    settings: Optional[SimpleNamespace] = None,
) -> FederatedHubSearch:
    fed = FederatedHubSearch(
        db=None, settings=settings or _settings(), http_client=client
    )

    async def _fake_hub_config():
        return (
            cfg
            if cfg is not None
            else {
                "hub_url": "https://hub.example.com",
                "hub_token": "hub-token",
                "source_node_id": "node-1",
            }
        )

    monkeypatch.setattr(fed, "_hub_config", _fake_hub_config)
    return fed


async def _local_search_single() -> SearchResponse:
    return SearchResponse(results=[_local_result("local-1")], total=1)


@pytest.mark.asyncio
async def test_scope_local_bypasses_hub_entirely(monkeypatch):
    client = _FakeRelayHTTPClient()
    fed = _federated(monkeypatch, client=client)

    response = await fed.search(
        scope="local", query="q", limit=5, local_search=_local_search_single
    )

    assert client.calls == []
    assert response.hub_status is None
    assert [r.id for r in response.results] == ["local-1"]


@pytest.mark.asyncio
async def test_scope_all_fuses_and_marks_origin(monkeypatch):
    client = _FakeRelayHTTPClient(
        response=RelaySearchResponse(
            results=[_hub_item("hub-1")],
            total=1,
        )
    )
    fed = _federated(monkeypatch, client=client)

    response = await fed.search(
        scope="all", query="q", limit=5, local_search=_local_search_single
    )

    assert response.hub_status == HUB_OK
    origins = {r.id: r.origin for r in response.results}
    assert origins == {"local-1": "local", "hub-1": "hub"}
    # local outranks hub at equal rank (weighted RRF)
    assert response.results[0].id == "local-1"
    hub_result = next(r for r in response.results if r.id == "hub-1")
    assert hub_result.source == "relay-hub"
    assert hub_result.title == "Title hub-1"
    assert hub_result.created_at == "2026-07-01T01:00:00Z"
    # exclude_source_node was sent to the hub
    assert client.calls[0]["payload"].exclude_source_node == "node-1"


@pytest.mark.asyncio
async def test_scope_all_filters_own_node_items_client_side(monkeypatch):
    client = _FakeRelayHTTPClient(
        response=RelaySearchResponse(
            results=[
                _hub_item("mine-echo", source_node_id="node-1"),
                _hub_item("hub-2", source_node_id="node-2"),
            ],
            total=2,
        )
    )
    fed = _federated(monkeypatch, client=client)

    response = await fed.search(
        scope="all", query="q", limit=5, local_search=_local_search_single
    )

    ids = [r.id for r in response.results]
    assert "mine-echo" not in ids
    assert "hub-2" in ids


@pytest.mark.asyncio
async def test_scope_all_degrades_to_local_when_hub_errors(monkeypatch):
    client = _FakeRelayHTTPClient(error=RuntimeError("connection refused"))
    fed = _federated(monkeypatch, client=client)

    response = await fed.search(
        scope="all", query="q", limit=5, local_search=_local_search_single
    )

    assert response.hub_status == HUB_UNAVAILABLE
    assert [r.id for r in response.results] == ["local-1"]


@pytest.mark.asyncio
async def test_scope_all_skips_when_hub_not_configured(monkeypatch):
    client = _FakeRelayHTTPClient()
    fed = _federated(
        monkeypatch,
        client=client,
        cfg={"hub_url": "", "hub_token": "", "source_node_id": ""},
    )

    response = await fed.search(
        scope="all", query="q", limit=5, local_search=_local_search_single
    )

    assert client.calls == []
    assert response.hub_status == HUB_SKIPPED
    assert [r.id for r in response.results] == ["local-1"]


@pytest.mark.asyncio
async def test_scope_hub_returns_hub_only(monkeypatch):
    client = _FakeRelayHTTPClient(
        response=RelaySearchResponse(results=[_hub_item("hub-1")], total=1)
    )
    fed = _federated(monkeypatch, client=client)

    called = False

    async def _local_should_not_run() -> SearchResponse:
        nonlocal called
        called = True
        return SearchResponse(results=[], total=0)

    response = await fed.search(
        scope="hub", query="q", limit=5, local_search=_local_should_not_run
    )

    assert called is False
    assert response.hub_status == HUB_OK
    assert [r.origin for r in response.results] == ["hub"]


@pytest.mark.asyncio
async def test_dispatcher_passes_scope_to_handlers():
    from app.mcp_common.dispatcher import MCPDispatcher

    captured = {}

    class _StubHandlers:
        async def search(self, **kwargs):
            captured.update(kwargs)
            return {"results": []}

    dispatcher = MCPDispatcher(_StubHandlers())
    await dispatcher._dispatch_search({"query": "q", "scope": "all"})
    assert captured["scope"] == "all"

    captured.clear()
    await dispatcher._dispatch_search({"query": "q"})
    assert captured["scope"] == "local"


@pytest.mark.asyncio
async def test_fetch_hub_results_filters_by_category(monkeypatch):
    client = _FakeRelayHTTPClient(
        response=RelaySearchResponse(
            results=[
                _hub_item("hub-decision"),  # kind="decision"
                RelaySearchResult(
                    id="hub-bug",
                    content="hub bug content",
                    team_project_id="team-proj",
                    source_node_id="node-2",
                    source_memory_id="src-bug",
                    source_version=1,
                    kind="bug",
                    status="active",
                    tags=[],
                    title=None,
                    abstract=None,
                    rank=2,
                    score=0.5,
                    updated_at=None,
                ),
            ],
            total=2,
        )
    )
    fed = _federated(monkeypatch, client=client)

    results, status = await fed.fetch_hub_results(
        query="q", limit=5, categories=["bug"]
    )

    assert status == HUB_OK
    assert [r.id for r in results] == ["hub-bug"]


@pytest.mark.asyncio
async def test_unknown_scope_falls_back_to_local(monkeypatch):
    client = _FakeRelayHTTPClient()
    fed = _federated(monkeypatch, client=client)

    response = await fed.search(
        scope="everything", query="q", limit=5, local_search=_local_search_single
    )

    assert client.calls == []
    assert response.hub_status is None
    assert [r.id for r in response.results] == ["local-1"]


class _StubStorage:
    """Storage stub without a db handle (API-backed storage shape)."""

    def __init__(self, results=None):
        self._results = results or []

    async def search_memories(self, params):
        return SearchResponse(results=list(self._results), total=len(self._results))


class _StubStorageWithDb(_StubStorage):
    def __init__(self, results=None):
        super().__init__(results)
        self.db = object()


@pytest.mark.asyncio
async def test_mcp_search_scope_hub_without_db_returns_empty_skipped():
    from app.mcp_common.tools import MCPToolHandlers

    handlers = MCPToolHandlers(
        _StubStorage([_local_result("local-1")]), enable_compression=False
    )
    result = await handlers.search("q", scope="hub", enable_noise_filter=False)

    assert result["hub_status"] == "skipped"
    assert result["results"] == []


@pytest.mark.asyncio
async def test_mcp_search_scope_all_without_db_degrades_to_local_skipped():
    from app.mcp_common.tools import MCPToolHandlers

    handlers = MCPToolHandlers(
        _StubStorage([_local_result("local-1")]), enable_compression=False
    )
    result = await handlers.search("q", scope="all", enable_noise_filter=False)

    assert result["hub_status"] == "skipped"
    assert [r["id"] for r in result["results"]] == ["local-1"]


@pytest.mark.asyncio
async def test_mcp_search_scope_all_with_db_uses_federated(monkeypatch):
    import app.core.services.federated_search as fed_mod
    from app.mcp_common.tools import MCPToolHandlers

    captured = {}

    class _FakeFederated:
        def __init__(self, db, settings, http_client=None):
            captured["db"] = db

        async def search(self, *, scope, query, limit, local_search, categories=None):
            captured["scope"] = scope
            captured["categories"] = categories
            local = await local_search()
            local.hub_status = "ok"
            return local

    monkeypatch.setattr(fed_mod, "FederatedHubSearch", _FakeFederated)

    handlers = MCPToolHandlers(
        _StubStorageWithDb([_local_result("local-1")]), enable_compression=False
    )
    result = await handlers.search(
        "q", scope="all", category="decision", enable_noise_filter=False
    )

    assert captured["scope"] == "all"
    assert captured["categories"] == ["decision"]
    assert result["hub_status"] == "ok"


def test_search_url_normalization():
    from app.core.services.relay import RelayHTTPClient

    assert (
        RelayHTTPClient._search_url("https://hub.example.com")
        == "https://hub.example.com/api/relay/v1/search"
    )
    assert (
        RelayHTTPClient._search_url("https://hub.example.com/api/relay/v1/search")
        == "https://hub.example.com/api/relay/v1/search"
    )
    assert (
        RelayHTTPClient._search_url("https://hub.example.com/api/relay/v1/ingest")
        == "https://hub.example.com/api/relay/v1/search"
    )
    assert (
        RelayHTTPClient._search_url("https://hub.example.com/api/relay/v1")
        == "https://hub.example.com/api/relay/v1/search"
    )


@pytest.mark.asyncio
async def test_send_search_raises_relay_unauthorized_on_401():
    from app.core.schemas.relay import RelaySearchRequest
    from app.core.services.relay import RelayHTTPClient, RelayUnauthorized

    class _Resp:
        status_code = 401
        text = "unauthorized"

        def json(self):
            return {"detail": "bad token"}

    class _Client:
        async def post(self, url, *, headers, json, timeout):
            return _Resp()

    client = RelayHTTPClient(http_client=_Client())
    with pytest.raises(RelayUnauthorized):
        await client.send_search(
            target_hub="https://hub.example.com",
            bearer_token="bad",
            payload=RelaySearchRequest(query="q", limit=1),
        )
