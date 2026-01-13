"""FastMCP 기반 MCP 서버 구현

mcp_common 모듈을 사용하여 공통 로직을 공유합니다.
"""
import os
from fastmcp import FastMCP
from typing import Optional
from ..core.config import Settings
from ..core.utils.logger import get_logger, setup_logging
from ..mcp_common.storage import StorageManager
from ..mcp_common.tools import MCPToolHandlers

# 로깅 시스템 초기화
setup_logging()
logger = get_logger("mcp-stdio-server")

log_level = os.getenv("MCP_LOG_LEVEL", "INFO")
log_file = os.getenv("MCP_LOG_FILE", "")

logger.info("Starting mem-mesh MCP server (FastMCP)", 
           log_level=log_level,
           log_file=log_file if log_file else "console_only")

# FastMCP 서버 인스턴스 생성
mcp = FastMCP("mem-mesh")

# 스토리지 매니저와 툴 핸들러
storage_manager = StorageManager()
tool_handlers: Optional[MCPToolHandlers] = None


async def initialize_storage(settings: Optional[Settings] = None) -> None:
    """스토리지 백엔드 초기화"""
    global tool_handlers
    
    storage = await storage_manager.initialize(settings)
    tool_handlers = MCPToolHandlers(storage)
    logger.info("Tool handlers initialized")


async def shutdown_storage() -> None:
    """스토리지 백엔드 종료"""
    global tool_handlers
    await storage_manager.shutdown()
    tool_handlers = None


def _get_handlers() -> MCPToolHandlers:
    """툴 핸들러 반환 (초기화 확인)"""
    if tool_handlers is None:
        raise RuntimeError("Storage not initialized. Call initialize_storage() first.")
    return tool_handlers


@mcp.tool()
async def add(
    content: str,
    project_id: Optional[str] = None,
    category: str = "task",
    source: str = "mcp",
    tags: Optional[list[str]] = None
) -> dict:
    """Add a new memory to the memory store
    
    Args:
        content: Memory content (10-10000 characters)
        project_id: Project identifier (optional)
        category: Memory category (task, bug, idea, decision, incident, code_snippet, git-history)
        source: Memory source
        tags: Memory tags
    """
    return await _get_handlers().add(content, project_id, category, source, tags)


@mcp.tool()
async def search(
    query: str,
    project_id: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 5,
    recency_weight: float = 0.0
) -> dict:
    """Search memories using hybrid search (vector + metadata)
    
    Args:
        query: Search query (min 3 characters)
        project_id: Project filter
        category: Category filter
        limit: Maximum results (1-20)
        recency_weight: Recency weight (0.0-1.0)
    """
    return await _get_handlers().search(query, project_id, category, limit, recency_weight)


@mcp.tool()
async def context(
    memory_id: str,
    depth: int = 2,
    project_id: Optional[str] = None
) -> dict:
    """Get context around a specific memory
    
    Args:
        memory_id: Memory ID to get context for
        depth: Search depth (1-5)
        project_id: Project filter
    """
    return await _get_handlers().context(memory_id, depth, project_id)


@mcp.tool()
async def update(
    memory_id: str,
    content: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[list[str]] = None
) -> dict:
    """Update an existing memory
    
    Args:
        memory_id: Memory ID to update
        content: New content
        category: New category
        tags: New tags
    """
    return await _get_handlers().update(memory_id, content, category, tags)


@mcp.tool()
async def delete(memory_id: str) -> dict:
    """Delete a memory from the store
    
    Args:
        memory_id: Memory ID to delete
    """
    return await _get_handlers().delete(memory_id)


@mcp.tool()
async def stats(
    project_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> dict:
    """Get statistics about stored memories
    
    Args:
        project_id: Project filter
        start_date: Start date filter (YYYY-MM-DD)
        end_date: End date filter (YYYY-MM-DD)
    """
    return await _get_handlers().stats(project_id, start_date, end_date)
