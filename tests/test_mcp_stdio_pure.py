"""
Pure MCP Stdio 서버 테스트

app/mcp_stdio_pure/server.py의 순수 MCP 프로토콜 구현을 테스트합니다.
FastMCP와 달리 수동 JSON-RPC 파싱과 도구 디스패치를 테스트합니다.
"""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.memory import MemoryService
from app.core.services.search import SearchService
from app.core.version import MCP_PROTOCOL_VERSION, SERVER_INFO
from app.mcp_common.storage import StorageManager
from app.mcp_common.tools import MCPToolHandlers

# Import Pure MCP server functions
from app.mcp_stdio_pure.server import (
    call_tool,
    list_tools,
    parse_message,
    resp_initialize,
    write_error,
    write_message,
    write_result,
)

# ============== Fixtures ==============


@pytest.fixture
def temp_db():
    """임시 데이터베이스 생성"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    for ext in ["", "-wal", "-shm"]:
        p = path + ext
        if os.path.exists(p):
            os.unlink(p)


@pytest.fixture
async def db(temp_db):
    """데이터베이스 인스턴스"""
    database = Database(temp_db)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def embedding_service():
    """임베딩 서비스 인스턴스"""
    return EmbeddingService(preload=False)


@pytest.fixture
def memory_service(db, embedding_service):
    """메모리 서비스 인스턴스"""
    return MemoryService(db, embedding_service)


@pytest.fixture
def search_service(db, embedding_service):
    """검색 서비스 인스턴스"""
    return SearchService(db, embedding_service)


@pytest.fixture
def temp_settings(temp_db):
    """테스트용 설정"""
    return Settings(database_path=temp_db, storage_mode="direct")


@pytest.fixture
async def storage_manager(temp_settings):
    """스토리지 매니저 인스턴스"""
    manager = StorageManager()
    await manager.initialize(temp_settings)
    yield manager
    await manager.shutdown()


@pytest.fixture
async def tool_handlers(storage_manager):
    """MCP 도구 핸들러 인스턴스"""
    return MCPToolHandlers(storage_manager.storage)


@pytest.fixture
async def dispatcher_fixture(tool_handlers):
    """MCP 디스패처 인스턴스"""
    from app.mcp_common.dispatcher import MCPDispatcher

    return MCPDispatcher(tool_handlers)


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
def mock_dispatcher(mock_tool_handlers):
    """Mock dispatcher for isolated testing"""
    from app.mcp_common.dispatcher import MCPDispatcher

    return MCPDispatcher(mock_tool_handlers)


# ============== JSON-RPC Message Parsing Tests ==============


def test_parse_initialize_message():
    """initialize 요청 메시지 파싱 테스트"""
    message = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        }
    )

    result = parse_message(message)

    assert result is not None
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 1
    assert result["method"] == "initialize"
    assert "params" in result
    assert result["params"]["protocolVersion"] == "2024-11-05"


def test_parse_tools_list_message():
    """tools/list 요청 메시지 파싱 테스트"""
    message = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    result = parse_message(message)

    assert result is not None
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 2
    assert result["method"] == "tools/list"


def test_parse_tools_call_message():
    """tools/call 요청 메시지 파싱 테스트"""
    message = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "add",
                "arguments": {
                    "content": "Test memory content",
                    "project_id": "test-project",
                    "category": "task",
                },
            },
        }
    )

    result = parse_message(message)

    assert result is not None
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 3
    assert result["method"] == "tools/call"
    assert result["params"]["name"] == "add"
    assert result["params"]["arguments"]["content"] == "Test memory content"


# ============== Error Handling Tests ==============


def test_malformed_json():
    """잘못된 JSON 처리 테스트"""
    malformed_messages = [
        "{invalid json}",
        "not json at all",
        '{"incomplete": ',
        "",
        "   ",
    ]

    for msg in malformed_messages:
        result = parse_message(msg)
        assert result is None, f"Expected None for malformed JSON: {msg}"


def test_missing_jsonrpc_field():
    """jsonrpc 필드 누락 테스트"""
    # Missing jsonrpc field entirely
    message1 = json.dumps({"id": 1, "method": "initialize"})
    result1 = parse_message(message1)
    assert result1 is None

    # Wrong jsonrpc version
    message2 = json.dumps({"jsonrpc": "1.0", "id": 1, "method": "initialize"})
    result2 = parse_message(message2)
    assert result2 is None


def test_invalid_message_format():
    """잘못된 메시지 형식 테스트"""
    # Array instead of object
    message1 = json.dumps([1, 2, 3])
    result1 = parse_message(message1)
    assert result1 is None

    # String instead of object
    message2 = json.dumps("just a string")
    result2 = parse_message(message2)
    assert result2 is None

    # Number instead of object
    message3 = json.dumps(12345)
    result3 = parse_message(message3)
    assert result3 is None


def test_empty_line():
    """빈 라인 처리 테스트"""
    result = parse_message("")
    assert result is None

    result2 = parse_message(None)
    assert result2 is None


# ============== Protocol Handler Tests ==============


def test_resp_initialize():
    """initialize 응답 테스트"""
    params = {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0"},
    }

    result = resp_initialize(params)

    assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert "capabilities" in result
    assert "tools" in result["capabilities"]
    assert "serverInfo" in result
    assert result["serverInfo"]["name"] == SERVER_INFO["name"]
    assert result["serverInfo"]["version"] == SERVER_INFO["version"]


def test_list_tools():
    """tools/list 응답 테스트"""
    result = list_tools()

    assert "tools" in result
    assert isinstance(result["tools"], list)
    assert len(result["tools"]) >= 11  # At least 11 tools

    # Verify tool structure
    tool_names = [tool["name"] for tool in result["tools"]]
    expected_tools = [
        "add",
        "search",
        "context",
        "update",
        "delete",
        "stats",
        "pin_add",
        "pin_complete",
        "pin_promote",
        "session_resume",
        "session_end",
    ]
    for expected in expected_tools:
        assert expected in tool_names, f"Tool '{expected}' not found in list"


# ============== Tool Dispatch Tests ==============


@pytest.mark.asyncio
async def test_dispatch_add_tool(tool_handlers, dispatcher_fixture):
    """add 도구 디스패치 테스트"""
    import app.mcp_stdio_pure.server as server

    original_handlers = server.tool_handlers
    original_dispatcher = server.dispatcher
    server.tool_handlers = tool_handlers
    server.dispatcher = dispatcher_fixture

    try:
        params = {
            "name": "add",
            "arguments": {
                "content": "Test memory content for dispatch testing purposes",
                "project_id": "test-project",
                "category": "task",
            },
        }

        result = await call_tool(params)

        assert "content" in result
        assert result["content"][0]["type"] == "text"
        assert "isError" not in result or result.get("isError") is False

        response_data = json.loads(result["content"][0]["text"])
        assert "id" in response_data
        assert response_data["status"] == "saved"
    finally:
        server.tool_handlers = original_handlers
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_dispatch_search_tool(tool_handlers, dispatcher_fixture):
    """search 도구 디스패치 테스트"""
    import app.mcp_stdio_pure.server as server

    original_handlers = server.tool_handlers
    original_dispatcher = server.dispatcher
    server.tool_handlers = tool_handlers
    server.dispatcher = dispatcher_fixture

    try:
        await tool_handlers.add(
            content="Authentication system with JWT tokens for testing",
            project_id="test-project",
            category="task",
        )

        params = {
            "name": "search",
            "arguments": {"query": "authentication JWT", "limit": 5},
        }

        result = await call_tool(params)

        assert "content" in result
        response_data = json.loads(result["content"][0]["text"])
        assert "results" in response_data
    finally:
        server.tool_handlers = original_handlers
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_dispatch_pin_tool(tool_handlers, dispatcher_fixture):
    """pin_add 도구 디스패치 테스트"""
    import app.mcp_stdio_pure.server as server

    original_handlers = server.tool_handlers
    original_dispatcher = server.dispatcher
    server.tool_handlers = tool_handlers
    server.dispatcher = dispatcher_fixture

    try:
        params = {
            "name": "pin_add",
            "arguments": {
                "content": "Implement new feature for testing",
                "project_id": "test-project",
                "importance": 3,
            },
        }

        result = await call_tool(params)

        assert "content" in result
        response_data = json.loads(result["content"][0]["text"])
        assert "id" in response_data
        assert response_data["status"] == "in_progress"
    finally:
        server.tool_handlers = original_handlers
        server.dispatcher = original_dispatcher


# ============== Invalid Tool Parameters Tests ==============


@pytest.mark.asyncio
async def test_invalid_tool_params_missing_content(mock_dispatcher):
    """필수 파라미터 누락 테스트 - add 도구"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = mock_dispatcher

    try:
        params = {
            "name": "add",
            "arguments": {
                "project_id": "test-project",
            },
        }

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "content" in response_data["error"].lower()
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_invalid_tool_params_missing_query(mock_dispatcher):
    """필수 파라미터 누락 테스트 - search 도구"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = mock_dispatcher

    try:
        params = {
            "name": "search",
            "arguments": {
                "limit": 5,
            },
        }

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "query" in response_data["error"].lower()
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_unknown_tool(mock_dispatcher):
    """알 수 없는 도구 호출 테스트"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = mock_dispatcher

    try:
        params = {"name": "unknown_tool", "arguments": {}}

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "unknown" in response_data["error"].lower()
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_missing_tool_name(mock_dispatcher):
    """도구 이름 누락 테스트"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = mock_dispatcher

    try:
        params = {"arguments": {"content": "test"}}

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "tool name" in response_data["error"].lower()
    finally:
        server.dispatcher = original_dispatcher


# ============== Response Formatting Tests ==============


def test_write_message_format(capsys):
    """write_message NDJSON 형식 테스트"""
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"test": "value"}}

    write_message(payload)

    captured = capsys.readouterr()
    # Should be valid JSON followed by newline
    assert captured.out.endswith("\n")
    parsed = json.loads(captured.out.strip())
    assert parsed == payload


def test_write_result_format(capsys):
    """write_result 응답 형식 테스트"""
    write_result(1, {"status": "ok"})

    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())

    assert parsed["jsonrpc"] == "2.0"
    assert parsed["id"] == 1
    assert parsed["result"] == {"status": "ok"}


def test_write_error_format(capsys):
    """write_error 에러 응답 형식 테스트"""
    write_error(1, -32601, "Method not found")

    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())

    assert parsed["jsonrpc"] == "2.0"
    assert parsed["id"] == 1
    assert "error" in parsed
    assert parsed["error"]["code"] == -32601
    assert parsed["error"]["message"] == "Method not found"


# ============== Additional Tool Dispatch Tests ==============


@pytest.mark.asyncio
async def test_dispatch_context_tool(tool_handlers, dispatcher_fixture):
    """context 도구 디스패치 테스트"""
    import app.mcp_stdio_pure.server as server

    original_handlers = server.tool_handlers
    original_dispatcher = server.dispatcher
    server.tool_handlers = tool_handlers
    server.dispatcher = dispatcher_fixture

    try:
        add_result = await tool_handlers.add(
            content="Test memory for context retrieval testing",
            project_id="test-project",
            category="task",
        )
        memory_id = add_result["id"]

        params = {
            "name": "context",
            "arguments": {"memory_id": memory_id, "depth": 2},
        }

        result = await call_tool(params)

        assert "content" in result
        response_data = json.loads(result["content"][0]["text"])
        assert "related_memories" in response_data
    finally:
        server.tool_handlers = original_handlers
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_dispatch_update_tool(tool_handlers, dispatcher_fixture):
    """update 도구 디스패치 테스트"""
    import app.mcp_stdio_pure.server as server

    original_handlers = server.tool_handlers
    original_dispatcher = server.dispatcher
    server.tool_handlers = tool_handlers
    server.dispatcher = dispatcher_fixture

    try:
        add_result = await tool_handlers.add(
            content="Original content for update testing purposes",
            project_id="test-project",
            category="task",
        )
        memory_id = add_result["id"]

        params = {
            "name": "update",
            "arguments": {
                "memory_id": memory_id,
                "content": "Updated content with new information",
                "category": "decision",
            },
        }

        result = await call_tool(params)

        assert "content" in result
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["status"] == "updated"
    finally:
        server.tool_handlers = original_handlers
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_dispatch_delete_tool(tool_handlers, dispatcher_fixture):
    """delete 도구 디스패치 테스트"""
    import app.mcp_stdio_pure.server as server

    original_handlers = server.tool_handlers
    original_dispatcher = server.dispatcher
    server.tool_handlers = tool_handlers
    server.dispatcher = dispatcher_fixture

    try:
        add_result = await tool_handlers.add(
            content="Memory to be deleted for testing purposes",
            project_id="test-project",
            category="task",
        )
        memory_id = add_result["id"]

        params = {"name": "delete", "arguments": {"memory_id": memory_id}}

        result = await call_tool(params)

        assert "content" in result
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["status"] == "deleted"
    finally:
        server.tool_handlers = original_handlers
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_dispatch_stats_tool(tool_handlers, dispatcher_fixture):
    """stats 도구 디스패치 테스트"""
    import app.mcp_stdio_pure.server as server

    original_handlers = server.tool_handlers
    original_dispatcher = server.dispatcher
    server.tool_handlers = tool_handlers
    server.dispatcher = dispatcher_fixture

    try:
        params = {"name": "stats", "arguments": {}}

        result = await call_tool(params)

        assert "content" in result
        response_data = json.loads(result["content"][0]["text"])
        assert "total_memories" in response_data
        assert "unique_projects" in response_data
    finally:
        server.tool_handlers = original_handlers
        server.dispatcher = original_dispatcher


# ============== Session Tool Dispatch Tests ==============


@pytest.mark.asyncio
async def test_dispatch_session_resume_tool(tool_handlers, dispatcher_fixture):
    """session_resume 도구 디스패치 테스트"""
    import app.mcp_stdio_pure.server as server

    original_handlers = server.tool_handlers
    original_dispatcher = server.dispatcher
    server.tool_handlers = tool_handlers
    server.dispatcher = dispatcher_fixture

    try:
        params = {
            "name": "session_resume",
            "arguments": {"project_id": "test-project", "expand": False, "limit": 10},
        }

        result = await call_tool(params)

        assert "content" in result
        # Session may or may not exist
        response_data = json.loads(result["content"][0]["text"])
        assert isinstance(response_data, dict)
    finally:
        server.tool_handlers = original_handlers
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_dispatch_session_end_tool(tool_handlers, dispatcher_fixture):
    """session_end 도구 디스패치 테스트"""
    import app.mcp_stdio_pure.server as server

    original_handlers = server.tool_handlers
    original_dispatcher = server.dispatcher
    server.tool_handlers = tool_handlers
    server.dispatcher = dispatcher_fixture

    try:
        params = {
            "name": "session_end",
            "arguments": {"project_id": "test-project", "summary": "Test session end"},
        }

        result = await call_tool(params)

        assert "content" in result
        response_data = json.loads(result["content"][0]["text"])
        assert isinstance(response_data, dict)
    finally:
        server.tool_handlers = original_handlers
        server.dispatcher = original_dispatcher


# ============== Tool Handlers Not Initialized Test ==============


@pytest.mark.asyncio
async def test_tool_handlers_not_initialized():
    """도구 핸들러 미초기화 상태 테스트"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = None

    try:
        params = {"name": "add", "arguments": {"content": "test"}}

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "not initialized" in response_data["error"].lower()
    finally:
        server.dispatcher = original_dispatcher


# ============== Pin Tool Required Parameters Tests ==============


@pytest.mark.asyncio
async def test_pin_add_missing_params(mock_dispatcher):
    """pin_add 필수 파라미터 누락 테스트"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = mock_dispatcher

    try:
        params = {"name": "pin_add", "arguments": {"content": "test content"}}

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_pin_complete_missing_params(mock_dispatcher):
    """pin_complete 필수 파라미터 누락 테스트"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = mock_dispatcher

    try:
        params = {"name": "pin_complete", "arguments": {}}

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "pin_id" in response_data["error"].lower()
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_pin_promote_missing_params(mock_dispatcher):
    """pin_promote 필수 파라미터 누락 테스트"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = mock_dispatcher

    try:
        params = {"name": "pin_promote", "arguments": {}}

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "pin_id" in response_data["error"].lower()
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_context_missing_memory_id(mock_dispatcher):
    """context 필수 파라미터 누락 테스트"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = mock_dispatcher

    try:
        params = {"name": "context", "arguments": {"depth": 2}}

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "memory_id" in response_data["error"].lower()
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_update_missing_memory_id(mock_dispatcher):
    """update 필수 파라미터 누락 테스트"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = mock_dispatcher

    try:
        params = {"name": "update", "arguments": {"content": "new content"}}

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "memory_id" in response_data["error"].lower()
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_delete_missing_memory_id(mock_dispatcher):
    """delete 필수 파라미터 누락 테스트"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = mock_dispatcher

    try:
        params = {"name": "delete", "arguments": {}}

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "memory_id" in response_data["error"].lower()
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_session_resume_missing_project_id(mock_dispatcher):
    """session_resume 필수 파라미터 누락 테스트"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = mock_dispatcher

    try:
        params = {"name": "session_resume", "arguments": {"expand": True}}

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "project_id" in response_data["error"].lower()
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_session_end_missing_project_id(mock_dispatcher):
    """session_end 필수 파라미터 누락 테스트"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = mock_dispatcher

    try:
        params = {"name": "session_end", "arguments": {"summary": "test"}}

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "project_id" in response_data["error"].lower()
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_batch_operations_missing_operations(mock_dispatcher):
    """batch_operations 필수 파라미터 누락 테스트"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = mock_dispatcher

    try:
        params = {"name": "batch_operations", "arguments": {}}

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "operations" in response_data["error"].lower()
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_batch_operations_fallback_without_handler(mock_dispatcher):
    """batch_operations BatchOperationHandler 없이 fallback 순차 처리 테스트"""
    import app.mcp_stdio_pure.server as server

    original_dispatcher = server.dispatcher
    server.dispatcher = mock_dispatcher

    try:
        params = {"name": "batch_operations", "arguments": {"operations": []}}

        result = await call_tool(params)

        assert result["isError"] is False
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["status"] == "success"
        assert response_data["total_operations"] == 0
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_dispatch_pin_promote_tool(tool_handlers, dispatcher_fixture):
    """pin_promote 도구 디스패치 테스트"""
    import app.mcp_stdio_pure.server as server

    original_handlers = server.tool_handlers
    original_dispatcher = server.dispatcher
    server.tool_handlers = tool_handlers
    server.dispatcher = dispatcher_fixture

    try:
        pin_result = await tool_handlers.pin_add(
            content="Important task to be promoted",
            project_id="test-project",
            importance=5,
        )
        pin_id = pin_result["id"]

        await tool_handlers.pin_complete(pin_id=pin_id)

        params = {"name": "pin_promote", "arguments": {"pin_id": pin_id}}

        result = await call_tool(params)

        assert "content" in result
        response_data = json.loads(result["content"][0]["text"])
        assert isinstance(response_data, dict)
    finally:
        server.tool_handlers = original_handlers
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_tool_exception_handling(mock_tool_handlers):
    """도구 실행 중 예외 처리 테스트"""
    import app.mcp_stdio_pure.server as server
    from app.mcp_common.dispatcher import MCPDispatcher

    mock_tool_handlers.add = AsyncMock(side_effect=Exception("Test exception"))
    mock_disp = MCPDispatcher(mock_tool_handlers)
    original_dispatcher = server.dispatcher
    server.dispatcher = mock_disp

    try:
        params = {
            "name": "add",
            "arguments": {
                "content": "Test content for exception handling",
                "project_id": "test",
            },
        }

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "Test exception" in response_data["error"]
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_validation_error_handling(mock_tool_handlers):
    """ValidationError 처리 테스트"""
    from pydantic import BaseModel

    import app.mcp_stdio_pure.server as server
    from app.mcp_common.dispatcher import MCPDispatcher

    class TestModel(BaseModel):
        value: int

    async def raise_validation_error(*args, **kwargs):
        TestModel(value="not_an_int")

    mock_tool_handlers.add = AsyncMock(side_effect=raise_validation_error)
    mock_disp = MCPDispatcher(mock_tool_handlers)
    original_dispatcher = server.dispatcher
    server.dispatcher = mock_disp

    try:
        params = {
            "name": "add",
            "arguments": {"content": "test content", "project_id": "test"},
        }

        result = await call_tool(params)

        assert result["isError"] is True
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["success"] is False
        assert "validation error" in response_data["error"].lower()
    finally:
        server.dispatcher = original_dispatcher


@pytest.mark.asyncio
async def test_dispatch_pin_complete_tool(tool_handlers, dispatcher_fixture):
    """pin_complete 도구 디스패치 테스트"""
    import app.mcp_stdio_pure.server as server

    original_handlers = server.tool_handlers
    original_dispatcher = server.dispatcher
    server.tool_handlers = tool_handlers
    server.dispatcher = dispatcher_fixture

    try:
        pin_result = await tool_handlers.pin_add(
            content="Task to be completed via dispatch",
            project_id="test-project",
            importance=3,
        )
        pin_id = pin_result["id"]

        params = {"name": "pin_complete", "arguments": {"pin_id": pin_id}}

        result = await call_tool(params)

        assert "content" in result
        response_data = json.loads(result["content"][0]["text"])
        assert response_data["status"] == "completed"
    finally:
        server.tool_handlers = original_handlers
        server.dispatcher = original_dispatcher


# ============== Notification Handling Test ==============


def test_parse_notification_message():
    """알림 메시지 (id 없음) 파싱 테스트"""
    message = json.dumps(
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    )

    result = parse_message(message)

    assert result is not None
    assert result["jsonrpc"] == "2.0"
    assert result["method"] == "notifications/initialized"
    assert "id" not in result  # Notifications don't have id


# ============== Unicode and Special Characters Test ==============


def test_parse_unicode_message():
    """유니코드 메시지 파싱 테스트"""
    message = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "add",
                "arguments": {
                    "content": "한글 테스트 메시지 with 특수문자 !@#$%",
                    "project_id": "테스트-프로젝트",
                },
            },
        },
        ensure_ascii=False,
    )

    result = parse_message(message)

    assert result is not None
    assert (
        result["params"]["arguments"]["content"]
        == "한글 테스트 메시지 with 특수문자 !@#$%"
    )
    assert result["params"]["arguments"]["project_id"] == "테스트-프로젝트"
