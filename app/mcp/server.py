"""FastMCP 기반 MCP 서버 구현"""
import os
from fastmcp import FastMCP
from typing import Optional
from ..core.config import Settings
from ..core.storage.base import StorageBackend
from ..core.storage.direct import DirectStorageBackend
from ..core.storage.api import APIStorageBackend
from ..core.utils.logger import get_logger, setup_logging

# 로깅 시스템 초기화
setup_logging()
logger = get_logger("mcp-server")

log_level = os.getenv("MCP_LOG_LEVEL", "INFO")
log_file = os.getenv("MCP_LOG_FILE", "")

logger.info("Starting mem-mesh MCP server", 
           log_level=log_level,
           log_file=log_file if log_file else "console_only")

# FastMCP 서버 인스턴스 생성
mcp = FastMCP("mem-mesh")

# 전역 스토리지 백엔드
storage: Optional[StorageBackend] = None

async def initialize_storage(settings: Optional[Settings] = None) -> None:
    """스토리지 백엔드 초기화
    
    Args:
        settings: 설정 객체. None이면 기본 설정 사용
    """
    global storage
    
    if settings is None:
        settings = Settings()
    
    logger.info("Initializing storage backend", storage_mode=settings.storage_mode)
    
    try:
        if settings.storage_mode == "direct":
            storage = DirectStorageBackend(settings.database_path)
            logger.info("Using DirectStorageBackend", database_path=settings.database_path)
        else:
            storage = APIStorageBackend(settings.api_base_url)
            logger.info("Using APIStorageBackend", api_base_url=settings.api_base_url)
        
        await storage.initialize()
        logger.info("Storage backend initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize storage", error=str(e), error_type=type(e).__name__)
        raise

async def shutdown_storage() -> None:
    """스토리지 백엔드 종료"""
    global storage
    if storage:
        logger.info("Shutting down storage backend")
        await storage.shutdown()
        storage = None


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
    logger.info(f"MCP add called: project_id={project_id}, category={category}, content_length={len(content)}")
    
    from ..core.schemas.requests import AddParams
    
    if storage is None:
        logger.error("Storage not initialized when calling add")
        raise RuntimeError("Storage not initialized. Call initialize_storage() first.")
    
    try:
        params = AddParams(
            content=content,
            project_id=project_id,
            category=category,
            source=source,
            tags=tags
        )
        logger.debug(f"Created AddParams: {params}")
        
        result = await storage.add_memory(params)
        logger.info(f"Successfully added memory with ID: {result.id}")
        return result.model_dump()
    except Exception as e:
        logger.error(f"Error in add: {e}")
        raise


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
    logger.info(f"MCP search called: query='{query}', project_id={project_id}, category={category}, limit={limit}")
    
    from ..core.schemas.requests import SearchParams
    
    if storage is None:
        logger.error("Storage not initialized when calling search")
        raise RuntimeError("Storage not initialized. Call initialize_storage() first.")
    
    try:
        params = SearchParams(
            query=query,
            project_id=project_id,
            category=category,
            limit=limit,
            recency_weight=recency_weight
        )
        logger.debug(f"Created SearchParams: {params}")
        
        result = await storage.search_memories(params)
        logger.info(f"Search returned {len(result.memories)} results")
        return result.model_dump()
    except Exception as e:
        logger.error(f"Error in search: {e}")
        raise


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
    logger.info(f"MCP context called: memory_id={memory_id}, depth={depth}, project_id={project_id}")
    
    if storage is None:
        logger.error("Storage not initialized when calling context")
        raise RuntimeError("Storage not initialized. Call initialize_storage() first.")
    
    try:
        result = await storage.get_context(memory_id, depth, project_id)
        logger.info(f"Context returned {len(result.memories)} memories")
        return result.model_dump()
    except Exception as e:
        logger.error(f"Error in context: {e}")
        raise


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
    logger.info(f"MCP update called: memory_id={memory_id}, has_content={content is not None}, category={category}")
    
    from ..core.schemas.requests import UpdateParams
    
    if storage is None:
        logger.error("Storage not initialized when calling update")
        raise RuntimeError("Storage not initialized. Call initialize_storage() first.")
    
    try:
        params = UpdateParams(content=content, category=category, tags=tags)
        logger.debug(f"Created UpdateParams: {params}")
        
        result = await storage.update_memory(memory_id, params)
        logger.info(f"Successfully updated memory {memory_id}")
        return result.model_dump()
    except Exception as e:
        logger.error(f"Error in update: {e}")
        raise


@mcp.tool()
async def delete(memory_id: str) -> dict:
    """Delete a memory from the store
    
    Args:
        memory_id: Memory ID to delete
    """
    logger.info(f"MCP delete called: memory_id={memory_id}")
    
    if storage is None:
        logger.error("Storage not initialized when calling delete")
        raise RuntimeError("Storage not initialized. Call initialize_storage() first.")
    
    try:
        result = await storage.delete_memory(memory_id)
        logger.info(f"Successfully deleted memory {memory_id}")
        return result.model_dump()
    except Exception as e:
        logger.error(f"Error in delete: {e}")
        raise


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
    logger.info(f"MCP stats called: project_id={project_id}, start_date={start_date}, end_date={end_date}")
    
    from ..core.schemas.requests import StatsParams
    
    if storage is None:
        logger.error("Storage not initialized when calling stats")
        raise RuntimeError("Storage not initialized. Call initialize_storage() first.")
    
    try:
        params = StatsParams(
            project_id=project_id,
            start_date=start_date,
            end_date=end_date
        )
        logger.debug(f"Created StatsParams: {params}")
        
        result = await storage.get_stats(params)
        logger.info(f"Stats returned: {result.total_memories} total memories")
        return result.model_dump()
    except Exception as e:
        logger.error(f"Error in stats: {e}")
        raise