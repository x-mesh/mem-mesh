"""RelayHTTPClient — the wire layer every other relay test fakes out.

The e2e suites inject a transport that raises RelayDeliveryConflict directly,
so they prove "this exception dead-letters the job" while assuming the piece
that turns an HTTP 409 into that exception. That assumption is what fails
silently: if a 409 ever mapped to RuntimeError instead, delivery would retry
forever rather than dead-letter, and every existing test would still pass.

These drive the real client against stubbed responses — no network, no server.
"""

import pytest

from app.core.errors import RelayDeliveryConflict, RelayUnauthorized
from app.core.schemas.relay import (
    RelayIngestRequest,
    RelayPairRequest,
    RelaySearchRequest,
)
from app.core.services.relay import RelayHTTPClient

HUB = "http://hub.invalid"
TOKEN = "token-abc"


class _Response:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class _StubHTTP:
    """Records the request and returns a canned response."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self._response

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self._response


def _ingest_payload():
    return RelayIngestRequest(
        idempotency_key="node:mem:1",
        payload_hash="sha256:abc",
        event_type="create",
        source_memory_id="mem",
        source_version=1,
        source_project_key="proj",
        kind="decision",
        content="body",
    )


# --- status mapping: the assumption the e2e suites rest on -----------------


@pytest.mark.asyncio
async def test_ingest_maps_409_to_delivery_conflict():
    """The one that matters: 409 must dead-letter, not retry forever."""
    http = _StubHTTP(_Response(409, {"detail": "version collision"}))
    client = RelayHTTPClient(http_client=http)

    with pytest.raises(RelayDeliveryConflict) as exc:
        await client.send_ingest(
            target_hub=HUB, bearer_token=TOKEN, payload=_ingest_payload()
        )
    assert "version collision" in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_ingest_maps_auth_failures(status):
    http = _StubHTTP(_Response(status, {"detail": "nope"}))
    client = RelayHTTPClient(http_client=http)

    with pytest.raises(RelayUnauthorized):
        await client.send_ingest(
            target_hub=HUB, bearer_token=TOKEN, payload=_ingest_payload()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 404, 422, 500, 503])
async def test_ingest_maps_other_errors_to_runtime_error(status):
    """Anything else stays retryable — the outbox backs off rather than gives up."""
    http = _StubHTTP(_Response(status, {"detail": "boom"}))
    client = RelayHTTPClient(http_client=http)

    with pytest.raises(RuntimeError) as exc:
        await client.send_ingest(
            target_hub=HUB, bearer_token=TOKEN, payload=_ingest_payload()
        )
    assert not isinstance(exc.value, (RelayDeliveryConflict, RelayUnauthorized))


@pytest.mark.asyncio
async def test_ingest_returns_parsed_response_on_success():
    http = _StubHTTP(
        _Response(200, {"accepted": True, "event_id": "e1", "current_memory_id": "m1"})
    )
    client = RelayHTTPClient(http_client=http)

    result = await client.send_ingest(
        target_hub=HUB, bearer_token=TOKEN, payload=_ingest_payload()
    )
    assert result.accepted is True
    assert result.event_id == "e1"


@pytest.mark.asyncio
async def test_search_does_not_treat_409_as_a_conflict():
    """Only ingest has conflict semantics; a search 409 is just a failure."""
    http = _StubHTTP(_Response(409, {"detail": "weird"}))
    client = RelayHTTPClient(http_client=http)

    with pytest.raises(RuntimeError) as exc:
        await client.send_search(
            target_hub=HUB, bearer_token=TOKEN, payload=RelaySearchRequest(query="q")
        )
    assert not isinstance(exc.value, RelayDeliveryConflict)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_search_maps_auth_failures(status):
    http = _StubHTTP(_Response(status, {"detail": "nope"}))
    client = RelayHTTPClient(http_client=http)

    with pytest.raises(RelayUnauthorized):
        await client.send_search(
            target_hub=HUB, bearer_token=TOKEN, payload=RelaySearchRequest(query="q")
        )


@pytest.mark.asyncio
async def test_digest_404_from_an_older_hub_is_a_plain_error():
    """Documented contract: a hub without the route degrades, not authorizes."""
    http = _StubHTTP(_Response(404, {"detail": "Not Found"}))
    client = RelayHTTPClient(http_client=http)

    with pytest.raises(RuntimeError):
        await client.fetch_project_digest(
            target_hub=HUB, bearer_token=TOKEN, team_project_id="node:proj"
        )


# --- error detail extraction ----------------------------------------------


@pytest.mark.asyncio
async def test_detail_falls_back_when_the_body_is_not_json():
    """A proxy's HTML error page must not crash the mapper."""
    http = _StubHTTP(_Response(502, payload=None, text="<html>bad gateway</html>"))
    client = RelayHTTPClient(http_client=http)

    with pytest.raises(RuntimeError) as exc:
        await client.send_ingest(
            target_hub=HUB, bearer_token=TOKEN, payload=_ingest_payload()
        )
    assert "bad gateway" in str(exc.value)


@pytest.mark.asyncio
async def test_detail_falls_back_to_status_when_body_is_empty():
    http = _StubHTTP(_Response(500, payload=None, text=""))
    client = RelayHTTPClient(http_client=http)

    with pytest.raises(RuntimeError) as exc:
        await client.send_ingest(
            target_hub=HUB, bearer_token=TOKEN, payload=_ingest_payload()
        )
    assert "500" in str(exc.value)


# --- request shape --------------------------------------------------------


@pytest.mark.asyncio
async def test_bearer_token_is_sent():
    http = _StubHTTP(
        _Response(200, {"accepted": True, "event_id": "e1", "current_memory_id": "m1"})
    )
    client = RelayHTTPClient(http_client=http)

    await client.send_ingest(
        target_hub=HUB, bearer_token=TOKEN, payload=_ingest_payload()
    )
    _, _, kwargs = http.calls[0]
    assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.asyncio
async def test_pair_carries_no_bearer_token():
    """The invite code IS the credential — a pairing node has no token yet."""
    http = _StubHTTP(
        _Response(
            200,
            {
                "token": "t",
                "user_id": "u",
                "source_node_id": "n",
                "display_name": "node",
            },
        )
    )
    client = RelayHTTPClient(http_client=http)

    await client.send_pair(
        target_hub=HUB, payload=RelayPairRequest(code="invite-code-0123456789")
    )
    _, _, kwargs = http.calls[0]
    assert "Authorization" not in (kwargs.get("headers") or {})


@pytest.mark.asyncio
async def test_search_timeout_argument_overrides_the_client_default():
    http = _StubHTTP(_Response(200, {"results": [], "total": 0}))
    client = RelayHTTPClient(http_client=http, timeout=10.0)

    await client.send_search(
        target_hub=HUB,
        bearer_token=TOKEN,
        payload=RelaySearchRequest(query="q"),
        timeout=2.5,
    )
    _, _, kwargs = http.calls[0]
    assert kwargs["timeout"] == 2.5


# --- URL building ---------------------------------------------------------


@pytest.mark.parametrize(
    "configured",
    [
        "http://hub.invalid",
        "http://hub.invalid/",
        "http://hub.invalid/api/relay/v1",
        "http://hub.invalid/api/relay/v1/",
        "http://hub.invalid/api/relay/v1/ingest",
        "http://hub.invalid/api/relay/v1/health",
        "http://hub.invalid/api/relay/v1/search",
    ],
)
def test_ingest_url_is_stable_however_the_hub_is_configured(configured):
    """Operators paste whatever URL they copied; all of them must land."""
    assert (
        RelayHTTPClient._ingest_url(configured)
        == "http://hub.invalid/api/relay/v1/ingest"
    )


@pytest.mark.parametrize(
    "configured",
    [
        "http://hub.invalid",
        "http://hub.invalid/api/relay/v1",
        "http://hub.invalid/api/relay/v1/health",
        "http://hub.invalid/api/relay/v1/ingest",
        "http://hub.invalid/api/relay/v1/search",
    ],
)
def test_search_url_is_stable_however_the_hub_is_configured(configured):
    assert (
        RelayHTTPClient._search_url(configured)
        == "http://hub.invalid/api/relay/v1/search"
    )


@pytest.mark.parametrize(
    "configured",
    [
        "http://hub.invalid",
        "http://hub.invalid/api/relay/v1",
        "http://hub.invalid/api/relay/v1/health",
    ],
)
def test_health_url_is_stable_however_the_hub_is_configured(configured):
    assert (
        RelayHTTPClient.health_url(configured)
        == "http://hub.invalid/api/relay/v1/health"
    )


def test_digest_url_embeds_the_team_project():
    assert RelayHTTPClient._digest_url(
        "http://hub.invalid/api/relay/v1", "node-a:proj"
    ) == ("http://hub.invalid/api/relay/v1/projects/node-a:proj/digest")
