"""Chat agent loop + tool-message serialization tests (M1b)."""

import json

import pytest

from app.core.services.chat_agent import ChatAgentLoop
from app.core.services.relay_worker import (
    AnthropicRelayEnricher,
    ChatResult,
    OpenAIRelayEnricher,
)

# A conversation that exercises every message variant.
_CONVO = [
    {"role": "system", "content": "be terse"},
    {"role": "user", "content": "what bugs are open?"},
    {
        "role": "assistant",
        "content": "let me check",
        "tool_calls": [
            {"id": "t1", "name": "search_memories", "arguments": {"query": "bug"}}
        ],
    },
    {
        "role": "tool",
        "results": [{"tool_call_id": "t1", "content": '{"ok": true, "data": {}}'}],
    },
]


def test_anthropic_chat_payload_serializes_tool_turns():
    enricher = AnthropicRelayEnricher(api_key="k")
    body = enricher._chat_payload(_CONVO, tools=None, tool_choice=None, max_tokens=100)
    assert body["system"] == "be terse"
    msgs = body["messages"]
    assert msgs[0] == {"role": "user", "content": "what bugs are open?"}
    # assistant turn carries text + tool_use blocks
    assert msgs[1]["role"] == "assistant"
    blocks = msgs[1]["content"]
    assert blocks[0] == {"type": "text", "text": "let me check"}
    assert blocks[1] == {
        "type": "tool_use",
        "id": "t1",
        "name": "search_memories",
        "input": {"query": "bug"},
    }
    # tool results become a user turn with tool_result blocks
    assert msgs[2]["role"] == "user"
    assert msgs[2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "t1",
        "content": '{"ok": true, "data": {}}',
    }


def test_openai_chat_payload_serializes_tool_turns():
    enricher = OpenAIRelayEnricher(api_key="k")
    body = enricher._chat_payload(_CONVO, tools=None, tool_choice=None, max_tokens=100)
    msgs = body["messages"]
    assert msgs[0] == {"role": "system", "content": "be terse"}
    assert msgs[1] == {"role": "user", "content": "what bugs are open?"}
    # assistant tool-call message with function arguments serialized to a string
    assert msgs[2]["role"] == "assistant"
    tc = msgs[2]["tool_calls"][0]
    assert tc["id"] == "t1"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "search_memories"
    assert json.loads(tc["function"]["arguments"]) == {"query": "bug"}
    # tool result is its own `tool` message
    assert msgs[3] == {
        "role": "tool",
        "tool_call_id": "t1",
        "content": '{"ok": true, "data": {}}',
    }


class _ScriptedEnricher:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []

    async def chat(self, messages, *, tools=None, tool_choice=None, max_tokens=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        return self.scripted.pop(0)


class _FakeHandlers:
    def __init__(self):
        self.calls = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return {"results": [{"id": "m1"}], "total": 1}


@pytest.mark.asyncio
async def test_agent_loop_runs_tool_then_answers():
    enricher = _ScriptedEnricher(
        [
            ChatResult(
                text="",
                tool_calls=[
                    {"id": "t1", "name": "search_memories", "arguments": {"query": "x"}}
                ],
            ),
            ChatResult(text="found 1 memory", tool_calls=[]),
        ]
    )
    handlers = _FakeHandlers()
    loop = ChatAgentLoop(
        enricher=enricher, provider="anthropic", handlers=handlers, max_steps=5
    )

    out = await loop.run([{"role": "user", "content": "search x"}])

    assert out["text"] == "found 1 memory"
    assert out["truncated"] is False
    assert out["steps"] == 2
    assert len(out["tool_calls"]) == 1
    assert out["tool_calls"][0]["name"] == "search_memories"
    assert out["tool_calls"][0]["result"]["ok"] is True
    # the handler actually ran with validated args (defaults included)
    assert handlers.calls[0] == {"query": "x", "limit": 5, "recency_weight": 0.0}
    # first model call carried tools, the loop fed results back on the 2nd
    assert enricher.calls[0]["tools"] is not None


class _AlwaysToolEnricher:
    def __init__(self):
        self.calls = []

    async def chat(self, messages, *, tools=None, tool_choice=None, max_tokens=None):
        self.calls.append({"tools": tools})
        if tools is None:
            return ChatResult(text="forced final answer", tool_calls=[])
        return ChatResult(
            text="", tool_calls=[{"id": "t", "name": "memory_stats", "arguments": {}}]
        )


@pytest.mark.asyncio
async def test_agent_loop_truncates_and_forces_final_answer():
    class _StatsHandlers:
        async def stats(self, **kwargs):
            return {"total_memories": 0}

    enricher = _AlwaysToolEnricher()
    loop = ChatAgentLoop(
        enricher=enricher, provider="openai", handlers=_StatsHandlers(), max_steps=3
    )

    out = await loop.run([{"role": "user", "content": "loop forever"}])

    assert out["truncated"] is True
    assert out["steps"] == 3
    assert out["text"] == "forced final answer"
    # 3 tool-enabled calls + 1 forced no-tools final call
    assert len(enricher.calls) == 4
    assert enricher.calls[-1]["tools"] is None


@pytest.mark.asyncio
async def test_agent_loop_rejects_unknown_tool_but_continues():
    enricher = _ScriptedEnricher(
        [
            ChatResult(
                text="",
                tool_calls=[{"id": "t1", "name": "delete_everything", "arguments": {}}],
            ),
            ChatResult(text="cannot do that", tool_calls=[]),
        ]
    )
    loop = ChatAgentLoop(
        enricher=enricher, provider="anthropic", handlers=_FakeHandlers()
    )

    out = await loop.run([{"role": "user", "content": "drop it"}])

    assert out["text"] == "cannot do that"
    assert out["tool_calls"][0]["result"]["ok"] is False
    assert "unknown tool" in out["tool_calls"][0]["result"]["error"]
