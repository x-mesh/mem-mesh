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
    HubCircuitBreaker,
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
    breaker: Optional[HubCircuitBreaker] = None,
) -> FederatedHubSearch:
    # A fresh breaker per test keeps failure state from leaking through the
    # process-wide shared instance.
    fed = FederatedHubSearch(
        db=None,
        settings=settings or _settings(),
        http_client=client,
        breaker=breaker or HubCircuitBreaker(),
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
async def test_fetch_hub_results_sends_kinds_and_overfetches(monkeypatch):
    client = _FakeRelayHTTPClient(
        response=RelaySearchResponse(results=[_hub_item("hub-1")], total=1)
    )
    fed = _federated(monkeypatch, client=client)

    await fed.fetch_hub_results(query="q", limit=5, categories=["bug", "decision"])

    payload = client.calls[0]["payload"]
    # Server-side kind filter travels with the request...
    assert payload.kinds == ["bug", "decision"]
    # ...and the request over-fetches to survive client-side re-filtering
    # against older hubs that ignore the field.
    assert payload.limit == 10

    await fed.fetch_hub_results(query="q", limit=5)
    assert client.calls[1]["payload"].kinds is None
    assert client.calls[1]["payload"].limit == 5


@pytest.mark.asyncio
async def test_circuit_breaker_skips_hub_after_consecutive_failures(monkeypatch):
    client = _FakeRelayHTTPClient(error=RuntimeError("connection refused"))
    now = [1000.0]
    breaker = HubCircuitBreaker(clock=lambda: now[0])
    settings = SimpleNamespace(
        relay_federated_timeout=2.5,
        relay_federated_hub_weight=0.75,
        relay_federated_breaker_threshold=3,
        relay_federated_breaker_cooldown=30.0,
    )
    fed = _federated(monkeypatch, client=client, settings=settings, breaker=breaker)

    for _ in range(3):
        results, status = await fed.fetch_hub_results(query="q", limit=5)
        assert status == HUB_UNAVAILABLE
    assert len(client.calls) == 3

    # Breaker is open: the hub is not called at all inside the cooldown.
    results, status = await fed.fetch_hub_results(query="q", limit=5)
    assert status == HUB_UNAVAILABLE
    assert len(client.calls) == 3

    # After the cooldown a single probe goes through (half-open) and its
    # failure re-opens the circuit.
    now[0] += 31.0
    await fed.fetch_hub_results(query="q", limit=5)
    assert len(client.calls) == 4
    await fed.fetch_hub_results(query="q", limit=5)
    assert len(client.calls) == 4

    # A successful probe closes the breaker again.
    now[0] += 31.0
    client.error = None
    client.response = RelaySearchResponse(results=[_hub_item("hub-1")], total=1)
    results, status = await fed.fetch_hub_results(query="q", limit=5)
    assert status == HUB_OK
    assert len(client.calls) == 5
    results, status = await fed.fetch_hub_results(query="q", limit=5)
    assert status == HUB_OK
    assert len(client.calls) == 6


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


# --- WS1 (R1): MCP 압축응답 federation 메타 보존 -------------------------------


def _hub_search_result(memory_id: str) -> SearchResult:
    """origin='hub' + enrichment(title/abstract)을 가진 federated 결과."""
    return SearchResult(
        id=memory_id,
        content=f"hub content {memory_id}",
        similarity_score=0.8,
        created_at="2026-07-01T01:00:00Z",
        project_id="team-proj",
        category="decision",
        source="relay",
        origin="hub",
        title=f"Title {memory_id}",
        abstract=f"Abstract {memory_id}",
    )


def _compress_handlers():
    from app.mcp_common.tools import MCPToolHandlers

    return MCPToolHandlers(_StubStorage(), enable_compression=False)


@pytest.mark.parametrize("fmt", ["minimal", "compact", "standard"])
def test_compress_envelope_always_has_hub_status_key(fmt):
    """R1.1: hub_status는 3포맷 top-level에 항상 존재(None이어도 키 유지)."""
    handlers = _compress_handlers()
    # 로컬 전용(hub_status=None)
    resp_local = SearchResponse(results=[_local_result("local-1")], hub_status=None)
    out = handlers._compress_search_response(resp_local, fmt)
    assert "hub_status" in out
    assert out["hub_status"] is None
    # 융합(hub_status='ok')
    resp_fused = SearchResponse(
        results=[_local_result("local-1"), _hub_search_result("hub-1")],
        hub_status=HUB_OK,
    )
    out2 = handlers._compress_search_response(resp_fused, fmt)
    assert out2["hub_status"] == HUB_OK


def test_compress_standard_marks_hub_origin_only():
    """R1.2/R1.3: standard에서 origin='hub'는 hub 결과만, 로컬엔 origin 키 없음."""
    handlers = _compress_handlers()
    resp = SearchResponse(
        results=[_local_result("local-1"), _hub_search_result("hub-1")],
        hub_status=HUB_OK,
    )
    out = handlers._compress_search_response(resp, "standard")
    by_id = {r["id"]: r for r in out["results"]}
    assert "origin" not in by_id["local-1"]  # N3: 로컬 origin 미반복
    assert by_id["hub-1"]["origin"] == "hub"
    assert by_id["hub-1"]["title"] == "Title hub-1"
    assert by_id["hub-1"]["abstract"] == "Abstract hub-1"


def test_compress_compact_marks_hub_origin_only():
    handlers = _compress_handlers()
    resp = SearchResponse(
        results=[_local_result("local-1"), _hub_search_result("hub-1")],
        hub_status=HUB_OK,
    )
    out = handlers._compress_search_response(resp, "compact")
    by_id = {r["id"][:8]: r for r in out["results"]}
    assert "origin" not in by_id["local-1"[:8]]
    assert by_id["hub-1"[:8]]["origin"] == "hub"


def test_compress_minimal_keeps_id_score_only_plus_envelope_hub_status():
    """R1.2: minimal per-result은 origin 제외({id,score}), envelope엔 hub_status."""
    handlers = _compress_handlers()
    resp = SearchResponse(
        results=[_local_result("local-1"), _hub_search_result("hub-1")],
        hub_status=HUB_OK,
    )
    out = handlers._compress_search_response(resp, "minimal")
    for item in out["results"]:
        assert set(item.keys()) == {"id", "score"}
    assert out["hub_status"] == HUB_OK


def test_compress_local_only_has_no_origin_anywhere():
    handlers = _compress_handlers()
    resp = SearchResponse(results=[_local_result("a"), _local_result("b")])
    for fmt in ("compact", "standard"):
        out = handlers._compress_search_response(resp, fmt)
        assert all("origin" not in r for r in out["results"])
        assert out["hub_status"] is None


# --- WS2 (R7 전반부): read_cached_team_digest 로컬 read 헬퍼 --------------------

import json as _json  # noqa: E402
from datetime import datetime as _dt  # noqa: E402
from datetime import timedelta as _td  # noqa: E402
from datetime import timezone as _tz  # noqa: E402
from types import SimpleNamespace as _NS  # noqa: E402

from app.core.services.federated_search import (  # noqa: E402
    read_cached_team_digest,
    session_digest_config_key,
)


class _FakeDigestDB:
    def __init__(self, config=None, raise_on_get=False):
        self._config = config or {}
        self._raise = raise_on_get

    async def get_app_config(self, key):
        if self._raise:
            raise RuntimeError("db boom")
        return self._config.get(key)


def _digest_settings(enabled=True, max_age=60):
    return _NS(
        relay_federated_session_digest_enabled=enabled,
        relay_federated_session_digest_max_age_minutes=max_age,
    )


def _cached(project_id, *, age_minutes=1, summary="Team shipped X.", count=3):
    fetched = _dt.now(_tz.utc) - _td(minutes=age_minutes)
    payload = {
        "summary": summary,
        "source_count": count,
        "generated_at": "2026-07-10T00:00:00Z",
        "fetched_at": fetched.isoformat(),
    }
    return {session_digest_config_key(project_id): _json.dumps(payload)}


def _patch_relay(monkeypatch, *, enabled):
    """Stub federated_search.RelayService so the auto-share gate is controllable."""
    import app.core.services.federated_search as fs

    class _Sub:
        def __init__(self):
            self.enabled = enabled

    class _Relay:
        def __init__(self, db):
            pass

        async def get_project_auto_share(self, project_id):
            return None if enabled is None else _Sub()

    monkeypatch.setattr(fs, "RelayService", _Relay)


@pytest.mark.asyncio
async def test_read_digest_cache_hit(monkeypatch):
    _patch_relay(monkeypatch, enabled=True)
    db = _FakeDigestDB(_cached("proj", age_minutes=1))
    out = await read_cached_team_digest(db, "proj", _digest_settings())
    assert out == {
        "summary": "Team shipped X.",
        "source_count": 3,
        "generated_at": "2026-07-10T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_read_digest_stale_beyond_max_age(monkeypatch):
    _patch_relay(monkeypatch, enabled=True)
    db = _FakeDigestDB(_cached("proj", age_minutes=120))
    out = await read_cached_team_digest(db, "proj", _digest_settings(max_age=60))
    assert out is None


@pytest.mark.asyncio
async def test_read_digest_absent(monkeypatch):
    _patch_relay(monkeypatch, enabled=True)
    db = _FakeDigestDB({})  # no cached row
    out = await read_cached_team_digest(db, "proj", _digest_settings())
    assert out is None


@pytest.mark.asyncio
async def test_read_digest_auto_share_gate_blocks(monkeypatch):
    _patch_relay(monkeypatch, enabled=False)  # subscription disabled
    db = _FakeDigestDB(_cached("proj"))
    out = await read_cached_team_digest(db, "proj", _digest_settings())
    assert out is None
    # And when there is no subscription at all:
    _patch_relay(monkeypatch, enabled=None)
    assert await read_cached_team_digest(db, "proj", _digest_settings()) is None


@pytest.mark.asyncio
async def test_read_digest_global_disabled(monkeypatch):
    _patch_relay(monkeypatch, enabled=True)
    db = _FakeDigestDB(_cached("proj"))
    out = await read_cached_team_digest(db, "proj", _digest_settings(enabled=False))
    assert out is None


@pytest.mark.asyncio
async def test_read_digest_swallows_exceptions(monkeypatch):
    _patch_relay(monkeypatch, enabled=True)
    db = _FakeDigestDB(raise_on_get=True)
    out = await read_cached_team_digest(db, "proj", _digest_settings())
    assert out is None
