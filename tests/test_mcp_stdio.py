"""
FastMCP 기반 MCP Stdio 서버 테스트

app/mcp_stdio/server.py의 FastMCP 서버 구현을 테스트합니다.
"""

import os
import tempfile

import pytest

from app.core.config import Settings
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.context import ContextService
from app.core.services.memory import MemoryService
from app.core.services.search import SearchService
from app.core.services.stats import StatsService
from app.mcp_common.schemas import (
    get_all_tool_schemas,
)
from app.mcp_common.storage import StorageManager
from app.mcp_common.tools import MCPToolHandlers

# ============== Fixtures ==============


@pytest.fixture
def temp_db():
    """임시 데이터베이스 생성"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


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
def context_service(db, embedding_service):
    """컨텍스트 서비스 인스턴스"""
    return ContextService(db, embedding_service)


@pytest.fixture
def stats_service(db):
    """통계 서비스 인스턴스"""
    return StatsService(db)


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


# ============== Initialization Tests ==============


@pytest.mark.asyncio
async def test_initialize_storage_direct_mode(temp_settings):
    """Direct 모드 스토리지 초기화 테스트"""
    manager = StorageManager()

    try:
        storage = await manager.initialize(temp_settings)

        assert storage is not None
        assert manager.is_initialized is True
        assert manager.storage is not None
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_initialize_storage_creates_handlers(temp_settings):
    """스토리지 초기화 후 핸들러 생성 테스트"""
    manager = StorageManager()

    try:
        storage = await manager.initialize(temp_settings)
        handlers = MCPToolHandlers(storage)

        assert handlers is not None
        assert handlers.storage is storage
    finally:
        await manager.shutdown()


# ============== Tool Registration Tests ==============


def test_tools_registered():
    """모든 11개 도구가 등록되었는지 테스트"""
    all_schemas = get_all_tool_schemas()
    tool_names = [schema["name"] for schema in all_schemas]

    # Memory tools (6)
    expected_memory_tools = ["add", "search", "context", "update", "delete", "stats"]
    for tool in expected_memory_tools:
        assert tool in tool_names, f"Memory tool '{tool}' not found"

    # Pin/Session tools (5)
    expected_pin_tools = [
        "pin_add",
        "pin_complete",
        "pin_promote",
        "session_resume",
        "session_end",
    ]
    for tool in expected_pin_tools:
        assert tool in tool_names, f"Pin/Session tool '{tool}' not found"

    # Total should be at least 11 (6 memory + 5 pin/session)
    assert len(tool_names) >= 11


def test_tool_schemas_valid():
    """도구 스키마가 유효한 JSON Schema인지 테스트"""
    all_schemas = get_all_tool_schemas()

    for schema in all_schemas:
        # 필수 필드 확인
        assert "name" in schema, "Schema missing 'name'"
        assert (
            "description" in schema
        ), f"Schema {schema.get('name', 'unknown')} missing 'description'"
        assert "inputSchema" in schema, f"Schema {schema['name']} missing 'inputSchema'"

        input_schema = schema["inputSchema"]

        # JSON Schema 기본 구조 확인
        assert (
            input_schema.get("type") == "object"
        ), f"Schema {schema['name']} inputSchema type should be 'object'"
        assert (
            "properties" in input_schema
        ), f"Schema {schema['name']} missing 'properties'"


# ============== Core Memory Tool Tests ==============


@pytest.mark.asyncio
async def test_add_memory_tool(tool_handlers):
    """add 도구 테스트 - 메모리 생성"""
    result = await tool_handlers.add(
        content="Test memory content for FastMCP stdio server testing",
        project_id="test-project",
        category="task",
        source="mcp-test",
        tags=["test", "fastmcp"],
    )

    assert "id" in result
    assert result["status"] == "saved"
    assert "created_at" in result


@pytest.mark.asyncio
async def test_search_memory_tool(tool_handlers):
    """search 도구 테스트 - 메모리 검색"""
    # 먼저 메모리 추가
    await tool_handlers.add(
        content="Authentication system implementation with JWT tokens for secure access",
        project_id="test-project",
        category="task",
    )

    # 검색 수행
    result = await tool_handlers.search(
        query="authentication JWT", project_id="test-project", limit=5
    )

    assert "results" in result
    assert isinstance(result["results"], list)


@pytest.mark.asyncio
async def test_stats_tool(tool_handlers, memory_service):
    """stats 도구 테스트 - 통계 조회"""
    # 테스트용 메모리 추가
    await memory_service.create(
        content="Test memory for stats verification",
        project_id="test-project",
        category="task",
        source="test",
    )

    # 통계 조회
    result = await tool_handlers.stats()

    assert "total_memories" in result
    assert "unique_projects" in result
    assert "categories_breakdown" in result
    assert "sources_breakdown" in result
    assert "query_time_ms" in result
    assert result["total_memories"] >= 1


# ============== Pin/Session Tool Tests ==============


@pytest.mark.asyncio
async def test_pin_add_tool(tool_handlers):
    """pin_add 도구 테스트 - Pin 생성"""
    result = await tool_handlers.pin_add(
        content="Implement new feature for user dashboard",
        project_id="test-project",
        importance=3,
        tags=["feature", "dashboard"],
    )

    assert "id" in result
    assert result["content"] == "Implement new feature for user dashboard"
    assert result["project_id"] == "test-project"
    assert result["status"] in ("active", "open")


@pytest.mark.asyncio
async def test_session_resume_tool(tool_handlers):
    """session_resume 도구 테스트 - 세션 재개"""
    # 먼저 Pin 추가하여 세션 생성
    await tool_handlers.pin_add(
        content="Test pin for session resume", project_id="test-project", importance=2
    )

    # 세션 재개
    result = await tool_handlers.session_resume(
        project_id="test-project", expand=False, limit=10
    )

    # 세션이 있거나 없을 수 있음
    if result.get("status") == "no_session":
        assert "message" in result
    else:
        assert "session_id" in result or "pins_count" in result


# ============== Error Handling Tests ==============


@pytest.mark.asyncio
async def test_invalid_tool_name():
    """알 수 없는 도구 이름 테스트"""
    all_schemas = get_all_tool_schemas()
    tool_names = [schema["name"] for schema in all_schemas]

    # 존재하지 않는 도구 이름 확인
    assert "unknown-tool" not in tool_names
    assert "invalid_tool" not in tool_names


@pytest.mark.asyncio
async def test_missing_required_params(tool_handlers):
    """필수 파라미터 누락 테스트"""
    # content가 너무 짧은 경우 (10자 미만)
    with pytest.raises(Exception):
        await tool_handlers.add(content="short")


# ============== Additional Coverage Tests ==============


@pytest.mark.asyncio
async def test_context_tool(tool_handlers):
    """context 도구 테스트 - 컨텍스트 조회"""
    # 먼저 메모리 추가
    add_result = await tool_handlers.add(
        content="User authentication system with JWT implementation for API security",
        project_id="test-project",
        category="task",
    )
    memory_id = add_result["id"]

    # 컨텍스트 조회
    result = await tool_handlers.context(
        memory_id=memory_id, depth=2, project_id="test-project"
    )

    assert "memory" in result or "primary_memory" in result
    assert "related_memories" in result


@pytest.mark.asyncio
async def test_update_tool(tool_handlers):
    """update 도구 테스트 - 메모리 업데이트"""
    # 먼저 메모리 추가
    add_result = await tool_handlers.add(
        content="Original authentication implementation for testing",
        project_id="test-project",
        category="task",
    )
    memory_id = add_result["id"]

    # 메모리 업데이트
    result = await tool_handlers.update(
        memory_id=memory_id,
        content="Updated authentication implementation with better security measures",
        category="decision",
        tags=["auth", "security", "updated"],
    )

    assert result["id"] == memory_id
    assert result["status"] == "updated"


@pytest.mark.asyncio
async def test_delete_tool(tool_handlers):
    """delete 도구 테스트 - 메모리 삭제"""
    # 먼저 메모리 추가
    add_result = await tool_handlers.add(
        content="Memory to be deleted for testing purposes",
        project_id="test-project",
        category="task",
    )
    memory_id = add_result["id"]

    # 메모리 삭제
    result = await tool_handlers.delete(memory_id=memory_id)

    assert result["id"] == memory_id
    assert result["status"] == "deleted"


@pytest.mark.asyncio
async def test_search_with_filters(tool_handlers):
    """search 도구 필터링 테스트"""
    # 다양한 카테고리로 메모리 추가
    await tool_handlers.add(
        content="Bug fix for login validation error handling",
        project_id="filter-project",
        category="bug",
    )
    await tool_handlers.add(
        content="New feature idea for user dashboard improvements",
        project_id="filter-project",
        category="idea",
    )

    # 카테고리 필터로 검색
    result = await tool_handlers.search(
        query="login validation", project_id="filter-project", category="bug", limit=5
    )

    assert "results" in result


@pytest.mark.asyncio
async def test_stats_with_project_filter(tool_handlers, memory_service):
    """stats 도구 프로젝트 필터링 테스트"""
    # 특정 프로젝트에 메모리 추가
    await memory_service.create(
        content="Test memory for filtered stats verification",
        project_id="stats-filter-project",
        category="bug",
        source="test",
    )

    # 프로젝트 필터로 통계 조회
    result = await tool_handlers.stats(project_id="stats-filter-project")

    assert result["total_memories"] >= 1
    assert result["unique_projects"] == 1


@pytest.mark.asyncio
async def test_pin_complete_tool(tool_handlers):
    """pin_complete 도구 테스트 - Pin 완료"""
    # 먼저 Pin 추가
    pin_result = await tool_handlers.pin_add(
        content="Task to be completed for testing",
        project_id="test-project",
        importance=4,
    )
    pin_id = pin_result["id"]

    # Pin 완료
    result = await tool_handlers.pin_complete(pin_id=pin_id)

    assert result["id"] == pin_id
    assert result["status"] == "completed"
    # importance >= 4이면 승격 제안
    assert "suggest_promotion" in result


@pytest.mark.asyncio
async def test_nonexistent_memory_context(tool_handlers):
    """존재하지 않는 메모리 컨텍스트 조회 테스트"""
    with pytest.raises(Exception):
        await tool_handlers.context(memory_id="nonexistent-id-12345")


@pytest.mark.asyncio
async def test_search_response_formats(tool_handlers):
    """search 도구 응답 형식 테스트"""
    # 메모리 추가
    await tool_handlers.add(
        content="Test content for response format verification testing",
        project_id="format-test",
        category="task",
    )

    # minimal 형식
    result_minimal = await tool_handlers.search(
        query="response format", limit=5, response_format="minimal"
    )
    assert "results" in result_minimal

    # compact 형식
    result_compact = await tool_handlers.search(
        query="response format", limit=5, response_format="compact"
    )
    assert "results" in result_compact

    # standard 형식
    result_standard = await tool_handlers.search(
        query="response format", limit=5, response_format="standard"
    )
    assert "results" in result_standard
