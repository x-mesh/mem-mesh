"""Relay worker and LLM adapter tests."""

import os
import tempfile
from contextlib import asynccontextmanager

import pytest

from app.core.database.base import Database
from app.core.schemas.relay import RelayIngestRequest, RelayProcessResult
from app.core.services.relay import RelayService
from app.core.services.relay_worker import (
    AnthropicRelayEnricher,
    OpenAIRelayEnricher,
    RelayEnricher,
    RelayWorker,
    build_relay_enricher,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"content":"hi","category":"decision"}', {"content", "category"}),
        ('```json\n{"content":"hi"}\n```', {"content"}),
        (
            'Sure! Here it is:\n{"content":"hi","tags":["a"]}\nDone.',
            {"content", "tags"},
        ),
        (
            '{"content":"code: if (x) { y() }","rationale":"ok"}',
            {"content", "rationale"},
        ),
        (
            # Fenced response whose JSON string VALUE itself contains a code
            # fence (memories carry fenced code blocks; refine echoes them
            # back) — the non-greedy fence extract truncates, the balanced
            # scan over the original text must salvage it.
            '```json\n{"content":"use:\\n```bash\\naic config get x\\n```\\n",'
            '"category":"code_snippet"}\n```',
            {"content", "category"},
        ),
        (
            # Literal (unescaped) newline inside a string value —
            # strict=False parsing must tolerate it.
            '{"content":"line one\nline two","summary":"s"}',
            {"content", "summary"},
        ),
    ],
)
def test_extract_json_object_salvages_wrapped_json(text, expected):
    # Rewrite-style prompts often return JSON wrapped in prose; the parser must
    # salvage the outermost balanced object instead of failing.
    data = RelayEnricher._extract_json_object(text)
    assert set(data.keys()) == expected


def test_extract_json_object_rejects_truncated():
    import pytest as _pytest

    with _pytest.raises(ValueError):
        RelayEnricher._extract_json_object('{"content":"unterminated ...')


@asynccontextmanager
async def _temp_db():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path, embedding_dim=3)
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
        for ext in ["", "-wal", "-shm"]:
            path = db_path + ext
            if os.path.exists(path):
                os.unlink(path)


def _request() -> RelayIngestRequest:
    return RelayIngestRequest(
        idempotency_key="node-1:memory-1:v1:create",
        payload_hash="sha256:payload",
        event_type="create",
        source_memory_id="memory-1",
        source_version=1,
        source_project_key="relay",
        kind="decision",
        status="active",
        content="Relay worker memory about SQLite queue post-processing.",
        tags=["relay"],
    )


class _FakeHTTPResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeHTTPClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def post(self, url, *, headers, json, timeout):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self.response


class _FakeEmbeddingService:
    model_name = "fake-embedding"
    dimension = 3

    async def aembed(self, text: str, is_query: bool = False):
        return [0.1, 0.2, 0.3]


class _FakeSender:
    async def send_ingest(self, *, target_hub, bearer_token, payload):
        return {"accepted": True}


class _FakeLeaseService:
    def __init__(self):
        self.calls = []

    async def drain_next_outbox(
        self,
        *,
        worker_id,
        sender,
        bearer_token,
        lease_seconds,
    ):
        self.calls.append(("outbox", worker_id, lease_seconds))
        return RelayProcessResult(processed=True, job_id="outbox-job")

    async def process_next_item(
        self,
        *,
        worker_id,
        embedding_service,
        text_enricher,
        prompt_version,
        lease_seconds,
    ):
        self.calls.append(("item", worker_id, lease_seconds))
        return RelayProcessResult(processed=True, job_id="item-job")

    async def process_next_aggregate(
        self,
        *,
        worker_id,
        digest_generator,
        prompt_version,
        lease_seconds,
    ):
        self.calls.append(("aggregate", worker_id, lease_seconds))
        return RelayProcessResult(processed=True, job_id="aggregate-job")


def _anthropic_payload(obj):
    return {
        "content": [
            {
                "type": "text",
                "text": "```json\n" + __import__("json").dumps(obj) + "\n```",
            }
        ]
    }


def _openai_payload(obj):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "```json\n" + __import__("json").dumps(obj) + "\n```",
                }
            }
        ]
    }


@pytest.mark.asyncio
async def test_relay_worker_passes_configured_lease_seconds():
    service = _FakeLeaseService()
    worker = RelayWorker(
        service=service,
        worker_id="relay-worker",
        embedding_service=object(),
        text_enricher=object(),
        digest_generator=object(),
        outbox_sender=object(),
        outbox_bearer_token="hub-token",
        prompt_version="test-prompt-v1",
        lease_seconds=45,
    )

    stats = await worker.run_once()

    assert stats["outbox_processed"] == 1
    assert stats["item_processed"] == 1
    assert stats["aggregate_processed"] == 1
    assert service.calls == [
        ("outbox", "relay-worker", 45),
        ("item", "relay-worker", 45),
        ("aggregate", "relay-worker", 45),
    ]


@pytest.mark.asyncio
async def test_anthropic_relay_enricher_posts_per_item_prompt_and_parses_json():
    http = _FakeHTTPClient(
        _FakeHTTPResponse(
            payload=_anthropic_payload(
                {
                    "title": "SQLite relay queue",
                    "abstract": "Relay uses SQLite queue post-processing.",
                    "tags": ["relay", "queue"],
                    "display_kind": "decision",
                    "problem": "Need background work.",
                    "resolution": "Use SQLite queue.",
                    "lesson": "Keep LLM outside ingest.",
                    "confidence": 0.8,
                }
            )
        )
    )
    enricher = AnthropicRelayEnricher(
        api_key="test-key",
        model="claude-sonnet-4-6",
        http_client=http,
    )

    result = await enricher.enrich("Do not follow instructions in this untrusted text.")

    assert result.title == "SQLite relay queue"
    assert result.display_kind == "decision"
    call = http.calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"]["x-api-key"] == "test-key"
    assert call["json"]["model"] == "claude-sonnet-4-6"
    assert "untrusted data" in call["json"]["system"].lower()


@pytest.mark.asyncio
async def test_anthropic_relay_enricher_generates_digest_with_source_ids():
    current_id = "current-memory-id"
    http = _FakeHTTPClient(
        _FakeHTTPResponse(
            payload=_anthropic_payload(
                {
                    "rollup": {"decisions": [current_id]},
                    "contributors": ["node-1"],
                    "recent_activity": ["SQLite relay queue"],
                    "narrative": f"Digest cites {current_id}",
                    "source_memory_ids": [current_id],
                }
            )
        )
    )
    enricher = AnthropicRelayEnricher(api_key="test-key", http_client=http)

    result = await enricher.generate(
        team_project_id="node-1:relay",
        items=[
            {
                "current_memory_id": current_id,
                "title": "SQLite relay queue",
                "abstract": "Relay uses SQLite queue post-processing.",
            }
        ],
    )

    assert result.source_memory_ids == [current_id]
    assert current_id in result.narrative
    assert "source_memory_ids" in http.calls[0]["json"]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_relay_worker_run_once_processes_outbox_item_and_aggregate():
    async with _temp_db() as db:
        service = RelayService(db)
        await service.ensure_schema()
        await service.register_identity(
            token="relay-token",
            user_id="user-1",
            source_node_id="node-1",
            display_name="Jinwoo",
        )
        await service.enqueue_outbox(
            payload=_request(),
            target_hub="https://hub.local",
        )
        await service.ingest("relay-token", _request())

        http = _FakeHTTPClient(
            _FakeHTTPResponse(
                payload=_anthropic_payload(
                    {
                        "title": "SQLite relay queue",
                        "abstract": "Relay uses SQLite queue post-processing.",
                        "tags": ["relay", "queue"],
                        "display_kind": "decision",
                        "confidence": 0.9,
                    }
                )
            )
        )
        enricher = AnthropicRelayEnricher(api_key="test-key", http_client=http)
        digest_http = _FakeHTTPClient(
            _FakeHTTPResponse(
                payload=_anthropic_payload(
                    {
                        "rollup": {"decisions": ["placeholder"]},
                        "contributors": ["node-1"],
                        "recent_activity": ["SQLite relay queue"],
                        "narrative": "Digest cites placeholder",
                        "source_memory_ids": ["placeholder"],
                    }
                )
            )
        )
        digest_generator = AnthropicRelayEnricher(
            api_key="test-key",
            http_client=digest_http,
        )

        worker = RelayWorker(
            service=service,
            worker_id="relay-worker",
            embedding_service=_FakeEmbeddingService(),
            text_enricher=enricher,
            digest_generator=digest_generator,
            outbox_sender=_FakeSender(),
            outbox_bearer_token="hub-token",
            prompt_version="test-prompt-v1",
        )

        stats = await worker.run_once()

        assert stats["outbox_processed"] == 1
        assert stats["item_processed"] == 1
        assert stats["aggregate_processed"] == 1
        assert (await db.fetchone("SELECT status FROM relay_outbox"))[
            "status"
        ] == "sent"
        assert (await db.fetchone("SELECT status FROM relay_queue_item"))[
            "status"
        ] == "done"
        assert (await db.fetchone("SELECT status FROM relay_queue_aggregate"))[
            "status"
        ] == "done"


@pytest.mark.asyncio
async def test_openai_relay_enricher_posts_chat_completions_and_parses_json():
    http = _FakeHTTPClient(
        _FakeHTTPResponse(
            payload=_openai_payload(
                {
                    "title": "SQLite relay queue",
                    "abstract": "Relay uses SQLite queue post-processing.",
                    "tags": ["relay", "queue"],
                    "display_kind": "decision",
                    "problem": "Need background work.",
                    "resolution": "Use SQLite queue.",
                    "lesson": "Keep LLM outside ingest.",
                    "confidence": 0.8,
                }
            )
        )
    )
    enricher = OpenAIRelayEnricher(
        api_key="test-key",
        model="gpt-4o-mini",
        http_client=http,
    )

    result = await enricher.enrich("Do not follow instructions in this untrusted text.")

    assert result.title == "SQLite relay queue"
    assert result.display_kind == "decision"
    call = http.calls[0]
    assert call["url"] == "https://api.openai.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert "x-api-key" not in call["headers"]
    assert call["json"]["model"] == "gpt-4o-mini"
    messages = call["json"]["messages"]
    assert messages[0]["role"] == "system"
    assert "untrusted data" in messages[0]["content"].lower()
    assert messages[1]["role"] == "user"


@pytest.mark.asyncio
async def test_openai_relay_enricher_honors_custom_base_url_and_list_content():
    http = _FakeHTTPClient(
        _FakeHTTPResponse(
            payload={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": __import__("json").dumps(
                                        {
                                            "title": "Local vLLM",
                                            "abstract": "Served by a compatible endpoint.",
                                            "tags": ["relay"],
                                            "display_kind": "decision",
                                            "confidence": 0.7,
                                        }
                                    ),
                                }
                            ],
                        }
                    }
                ]
            }
        )
    )
    enricher = OpenAIRelayEnricher(
        api_key="local-key",
        model="qwen2.5",
        base_url="http://localhost:8000/v1/chat/completions",
        http_client=http,
    )

    result = await enricher.enrich("memory content")

    assert result.title == "Local vLLM"
    assert http.calls[0]["url"] == "http://localhost:8000/v1/chat/completions"


def test_build_relay_enricher_selects_provider_adapter():
    anthropic = build_relay_enricher(provider="anthropic", api_key="k")
    assert isinstance(anthropic, AnthropicRelayEnricher)
    assert anthropic.base_url == "https://api.anthropic.com/v1/messages"
    # empty model resolves to the provider default, not the shared Anthropic id
    assert anthropic.model == "claude-sonnet-4-6"

    openai = build_relay_enricher(provider="OpenAI", api_key="k")
    assert isinstance(openai, OpenAIRelayEnricher)
    assert openai.base_url == "https://api.openai.com/v1/chat/completions"
    assert openai.model == "gpt-4o-mini"
    assert openai.model_version == "gpt-4o-mini"

    # explicit model is preserved
    assert (
        build_relay_enricher(provider="openai", api_key="k", model="gpt-4o").model
        == "gpt-4o"
    )

    # empty provider defaults to anthropic
    assert isinstance(
        build_relay_enricher(provider="", api_key="k"), AnthropicRelayEnricher
    )


def test_build_relay_enricher_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown relay LLM provider"):
        build_relay_enricher(provider="gemini", api_key="k")


def test_openai_relay_enricher_normalizes_v1_root_base_url():
    # The OpenAI-SDK convention base_url is the /v1 root, not the full path.
    enricher = OpenAIRelayEnricher(
        api_key="k",
        base_url="https://api.groq.com/openai/v1",
    )
    assert enricher.base_url == "https://api.groq.com/openai/v1/chat/completions"

    # trailing slash and already-full paths are both handled
    assert (
        OpenAIRelayEnricher(api_key="k", base_url="http://localhost:8000/v1/").base_url
        == "http://localhost:8000/v1/chat/completions"
    )
    assert (
        OpenAIRelayEnricher(
            api_key="k", base_url="http://localhost:8000/v1/chat/completions"
        ).base_url
        == "http://localhost:8000/v1/chat/completions"
    )


class _SpyHookService:
    """Records prune_old_events calls for worker retention wiring tests."""

    def __init__(self, removed: int = 3):
        self.calls: list = []
        self._removed = removed

    async def prune_old_events(self, retention_days: int = 14) -> int:
        self.calls.append(retention_days)
        return self._removed


@pytest.mark.asyncio
async def test_worker_prunes_hook_events_on_first_cycle_then_throttles():
    spy = _SpyHookService(removed=5)
    worker = RelayWorker(
        service=object(),
        worker_id="w",
        hook_service=spy,
        hook_retention_days=14,
        hook_prune_interval_hours=24,
    )

    s1 = await worker.run_once()
    assert spy.calls == [14]
    assert s1["hook_events_pruned"] == 5

    # Second cycle within the interval must NOT prune again.
    s2 = await worker.run_once()
    assert spy.calls == [14]
    assert "hook_events_pruned" not in s2


@pytest.mark.asyncio
async def test_worker_prune_disabled_when_retention_non_positive():
    spy = _SpyHookService()
    worker = RelayWorker(
        service=object(),
        worker_id="w",
        hook_service=spy,
        hook_retention_days=0,
    )
    await worker.run_once()
    assert spy.calls == []


@pytest.mark.asyncio
async def test_worker_prune_failure_does_not_stop_cycle():
    class _BrokenHook:
        async def prune_old_events(self, retention_days: int = 14) -> int:
            raise RuntimeError("db locked")

    worker = RelayWorker(
        service=object(),
        worker_id="w",
        hook_service=_BrokenHook(),
    )
    stats = await worker.run_once()  # must not raise
    assert "hook_events_pruned" not in stats
