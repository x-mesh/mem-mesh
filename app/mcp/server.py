"""FastMCP 기반 MCP 서버 구현"""
from fastmcp import FastMCP
from typing import Optional
from ..core.config import Settings
from ..core.storage.base import StorageBackend
from ..core.storage.direct import DirectStorageBackend
from ..core.storage.api import APIStorageBackend

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
    
    if settings.storage_mode == "direct":
        storage = DirectStorageBackend(settings.database_path)
    else:
        storage = APIStorageBackend(settings.api_base_url)
    
    await storage.initialize()

async def shutdown_storage() -> None:
    """스토리지 백엔드 종료"""
    global storage
    if storage:
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
        category: Memory category (task, bug, idea, decision, incident, code_snippet)
        source: Memory source
        tags: Memory tags
    """
    from ..core.schemas.requests import AddParams
    
    if storage is None:
        raise RuntimeError("Storage not initialized. Call initialize_storage() first.")
    
    params = AddParams(
        content=content,
        project_id=project_id,
        category=category,
        source=source,
        tags=tags
    )
    result = await storage.add_memory(params)
    return result.model_dump()


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
    from ..core.schemas.requests import SearchParams
    
    if storage is None:
        raise RuntimeError("Storage not initialized. Call initialize_storage() first.")
    
    params = SearchParams(
        query=query,
        project_id=project_id,
        category=category,
        limit=limit,
        recency_weight=recency_weight
    )
    result = await storage.search_memories(params)
    return result.model_dump()


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
    if storage is None:
        raise RuntimeError("Storage not initialized. Call initialize_storage() first.")
    
    result = await storage.get_context(memory_id, depth, project_id)
    return result.model_dump()


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
    from ..core.schemas.requests import UpdateParams
    
    if storage is None:
        raise RuntimeError("Storage not initialized. Call initialize_storage() first.")
    
    params = UpdateParams(content=content, category=category, tags=tags)
    result = await storage.update_memory(memory_id, params)
    return result.model_dump()


@mcp.tool()
async def delete(memory_id: str) -> dict:
    """Delete a memory from the store
    
    Args:
        memory_id: Memory ID to delete
    """
    if storage is None:
        raise RuntimeError("Storage not initialized. Call initialize_storage() first.")
    
    result = await storage.delete_memory(memory_id)
    return result.model_dump()


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
    from ..core.schemas.requests import StatsParams
    
    if storage is None:
        raise RuntimeError("Storage not initialized. Call initialize_storage() first.")
    
    params = StatsParams(
        project_id=project_id,
        start_date=start_date,
        end_date=end_date
    )
    result = await storage.get_stats(params)
    return result.model_dump()