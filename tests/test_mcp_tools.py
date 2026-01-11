"""
MCP Tools 테스트
"""

import pytest
import tempfile
import os
import json

from src.database.base import Database
from src.embeddings.service import EmbeddingService
from src.services.memory import MemoryService
from src.services.search import SearchService
from src.services.context import ContextService
from src.services.stats import StatsService
from src.mcp.tools import MCPTools


@pytest.fixture
def temp_db():
    """임시 데이터베이스 생성"""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
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
    return EmbeddingService()


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
def mcp_tools(memory_service, search_service, context_service, stats_service):
    """MCP 도구 인스턴스"""
    return MCPTools(memory_service, search_service, context_service, stats_service)


@pytest.mark.asyncio
async def test_get_available_tools(mcp_tools):
    """사용 가능한 도구 목록 테스트"""
    tools = mcp_tools.get_available_tools()
    
    assert len(tools) == 6
    tool_names = [tool["name"] for tool in tools]
    
    expected_tools = [
        "mem-mesh.add",
        "mem-mesh.search", 
        "mem-mesh.context",
        "mem-mesh.update",
        "mem-mesh.delete",
        "mem-mesh.stats"
    ]
    
    for expected_tool in expected_tools:
        assert expected_tool in tool_names


@pytest.mark.asyncio
async def test_handle_add_tool(mcp_tools):
    """mem-mesh.add 도구 테스트"""
    arguments = {
        "content": "Test memory content for MCP tool testing",
        "project_id": "test-project",
        "category": "task",
        "source": "mcp-test",
        "tags": ["test", "mcp"]
    }
    
    result = await mcp_tools.handle_tool_call("mem-mesh.add", arguments)
    
    assert "content" in result
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    
    # JSON 응답 파싱
    response_data = json.loads(result["content"][0]["text"])
    assert "id" in response_data
    assert response_data["status"] == "saved"
    assert "created_at" in response_data


@pytest.mark.asyncio
async def test_handle_search_tool(mcp_tools):
    """mem-mesh.search 도구 테스트"""
    # 먼저 메모리 추가
    add_args = {
        "content": "Authentication system implementation with JWT tokens",
        "project_id": "test-project",
        "category": "task"
    }
    await mcp_tools.handle_tool_call("mem-mesh.add", add_args)
    
    # 검색 수행
    search_args = {
        "query": "authentication JWT",
        "project_id": "test-project",
        "limit": 5
    }
    
    result = await mcp_tools.handle_tool_call("mem-mesh.search", search_args)
    
    assert "content" in result
    response_data = json.loads(result["content"][0]["text"])
    assert "results" in response_data
    assert len(response_data["results"]) >= 1


@pytest.mark.asyncio
async def test_handle_context_tool(mcp_tools):
    """mem-mesh.context 도구 테스트"""
    # 먼저 메모리 추가
    add_args = {
        "content": "User authentication system with JWT implementation",
        "project_id": "test-project",
        "category": "task"
    }
    add_result = await mcp_tools.handle_tool_call("mem-mesh.add", add_args)
    add_response = json.loads(add_result["content"][0]["text"])
    memory_id = add_response["id"]
    
    # 맥락 조회
    context_args = {
        "memory_id": memory_id,
        "depth": 2
    }
    
    result = await mcp_tools.handle_tool_call("mem-mesh.context", context_args)
    
    assert "content" in result
    response_data = json.loads(result["content"][0]["text"])
    assert "primary_memory" in response_data
    assert "related_memories" in response_data
    assert "timeline" in response_data
    assert response_data["primary_memory"]["id"] == memory_id


@pytest.mark.asyncio
async def test_handle_update_tool(mcp_tools):
    """mem-mesh.update 도구 테스트"""
    # 먼저 메모리 추가
    add_args = {
        "content": "Original authentication implementation",
        "project_id": "test-project",
        "category": "task"
    }
    add_result = await mcp_tools.handle_tool_call("mem-mesh.add", add_args)
    add_response = json.loads(add_result["content"][0]["text"])
    memory_id = add_response["id"]
    
    # 메모리 업데이트
    update_args = {
        "memory_id": memory_id,
        "content": "Updated authentication implementation with better security",
        "category": "task",
        "tags": ["auth", "security", "updated"]
    }
    
    result = await mcp_tools.handle_tool_call("mem-mesh.update", update_args)
    
    assert "content" in result
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["id"] == memory_id
    assert response_data["status"] == "updated"


@pytest.mark.asyncio
async def test_handle_delete_tool(mcp_tools):
    """mem-mesh.delete 도구 테스트"""
    # 먼저 메모리 추가
    add_args = {
        "content": "Memory to be deleted for testing",
        "project_id": "test-project",
        "category": "task"
    }
    add_result = await mcp_tools.handle_tool_call("mem-mesh.add", add_args)
    add_response = json.loads(add_result["content"][0]["text"])
    memory_id = add_response["id"]
    
    # 메모리 삭제
    delete_args = {
        "memory_id": memory_id
    }
    
    result = await mcp_tools.handle_tool_call("mem-mesh.delete", delete_args)
    
    assert "content" in result
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["id"] == memory_id
    assert response_data["status"] == "deleted"


@pytest.mark.asyncio
async def test_handle_unknown_tool(mcp_tools):
    """알 수 없는 도구 호출 테스트"""
    result = await mcp_tools.handle_tool_call("unknown-tool", {})
    
    assert "content" in result
    assert "isError" in result
    assert result["isError"] is True
    
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["error"] == "UNKNOWN_TOOL"


@pytest.mark.asyncio
async def test_handle_invalid_arguments(mcp_tools):
    """잘못된 인수로 도구 호출 테스트"""
    # content가 너무 짧은 경우
    arguments = {
        "content": "short"  # 10자 미만
    }
    
    result = await mcp_tools.handle_tool_call("mem-mesh.add", arguments)
    
    assert "content" in result
    assert "isError" in result
    assert result["isError"] is True


@pytest.mark.asyncio
async def test_handle_nonexistent_memory_context(mcp_tools):
    """존재하지 않는 메모리 맥락 조회 테스트"""
    context_args = {
        "memory_id": "nonexistent-id"
    }
    
    result = await mcp_tools.handle_tool_call("mem-mesh.context", context_args)
    
    assert "content" in result
    assert "isError" in result
    assert result["isError"] is True
    
    response_data = json.loads(result["content"][0]["text"])
    assert response_data["error"] == "MEMORY_NOT_FOUND"

@pytest.mark.asyncio
async def test_handle_stats_tool(mcp_tools, memory_service):
    """mem-mesh.stats 도구 테스트"""
    # 테스트용 메모리 추가
    await memory_service.create(
        content="Test memory for stats",
        project_id="test-project",
        category="task",
        source="test"
    )
    
    # 기본 통계 조회
    result = await mcp_tools.handle_tool_call("mem-mesh.stats", {})
    
    assert "content" in result
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    
    # JSON 파싱 확인
    import json
    stats_data = json.loads(result["content"][0]["text"])
    
    assert "total_memories" in stats_data
    assert "unique_projects" in stats_data
    assert "categories_breakdown" in stats_data
    assert "sources_breakdown" in stats_data
    assert "projects_breakdown" in stats_data
    assert "query_time_ms" in stats_data
    
    assert stats_data["total_memories"] >= 1
    assert isinstance(stats_data["query_time_ms"], (int, float))


@pytest.mark.asyncio
async def test_handle_stats_tool_with_filters(mcp_tools, memory_service):
    """mem-mesh.stats 도구 필터링 테스트"""
    # 테스트용 메모리 추가
    await memory_service.create(
        content="Test memory for filtered stats",
        project_id="filter-project",
        category="bug",
        source="test"
    )
    
    # 프로젝트 필터링
    result = await mcp_tools.handle_tool_call("mem-mesh.stats", {
        "project_id": "filter-project"
    })
    
    assert "content" in result
    
    import json
    stats_data = json.loads(result["content"][0]["text"])
    
    assert stats_data["total_memories"] >= 1
    assert stats_data["unique_projects"] == 1


@pytest.mark.asyncio
async def test_handle_stats_tool_invalid_params(mcp_tools):
    """mem-mesh.stats 도구 잘못된 파라미터 테스트"""
    result = await mcp_tools.handle_tool_call("mem-mesh.stats", {
        "start_date": "invalid-date"
    })
    
    assert result.get("isError") is True
    assert "content" in result