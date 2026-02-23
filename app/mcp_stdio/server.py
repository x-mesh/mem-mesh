"""FastMCP 기반 MCP 서버 구현

mcp_common 모듈을 사용하여 공통 로직을 공유합니다.

IMPORTANT: Tool parameter signatures here must stay in sync with
app/mcp_common/schemas.py. FastMCP uses @mcp.tool() decorators which
define schemas independently from the shared JSON schemas used by
SSE and Pure stdio servers. When adding/changing tool parameters,
update BOTH this file AND schemas.py to prevent drift.

Shared tools (16): add, search, context, update, delete, stats,
    pin_add, pin_complete, pin_promote, session_resume, session_end,
    batch_operations, link, unlink, get_links, weekly_review
FastMCP-only (2): cache_stats, clear_cache
"""

import os
from fastmcp import FastMCP
from typing import Optional, Union
from ..core.config import Settings
from ..core.utils.logger import get_logger, setup_logging
from ..mcp_common.storage import StorageManager
from ..mcp_common.tools import MCPToolHandlers
from ..mcp_common.batch_tools import BatchOperationHandler
from ..core.services.cache_manager import get_cache_manager

# 로깅 시스템 초기화
setup_logging()
logger = get_logger("mcp-stdio-server")

log_level = os.getenv("MEM_MESH_LOG_LEVEL") or os.getenv("MCP_LOG_LEVEL", "INFO")
log_file = os.getenv("MEM_MESH_LOG_FILE") or os.getenv("MCP_LOG_FILE", "")

logger.info(
    "Starting mem-mesh MCP server (FastMCP)",
    log_level=log_level,
    log_file=log_file if log_file else "console_only",
)

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
    from ..core.services.legacy.search import SearchService

    batch_settings = settings or Settings()
    db = Database(batch_settings.database_path)
    await db.connect()
    embedding_service = EmbeddingService(preload=False)
    memory_service = MemoryService(db, embedding_service)
    search_service = SearchService(db, embedding_service)

    batch_handler = BatchOperationHandler(
        memory_service=memory_service,
        search_service=search_service,
        embedding_service=embedding_service,
        db=db,
    )

    logger.info("Tool handlers and batch operations initialized with caching")


async def shutdown_storage() -> None:
    """스토리지 백엔드 종료"""
    global tool_handlers, batch_handler
    await storage_manager.shutdown()
    if batch_handler is not None:
        try:
            if hasattr(batch_handler, 'db') and batch_handler.db is not None:
                await batch_handler.db.disconnect()
        except Exception as e:
            logger.warning("Error closing batch handler DB", error=str(e))
        batch_handler = None
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
    tags: Optional[list[str]] = None,
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
    recency_weight: float = 0.0,
    response_format: str = "standard",
) -> dict:
    """Search memories using hybrid search (vector + metadata)

    Args:
        query: Search query (min 3 characters)
        project_id: Project filter
        category: Category filter
        limit: Maximum results (1-20)
        recency_weight: Recency weight (0.0-1.0)
        response_format: Response format (minimal/compact/standard/full)
    """
    return await _get_handlers().search(
        query, project_id, category, limit, recency_weight, response_format
    )


@mcp.tool()
async def context(
    memory_id: str,
    depth: int = 2,
    project_id: Optional[str] = None,
    response_format: str = "standard",
) -> dict:
    """Get context around a specific memory

    Args:
        memory_id: Memory ID to get context for
        depth: Search depth (1-5)
        project_id: Project filter
        response_format: Response format (compact/standard/full)
    """
    return await _get_handlers().context(memory_id, depth, project_id, response_format)


@mcp.tool()
async def update(
    memory_id: str,
    content: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[list[str]] = None,
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
    end_date: Optional[str] = None,
) -> dict:
    """Get statistics about stored memories

    Args:
        project_id: Project filter
        start_date: Start date filter (YYYY-MM-DD)
        end_date: End date filter (YYYY-MM-DD)
    """
    return await _get_handlers().stats(project_id, start_date, end_date)


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
async def pin_add(
    content: str,
    project_id: str,
    importance: Optional[int] = None,
    tags: Optional[list[str]] = None,
) -> dict:
    """Add a new pin (short-term task) to the current session

    Args:
        content: Pin content describing the task or work item
        project_id: Project identifier
        importance: Importance score (1-5). Auto-determined if not provided.
        tags: Pin tags
    """
    return await _get_handlers().pin_add(content, project_id, importance, tags)


@mcp.tool()
async def pin_complete(pin_id: str) -> dict:
    """Mark a pin as completed. Returns promotion suggestion if importance >= 4.

    Args:
        pin_id: Pin ID to complete
    """
    return await _get_handlers().pin_complete(pin_id)


@mcp.tool()
async def pin_promote(pin_id: str) -> dict:
    """Promote a completed pin to a permanent memory.

    Args:
        pin_id: Pin ID to promote to memory
    """
    return await _get_handlers().pin_promote(pin_id)


@mcp.tool()
async def session_resume(
    project_id: str,
    expand: Union[bool, str] = False,
    limit: int = 10,
) -> dict:
    """Resume the last session for a project. Returns active pins and session context.

    Args:
        project_id: Project identifier
        expand: false=compact, true=full, "smart"=full for open/in_progress only (recommended)
        limit: Maximum number of pins to return
    """
    return await _get_handlers().session_resume(project_id, expand, limit)


@mcp.tool()
async def session_end(
    project_id: str,
    summary: Optional[str] = None,
) -> dict:
    """End the current session for a project.

    Args:
        project_id: Project identifier
        summary: Session summary (auto-generated if not provided)
    """
    return await _get_handlers().session_end(project_id, summary)


@mcp.tool()
async def link(
    source_id: str,
    target_id: str,
    relation_type: str = "related",
    strength: float = 1.0,
    metadata: Optional[dict] = None,
) -> dict:
    """Create a relation between two memories.

    Args:
        source_id: Source memory ID
        target_id: Target memory ID
        relation_type: Relation type (related, parent, child, supersedes, references, depends_on, similar)
        strength: Relation strength (0.0-1.0)
        metadata: Optional metadata for the relation
    """
    return await _get_handlers().link(source_id, target_id, relation_type, strength, metadata)


@mcp.tool()
async def unlink(
    source_id: str,
    target_id: str,
    relation_type: Optional[str] = None,
) -> dict:
    """Remove a relation between two memories.

    Args:
        source_id: Source memory ID
        target_id: Target memory ID
        relation_type: Specific relation type to remove (optional, removes all if not specified)
    """
    return await _get_handlers().unlink(source_id, target_id, relation_type)


@mcp.tool()
async def get_links(
    memory_id: str,
    relation_type: Optional[str] = None,
    direction: str = "both",
    limit: int = 20,
) -> dict:
    """Get relations for a memory.

    Args:
        memory_id: Memory ID to get relations for
        relation_type: Filter by relation type (optional)
        direction: Relation direction filter (outgoing, incoming, both)
        limit: Maximum relations to return
    """
    return await _get_handlers().get_links(memory_id, relation_type, direction, limit)


@mcp.tool()
async def weekly_review(
    project_id: str,
    days: int = 7,
) -> dict:
    """Generate a weekly review report for a project.

    Returns incomplete pins, recent memories, session summaries,
    zero-result searches, and recommendations.

    Args:
        project_id: Project identifier
        days: Number of days to review (default: 7)
    """
    return await _get_handlers().weekly_review(project_id, days)


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
        "message": f"Total tokens saved: {stats['total_tokens_saved']} (~${stats['estimated_cost_saved']:.4f})",
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
