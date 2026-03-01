"""
MCP Dispatcher Tests - TDD for unified tool dispatch abstraction.

Tests the MCPDispatcher class that eliminates duplicated dispatch logic
between Pure MCP and SSE MCP implementations.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mcp_common.tools import MCPToolHandlers

# ============== Fixtures ==============


@pytest.fixture
def mock_tool_handlers():
    """Mock tool handlers for isolated testing"""
    handlers = MagicMock(spec=MCPToolHandlers)
    handlers.add = AsyncMock(
        return_value={"id": "test-id", "status": "saved", "created_at": "2024-01-01"}
    )
    handlers.search = AsyncMock(return_value={"results": [], "total": 0})
    handlers.context = AsyncMock(return_value={"memory": {}, "related_memories": []})
    handlers.update = AsyncMock(return_value={"id": "test-id", "status": "updated"})
    handlers.delete = AsyncMock(return_value={"id": "test-id", "status": "deleted"})
    handlers.stats = AsyncMock(
        return_value={
            "total_memories": 0,
            "unique_projects": 0,
            "categories_breakdown": {},
            "sources_breakdown": {},
            "query_time_ms": 1.0,
        }
    )
    handlers.pin_add = AsyncMock(
        return_value={
            "id": "pin-id",
            "content": "test",
            "project_id": "test",
            "status": "active",
        }
    )
    handlers.pin_complete = AsyncMock(
        return_value={"id": "pin-id", "status": "completed", "suggest_promotion": False}
    )
    handlers.pin_promote = AsyncMock(
        return_value={"id": "pin-id", "memory_id": "mem-id", "status": "promoted"}
    )
    handlers.session_resume = AsyncMock(
        return_value={"session_id": "sess-id", "pins_count": 0}
    )
    handlers.session_end = AsyncMock(
        return_value={"status": "ended", "summary": "test"}
    )
    return handlers


@pytest.fixture
def dispatcher(mock_tool_handlers):
    """Create dispatcher with mock handlers"""
    from app.mcp_common.dispatcher import MCPDispatcher

    return MCPDispatcher(mock_tool_handlers)


# ============== Dispatcher Initialization Tests ==============


def test_dispatcher_initialization(mock_tool_handlers):
    """Test dispatcher initializes with tool handlers"""
    from app.mcp_common.dispatcher import MCPDispatcher

    dispatcher = MCPDispatcher(mock_tool_handlers)

    assert dispatcher.tool_handlers is mock_tool_handlers


def test_dispatcher_requires_tool_handlers():
    """Test dispatcher requires tool handlers"""
    from app.mcp_common.dispatcher import MCPDispatcher

    with pytest.raises(TypeError):
        MCPDispatcher()  # Missing required argument


# ============== Tool Dispatch Tests - Memory Tools ==============


@pytest.mark.asyncio
async def test_dispatch_add_tool(dispatcher, mock_tool_handlers):
    """Test dispatching add tool"""
    result = await dispatcher.dispatch(
        "add",
        {
            "content": "Test memory content for dispatch testing",
            "project_id": "test-project",
            "category": "task",
        },
    )

    assert result["isError"] is False
    assert "content" in result
    mock_tool_handlers.add.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_add_missing_content(dispatcher):
    """Test add tool with missing required content"""
    result = await dispatcher.dispatch("add", {"project_id": "test"})

    assert result["isError"] is True
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["success"] is False
    assert "content" in response_data["error"].lower()


@pytest.mark.asyncio
async def test_dispatch_search_tool(dispatcher, mock_tool_handlers):
    """Test dispatching search tool"""
    result = await dispatcher.dispatch("search", {"query": "test query", "limit": 5})

    assert result["isError"] is False
    mock_tool_handlers.search.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_search_missing_query(dispatcher):
    """Test search tool with missing required query"""
    result = await dispatcher.dispatch("search", {"limit": 5})

    assert result["isError"] is True
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["success"] is False
    assert "query" in response_data["error"].lower()


@pytest.mark.asyncio
async def test_dispatch_context_tool(dispatcher, mock_tool_handlers):
    """Test dispatching context tool"""
    result = await dispatcher.dispatch("context", {"memory_id": "test-id", "depth": 2})

    assert result["isError"] is False
    mock_tool_handlers.context.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_context_missing_memory_id(dispatcher):
    """Test context tool with missing required memory_id"""
    result = await dispatcher.dispatch("context", {"depth": 2})

    assert result["isError"] is True
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["success"] is False
    assert "memory_id" in response_data["error"].lower()


@pytest.mark.asyncio
async def test_dispatch_update_tool(dispatcher, mock_tool_handlers):
    """Test dispatching update tool"""
    result = await dispatcher.dispatch(
        "update", {"memory_id": "test-id", "content": "Updated content"}
    )

    assert result["isError"] is False
    mock_tool_handlers.update.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_update_missing_memory_id(dispatcher):
    """Test update tool with missing required memory_id"""
    result = await dispatcher.dispatch("update", {"content": "new content"})

    assert result["isError"] is True
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["success"] is False
    assert "memory_id" in response_data["error"].lower()


@pytest.mark.asyncio
async def test_dispatch_delete_tool(dispatcher, mock_tool_handlers):
    """Test dispatching delete tool"""
    result = await dispatcher.dispatch("delete", {"memory_id": "test-id"})

    assert result["isError"] is False
    mock_tool_handlers.delete.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_delete_missing_memory_id(dispatcher):
    """Test delete tool with missing required memory_id"""
    result = await dispatcher.dispatch("delete", {})

    assert result["isError"] is True
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["success"] is False
    assert "memory_id" in response_data["error"].lower()


@pytest.mark.asyncio
async def test_dispatch_stats_tool(dispatcher, mock_tool_handlers):
    """Test dispatching stats tool"""
    result = await dispatcher.dispatch("stats", {"project_id": "test"})

    assert result["isError"] is False
    mock_tool_handlers.stats.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_stats_no_args(dispatcher, mock_tool_handlers):
    """Test stats tool with no arguments (all optional)"""
    result = await dispatcher.dispatch("stats", {})

    assert result["isError"] is False
    mock_tool_handlers.stats.assert_called_once()


# ============== Tool Dispatch Tests - Pin/Session Tools ==============


@pytest.mark.asyncio
async def test_dispatch_pin_add_tool(dispatcher, mock_tool_handlers):
    """Test dispatching pin_add tool"""
    result = await dispatcher.dispatch(
        "pin_add",
        {"content": "Test pin", "project_id": "test-project", "importance": 3},
    )

    assert result["isError"] is False
    mock_tool_handlers.pin_add.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_pin_add_missing_content(dispatcher):
    """Test pin_add with missing content"""
    result = await dispatcher.dispatch("pin_add", {"project_id": "test"})

    assert result["isError"] is True
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["success"] is False


@pytest.mark.asyncio
async def test_dispatch_pin_add_missing_project_id(dispatcher):
    """Test pin_add with missing project_id"""
    result = await dispatcher.dispatch("pin_add", {"content": "test"})

    assert result["isError"] is True
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["success"] is False


@pytest.mark.asyncio
async def test_dispatch_pin_complete_tool(dispatcher, mock_tool_handlers):
    """Test dispatching pin_complete tool"""
    result = await dispatcher.dispatch("pin_complete", {"pin_id": "test-pin"})

    assert result["isError"] is False
    mock_tool_handlers.pin_complete.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_pin_complete_missing_pin_id(dispatcher):
    """Test pin_complete with missing pin_id"""
    result = await dispatcher.dispatch("pin_complete", {})

    assert result["isError"] is True
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["success"] is False
    assert "pin_id" in response_data["error"].lower()


@pytest.mark.asyncio
async def test_dispatch_pin_promote_tool(dispatcher, mock_tool_handlers):
    """Test dispatching pin_promote tool"""
    result = await dispatcher.dispatch("pin_promote", {"pin_id": "test-pin"})

    assert result["isError"] is False
    mock_tool_handlers.pin_promote.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_pin_promote_missing_pin_id(dispatcher):
    """Test pin_promote with missing pin_id"""
    result = await dispatcher.dispatch("pin_promote", {})

    assert result["isError"] is True
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["success"] is False
    assert "pin_id" in response_data["error"].lower()


@pytest.mark.asyncio
async def test_dispatch_session_resume_tool(dispatcher, mock_tool_handlers):
    """Test dispatching session_resume tool"""
    result = await dispatcher.dispatch(
        "session_resume", {"project_id": "test-project", "expand": False, "limit": 10}
    )

    assert result["isError"] is False
    mock_tool_handlers.session_resume.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_session_resume_missing_project_id(dispatcher):
    """Test session_resume with missing project_id"""
    result = await dispatcher.dispatch("session_resume", {"expand": True})

    assert result["isError"] is True
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["success"] is False
    assert "project_id" in response_data["error"].lower()


@pytest.mark.asyncio
async def test_dispatch_session_end_tool(dispatcher, mock_tool_handlers):
    """Test dispatching session_end tool"""
    result = await dispatcher.dispatch(
        "session_end", {"project_id": "test-project", "summary": "Test summary"}
    )

    assert result["isError"] is False
    mock_tool_handlers.session_end.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_session_end_missing_project_id(dispatcher):
    """Test session_end with missing project_id"""
    result = await dispatcher.dispatch("session_end", {"summary": "test"})

    assert result["isError"] is True
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["success"] is False
    assert "project_id" in response_data["error"].lower()


# ============== Error Handling Tests ==============


@pytest.mark.asyncio
async def test_dispatch_unknown_tool(dispatcher):
    """Test dispatching unknown tool"""
    result = await dispatcher.dispatch("unknown_tool", {})

    assert result["isError"] is True
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["success"] is False
    assert "unknown" in response_data["error"].lower()


@pytest.mark.asyncio
async def test_dispatch_exception_handling(dispatcher, mock_tool_handlers):
    """Test exception handling during dispatch"""
    mock_tool_handlers.add = AsyncMock(side_effect=Exception("Test exception"))

    result = await dispatcher.dispatch(
        "add", {"content": "Test content for exception handling"}
    )

    assert result["isError"] is True
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["success"] is False
    assert "Test exception" in response_data["error"]


@pytest.mark.asyncio
async def test_dispatch_validation_error_handling(dispatcher, mock_tool_handlers):
    """Test ValidationError handling during dispatch"""
    from pydantic import BaseModel

    class TestModel(BaseModel):
        value: int

    async def raise_validation_error(*args, **kwargs):
        TestModel(value="not_an_int")

    mock_tool_handlers.add = AsyncMock(side_effect=raise_validation_error)

    result = await dispatcher.dispatch("add", {"content": "Test content"})

    assert result["isError"] is True
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["success"] is False
    assert "validation" in response_data["error"].lower()


# ============== Transport Utility Tests ==============


def test_format_tool_response():
    """Test formatting successful tool response"""
    from app.mcp_common.transport import format_tool_response

    result = {"id": "test-id", "status": "saved"}
    response = format_tool_response(result)

    assert response["isError"] is False
    assert "content" in response
    assert response["content"][0]["type"] == "text"
    parsed = json.loads(response["content"][0]["text"])
    assert parsed == result


def test_format_tool_error():
    """Test formatting tool error response"""
    from app.mcp_common.transport import format_tool_error

    response = format_tool_error("Missing required argument: content")

    assert response["isError"] is True
    assert "content" in response
    parsed = json.loads(response["content"][0]["text"])
    assert parsed["success"] is False
    assert "content" in parsed["error"]


def test_format_jsonrpc_response():
    """Test formatting JSON-RPC success response"""
    from app.mcp_common.transport import format_jsonrpc_response

    result = {"tools": []}
    response = format_jsonrpc_response(result, request_id=1)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert response["result"] == result


def test_format_jsonrpc_error():
    """Test formatting JSON-RPC error response"""
    from app.mcp_common.transport import format_jsonrpc_error

    response = format_jsonrpc_error("Method not found", request_id=1, code=-32601)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert "error" in response
    assert response["error"]["code"] == -32601
    assert response["error"]["message"] == "Method not found"


def test_format_jsonrpc_error_default_code():
    """Test JSON-RPC error with default error code"""
    from app.mcp_common.transport import format_jsonrpc_error

    response = format_jsonrpc_error("Internal error", request_id=2)

    assert response["error"]["code"] == -32603  # Default internal error code


# ============== Response Content Structure Tests ==============


@pytest.mark.asyncio
async def test_dispatch_response_structure(dispatcher, mock_tool_handlers):
    """Test that dispatch returns proper MCP content structure"""
    result = await dispatcher.dispatch(
        "add", {"content": "Test content for structure testing"}
    )

    # Verify MCP content structure
    assert "content" in result
    assert isinstance(result["content"], list)
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    assert isinstance(result["content"][0]["text"], str)

    # Verify JSON parseable
    parsed = json.loads(result["content"][0]["text"])
    assert isinstance(parsed, dict)


@pytest.mark.asyncio
async def test_dispatch_error_response_structure(dispatcher):
    """Test that dispatch error returns proper MCP content structure"""
    result = await dispatcher.dispatch("add", {})  # Missing content

    # Verify MCP error content structure
    assert "content" in result
    assert "isError" in result
    assert result["isError"] is True
    assert isinstance(result["content"], list)
    assert result["content"][0]["type"] == "text"

    # Verify error JSON structure
    parsed = json.loads(result["content"][0]["text"])
    assert parsed["success"] is False
    assert "error" in parsed


# ============== Default Value Tests ==============


@pytest.mark.asyncio
async def test_dispatch_add_default_values(dispatcher, mock_tool_handlers):
    """Test add tool uses default values correctly"""
    await dispatcher.dispatch("add", {"content": "Test content"})

    # Verify default values were passed
    call_kwargs = mock_tool_handlers.add.call_args.kwargs
    assert call_kwargs.get("category") == "task"
    assert call_kwargs.get("source") == "mcp"


@pytest.mark.asyncio
async def test_dispatch_search_default_values(dispatcher, mock_tool_handlers):
    """Test search tool uses default values correctly"""
    await dispatcher.dispatch("search", {"query": "test"})

    call_kwargs = mock_tool_handlers.search.call_args.kwargs
    assert call_kwargs.get("limit") == 5
    assert call_kwargs.get("recency_weight") == 0.0


@pytest.mark.asyncio
async def test_dispatch_context_default_values(dispatcher, mock_tool_handlers):
    """Test context tool uses default values correctly"""
    await dispatcher.dispatch("context", {"memory_id": "test-id"})

    call_kwargs = mock_tool_handlers.context.call_args.kwargs
    assert call_kwargs.get("depth") == 2


@pytest.mark.asyncio
async def test_dispatch_session_resume_default_values(dispatcher, mock_tool_handlers):
    """Test session_resume tool uses default values correctly"""
    await dispatcher.dispatch("session_resume", {"project_id": "test"})

    call_kwargs = mock_tool_handlers.session_resume.call_args.kwargs
    assert call_kwargs.get("expand") is False
    assert call_kwargs.get("limit") == 10
