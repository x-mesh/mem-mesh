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


# ----- streaming (chat_stream parsers + run_events) -----------------------


async def _aiter(lines):
    for ln in lines:
        yield ln


@pytest.mark.asyncio
async def test_parse_anthropic_stream_text_and_tool_use():
    from app.core.services.relay_worker import AnthropicRelayEnricher

    lines = [
        'data: {"type":"message_start"}',
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hel"}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"lo"}}',
        'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"tu1","name":"search_memories"}}',
        'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"query\\":"}}',
        'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"\\"auth\\"}"}}',
        'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"}}',
        'data: {"type":"message_stop"}',
    ]
    deltas = []
    final = None
    async for ev in AnthropicRelayEnricher._parse_anthropic_stream(_aiter(lines)):
        if ev["type"] == "text_delta":
            deltas.append(ev["text"])
        elif ev["type"] == "final":
            final = ev["result"]
    assert "".join(deltas) == "Hello"
    assert final.text == "Hello"
    assert final.finish_reason == "tool_use"
    assert final.tool_calls == [
        {"id": "tu1", "name": "search_memories", "arguments": {"query": "auth"}}
    ]


@pytest.mark.asyncio
async def test_parse_openai_stream_text_and_tool_calls():
    from app.core.services.relay_worker import OpenAIRelayEnricher

    lines = [
        'data: {"choices":[{"delta":{"content":"Hi"}}]}',
        'data: {"choices":[{"delta":{"content":" there"}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"list_pins","arguments":"{\\"pro"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"ject_id\\":\\"p1\\"}"}}]},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ]
    deltas = []
    final = None
    async for ev in OpenAIRelayEnricher._parse_openai_stream(_aiter(lines)):
        if ev["type"] == "text_delta":
            deltas.append(ev["text"])
        elif ev["type"] == "final":
            final = ev["result"]
    assert "".join(deltas) == "Hi there"
    assert final.text == "Hi there"
    assert final.finish_reason == "tool_calls"
    assert final.tool_calls == [
        {"id": "c1", "name": "list_pins", "arguments": {"project_id": "p1"}}
    ]


class _StreamingEnricher:
    """Fake enricher exposing chat_stream with scripted turns."""

    def __init__(self, turns):
        # turns: list of (list_of_text_chunks, ChatResult)
        self.turns = list(turns)
        self.calls = []

    async def chat_stream(self, messages, *, tools=None, max_tokens=None):
        self.calls.append({"tools": tools})
        chunks, result = self.turns.pop(0)
        for c in chunks:
            yield {"type": "text_delta", "text": c}
        yield {"type": "final", "result": result}


@pytest.mark.asyncio
async def test_run_events_streams_deltas_then_tool_then_answer():
    enricher = _StreamingEnricher(
        [
            (
                [],
                ChatResult(
                    text="",
                    tool_calls=[{"id": "t1", "name": "memory_stats", "arguments": {}}],
                ),
            ),
            (["You ", "have ", "3."], ChatResult(text="You have 3.", tool_calls=[])),
        ]
    )

    class _StatsHandlers:
        async def stats(self, **kwargs):
            return {"total_memories": 3}

    loop = ChatAgentLoop(
        enricher=enricher, provider="anthropic", handlers=_StatsHandlers(), max_steps=5
    )
    events = [
        ev async for ev in loop.run_events([{"role": "user", "content": "count"}])
    ]
    types = [e["type"] for e in events]
    assert "tool_call" in types and "tool_result" in types
    deltas = "".join(e["text"] for e in events if e["type"] == "delta")
    assert deltas == "You have 3."
    msg = next(e for e in events if e["type"] == "message")
    assert msg["text"] == "You have 3."
    done = next(e for e in events if e["type"] == "done")
    assert done["truncated"] is False
