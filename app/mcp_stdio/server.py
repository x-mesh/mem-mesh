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
from ..mcp_common.batch_tools import BatchOperationHandler
from ..core.services.cache_manager import get_cache_manager

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
batch_handler: Optional[BatchOperationHandler] = None
cache_manager = get_cache_manager()  # 캐시 매니저 초기화


async def initialize_storage(settings: Optional[Settings] = None) -> None:
    """스토리지 백엔드 초기화"""
    global tool_handlers, batch_handler

    storage = await storage_manager.initialize(settings)
    tool_handlers = MCPToolHandlers(storage)

    # 배치 핸들러 초기화
    from ..core.database.base import Database
    from ..core.embeddings.service import EmbeddingService
    from ..core.services.memory import MemoryService
    from ..core.services.search import SearchService

    db = Database()
    embedding_service = EmbeddingService(preload=False)
    memory_service = MemoryService(db, embedding_service)
    search_service = SearchService(db, embedding_service)

    batch_handler = BatchOperationHandler(
        memory_service=memory_service,
        search_service=search_service,
        embedding_service=embedding_service,
        db=db
    )

    logger.info("Tool handlers and batch operations initialized with caching")


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


@mcp.tool()
async def batch_add_memories(
    contents: list[str],
    project_id: Optional[str] = None,
    category: str = "task",
    source: str = "mcp_batch",
    tags: Optional[list[str]] = None
) -> dict:
    """Batch add multiple memories with optimized embedding generation

    Args:
        contents: List of memory contents to add
        project_id: Project identifier for all memories
        category: Category for all memories
        source: Source for all memories
        tags: Tags for all memories

    Returns:
        Dictionary with batch operation results and token savings
    """
    if batch_handler is None:
        return {"status": "error", "message": "Batch handler not initialized"}

    return await batch_handler.batch_add_memories(
        contents=contents,
        project_id=project_id,
        category=category,
        source=source,
        tags=tags
    )


@mcp.tool()
async def batch_search(
    queries: list[str],
    project_id: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 5
) -> dict:
    """Batch search multiple queries with caching optimization

    Args:
        queries: List of search queries
        project_id: Project filter for all queries
        category: Category filter for all queries
        limit: Maximum results per query (1-20)

    Returns:
        Dictionary with search results for each query and cache statistics
    """
    if batch_handler is None:
        return {"status": "error", "message": "Batch handler not initialized"}

    return await batch_handler.batch_search(
        queries=queries,
        project_id=project_id,
        category=category,
        limit=limit
    )


@mcp.tool()
async def batch_operations(operations: list[dict]) -> dict:
    """Execute multiple mixed operations in batch for maximum efficiency

    Args:
        operations: List of operation dictionaries with 'type' and parameters
                   Supported types: 'add', 'search'
                   Example: [
                       {"type": "add", "content": "Task content"},
                       {"type": "search", "query": "bug fix"}
                   ]

    Returns:
        Dictionary with results for each operation and total token savings
    """
    if batch_handler is None:
        return {"status": "error", "message": "Batch handler not initialized"}

    return await batch_handler.batch_operations(operations=operations)


@mcp.tool()
async def cache_stats() -> dict:
    """Get cache statistics and performance metrics

    Returns:
        Dictionary with cache hit rates, token savings, and memory usage
    """
    stats = cache_manager.get_cache_stats()

    return {
        "status": "success",
        "cache_stats": stats,
        "message": f"Total tokens saved: {stats['total_tokens_saved']} (~${stats['estimated_cost_saved']:.4f})"
    }


@mcp.tool()
async def clear_cache(cache_type: Optional[str] = None) -> dict:
    """Clear cache to free memory or reset state

    Args:
        cache_type: Specific cache to clear ('embedding', 'search', 'context')
                   If None, clears all caches

    Returns:
        Dictionary with clear operation status
    """
    if cache_type:
        # Clear specific cache
        if cache_type == "embedding":
            cache_manager.embedding_cache.clear()
        elif cache_type == "search":
            cache_manager.search_cache.clear()
        elif cache_type == "context":
            cache_manager.context_cache.clear()
        else:
            return {"status": "error", "message": f"Unknown cache type: {cache_type}"}

        return {"status": "success", "message": f"Cleared {cache_type} cache"}
    else:
        # Clear all caches
        cache_manager.clear_all_caches()
        return {"status": "success", "message": "All caches cleared"}
