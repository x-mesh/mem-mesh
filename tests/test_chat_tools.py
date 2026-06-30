"""Chat tool registry tests (M1a)."""

import pytest

from app.core.services.chat_tools import (
    READ_ONLY_TOOLS,
    REGISTRY,
    SearchToolInput,
    execute_tool,
    render_tools,
)


class _FakeHandlers:
    """Duck-typed stand-in for MCPToolHandlers."""

    def __init__(self):
        self.calls = []

    async def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        return {"results": [{"id": "m1"}], "total": 1}

    async def context(self, **kwargs):
        self.calls.append(("context", kwargs))
        return {"primary_memory": {"id": kwargs.get("memory_id")}}

    async def stats(self, **kwargs):
        self.calls.append(("stats", kwargs))
        return {"total_memories": 3}

    async def pin_list(self, **kwargs):
        self.calls.append(("pin_list", kwargs))
        return {"pins": [], "count": 0}

    async def weekly_review(self, **kwargs):
        self.calls.append(("weekly_review", kwargs))
        return {"summary": {}}


def test_all_read_only_tools_are_safe():
    assert all(t.danger == "safe" for t in READ_ONLY_TOOLS)
    assert set(REGISTRY) == {
        "search_memories",
        "get_memory_context",
        "memory_stats",
        "list_pins",
        "weekly_review",
    }


def test_to_anthropic_shape():
    tool = REGISTRY["search_memories"]
    spec = tool.to_anthropic()
    assert spec["name"] == "search_memories"
    assert "description" in spec
    schema = spec["input_schema"]
    assert schema["type"] == "object"
    assert "query" in schema["properties"]
    assert "query" in schema["required"]
    assert "title" not in schema


def test_to_openai_shape():
    tool = REGISTRY["list_pins"]
    spec = tool.to_openai()
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "list_pins"
    params = spec["function"]["parameters"]
    assert params["type"] == "object"
    assert "project_id" in params["properties"]
    assert "project_id" in params["required"]


def test_render_tools_per_provider():
    anth = render_tools(READ_ONLY_TOOLS, "anthropic")
    assert len(anth) == len(READ_ONLY_TOOLS)
    assert "input_schema" in anth[0]

    oai = render_tools(READ_ONLY_TOOLS, "OpenAI")
    assert all(t["type"] == "function" for t in oai)


@pytest.mark.asyncio
async def test_execute_tool_dispatches_with_validated_args():
    handlers = _FakeHandlers()
    out = await execute_tool(
        handlers,
        "search_memories",
        {"query": "auth bug", "limit": 3, "recency_weight": 0.3},
    )
    assert out["ok"] is True
    assert out["data"]["total"] == 1
    name, kwargs = handlers.calls[0]
    assert name == "search"
    assert kwargs == {"query": "auth bug", "limit": 3, "recency_weight": 0.3}


@pytest.mark.asyncio
async def test_execute_tool_unknown_name():
    out = await execute_tool(_FakeHandlers(), "drop_table", {})
    assert out["ok"] is False
    assert "unknown tool" in out["error"]


@pytest.mark.asyncio
async def test_execute_tool_invalid_args():
    # missing required `query`
    out = await execute_tool(_FakeHandlers(), "search_memories", {"limit": 3})
    assert out["ok"] is False
    assert "invalid arguments" in out["error"]


@pytest.mark.asyncio
async def test_execute_tool_surfaces_handler_error():
    class _Boom:
        async def stats(self, **kwargs):
            raise RuntimeError("db down")

    out = await execute_tool(_Boom(), "memory_stats", {})
    assert out["ok"] is False
    assert "db down" in out["error"]


@pytest.mark.asyncio
async def test_execute_tool_excludes_none_optional_args():
    handlers = _FakeHandlers()
    await execute_tool(handlers, "list_pins", {"project_id": "p1"})
    _name, kwargs = handlers.calls[0]
    # status is None -> not forwarded; defaults stay server-side
    assert "status" not in kwargs
    assert kwargs["project_id"] == "p1"
    assert kwargs["limit"] == 10


def test_search_tool_input_validates_bounds():
    with pytest.raises(Exception):
        SearchToolInput(query="x", limit=999)
