"""Chat assistant adapter + service tests (M0)."""

import os
import tempfile
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.core.database.base import Database
from app.core.errors import ChatNotConfiguredError, ChatProviderError
from app.core.services.chat import ChatService
from app.core.services.relay_worker import (
    AnthropicRelayEnricher,
    OpenAIRelayEnricher,
    build_chat_enricher,
)


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
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return self.response


def _settings(**overrides):
    base = dict(
        chat_llm_provider="anthropic",
        chat_llm_api_key="",
        chat_llm_model="",
        chat_llm_base_url="",
        chat_llm_timeout=60.0,
        chat_llm_max_tokens=2048,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ----- adapter chat() -------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_chat_posts_system_at_top_level_and_parses_tool_use():
    http = _FakeHTTPClient(
        _FakeHTTPResponse(
            payload={
                "content": [
                    {"type": "text", "text": "hello there"},
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "search",
                        "input": {"query": "auth"},
                    },
                ],
                "stop_reason": "tool_use",
            }
        )
    )
    enricher = AnthropicRelayEnricher(api_key="k", http_client=http)

    result = await enricher.chat(
        [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hi"},
        ]
    )

    assert result.text == "hello there"
    assert result.finish_reason == "tool_use"
    assert result.tool_calls == [
        {"id": "tu_1", "name": "search", "arguments": {"query": "auth"}}
    ]
    call = http.calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"]["x-api-key"] == "k"
    # system goes top-level, not into messages
    assert call["json"]["system"] == "be terse"
    assert call["json"]["messages"] == [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_openai_chat_keeps_system_role_and_parses_function_tool_call():
    http = _FakeHTTPClient(
        _FakeHTTPResponse(
            payload={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "answer",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "search",
                                        "arguments": '{"query": "auth"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        )
    )
    enricher = OpenAIRelayEnricher(api_key="k", http_client=http)

    result = await enricher.chat(
        [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hi"},
        ]
    )

    assert result.text == "answer"
    assert result.finish_reason == "tool_calls"
    # OpenAI function arguments string is parsed into a dict
    assert result.tool_calls == [
        {"id": "call_1", "name": "search", "arguments": {"query": "auth"}}
    ]
    call = http.calls[0]
    assert call["url"] == "https://api.openai.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer k"
    # system stays as a message role
    assert call["json"]["messages"][0] == {"role": "system", "content": "be terse"}


@pytest.mark.asyncio
async def test_chat_rejects_empty_messages():
    enricher = AnthropicRelayEnricher(api_key="k", http_client=_FakeHTTPClient(None))
    with pytest.raises(ValueError, match="messages must not be empty"):
        await enricher.chat([])


def test_build_chat_enricher_uses_chat_defaults():
    a = build_chat_enricher(provider="anthropic", api_key="k")
    assert isinstance(a, AnthropicRelayEnricher)
    assert a.model == "claude-sonnet-4-6"
    assert a.max_tokens == 2048
    assert a.timeout == 60.0

    o = build_chat_enricher(provider="openai", api_key="k")
    assert isinstance(o, OpenAIRelayEnricher)
    assert o.model == "gpt-4o-mini"


# ----- ChatService ----------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_service_raises_when_not_configured():
    async with _temp_db() as db:
        service = ChatService(db)
        assert await service.is_configured(_settings()) is False
        with pytest.raises(ChatNotConfiguredError):
            await service.complete([{"role": "user", "content": "hi"}], _settings())


@pytest.mark.asyncio
async def test_chat_service_db_overrides_env():
    async with _temp_db() as db:
        await db.set_app_config("chat.llm_provider", "openai")
        await db.set_app_config("chat.llm_api_key", "db-key")
        await db.set_app_config("chat.llm_model", "gpt-4o")
        service = ChatService(db)

        effective = await service.get_effective_config(
            _settings(chat_llm_provider="anthropic", chat_llm_api_key="env-key")
        )
        assert effective["values"]["llm_provider"] == "openai"
        assert effective["values"]["llm_api_key"] == "db-key"
        assert effective["sources"]["llm_provider"] == "db"
        assert await service.is_configured(_settings()) is True


@pytest.mark.asyncio
async def test_chat_service_complete_returns_result_with_fake_http():
    async with _temp_db() as db:
        service = ChatService(db)
        http = _FakeHTTPClient(
            _FakeHTTPResponse(payload={"content": [{"type": "text", "text": "pong"}]})
        )
        result = await service.complete(
            [{"role": "user", "content": "hi"}],
            _settings(chat_llm_api_key="env-key"),
            http_client=http,
        )
        assert result.text == "pong"


@pytest.mark.asyncio
async def test_chat_service_test_connection_ok():
    async with _temp_db() as db:
        service = ChatService(db)
        http = _FakeHTTPClient(
            _FakeHTTPResponse(payload={"content": [{"type": "text", "text": "pong"}]})
        )
        out = await service.test_connection(
            _settings(chat_llm_api_key="env-key", chat_llm_provider="anthropic"),
            http_client=http,
        )
        assert out["ok"] is True
        assert out["provider"] == "anthropic"
        assert out["model"] == "claude-sonnet-4-6"
        assert out["sample"] == "pong"


@pytest.mark.asyncio
async def test_chat_service_test_connection_uses_overrides_before_save():
    async with _temp_db() as db:
        service = ChatService(db)  # nothing saved
        http = _FakeHTTPClient(
            _FakeHTTPResponse(payload={"choices": [{"message": {"content": "pong"}}]})
        )
        out = await service.test_connection(
            _settings(),  # no stored/env key
            overrides={
                "llm_provider": "openai",
                "llm_api_key": "form-key",
                "llm_model": "gpt-4o",
            },
            http_client=http,
        )
        assert out["ok"] is True
        assert out["provider"] == "openai"
        assert out["model"] == "gpt-4o"
        # the freshly typed key was used, not a stored one
        assert http.calls[0]["headers"]["Authorization"] == "Bearer form-key"


@pytest.mark.asyncio
async def test_chat_service_wraps_provider_http_error():
    async with _temp_db() as db:
        service = ChatService(db)
        http = _FakeHTTPClient(
            _FakeHTTPResponse(
                status_code=401,
                payload={"error": {"message": "invalid api key"}},
            )
        )
        with pytest.raises(ChatProviderError, match="invalid api key"):
            await service.complete(
                [{"role": "user", "content": "hi"}],
                _settings(chat_llm_api_key="bad-key"),
                http_client=http,
            )


@pytest.mark.asyncio
async def test_refine_memory_content_parses_json():
    async with _temp_db() as db:
        service = ChatService(db)
        http = _FakeHTTPClient(
            _FakeHTTPResponse(
                payload={
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "```json\n"
                                '{"content":"## WHY\\nbecause","category":"decision",'
                                '"tags":["auth","fix"],"summary":"s","rationale":"r"}'
                                "\n```"
                            ),
                        }
                    ]
                }
            )
        )
        out = await service.refine_memory_content(
            content="old text",
            category="task",
            tags=["t1"],
            settings=_settings(chat_llm_api_key="k"),
            http_client=http,
        )
        assert out["category"] == "decision"
        assert out["tags"] == ["auth", "fix"]
        assert "WHY" in out["content"]


@pytest.mark.asyncio
async def test_refine_memory_content_bad_json_raises():
    async with _temp_db() as db:
        service = ChatService(db)
        http = _FakeHTTPClient(
            _FakeHTTPResponse(
                payload={"content": [{"type": "text", "text": "not json at all"}]}
            )
        )
        with pytest.raises(ChatProviderError, match="parse"):
            await service.refine_memory_content(
                content="old",
                category="task",
                tags=[],
                settings=_settings(chat_llm_api_key="k"),
                http_client=http,
            )


@pytest.mark.asyncio
async def test_summarize_for_memory_parses_json():
    async with _temp_db() as db:
        service = ChatService(db)
        http = _FakeHTTPClient(
            _FakeHTTPResponse(
                payload={
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "```json\n"
                                '{"content":"## WHY\\nlasting decision","category":"decision",'
                                '"tags":["x"],"summary":"s"}\n```'
                            ),
                        }
                    ]
                }
            )
        )
        out = await service.summarize_for_memory(
            text="we decided X because Y",
            settings=_settings(chat_llm_api_key="k"),
            http_client=http,
        )
        assert out["category"] == "decision"
        assert out["tags"] == ["x"]
        assert "WHY" in out["content"]


@pytest.mark.asyncio
async def test_enrich_memory_content_via_relay_enrich():
    async with _temp_db() as db:
        service = ChatService(db)
        http = _FakeHTTPClient(
            _FakeHTTPResponse(
                payload={
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                '{"title":"T","abstract":"A","tags":["x","y"],'
                                '"display_kind":"note","confidence":0.8}'
                            ),
                        }
                    ]
                }
            )
        )
        out = await service.enrich_memory_content(
            content="some memory content",
            settings=_settings(chat_llm_api_key="k"),
            http_client=http,
        )
        assert out["title"] == "T"
        assert out["abstract"] == "A"
        assert out["tags"] == ["x", "y"]
