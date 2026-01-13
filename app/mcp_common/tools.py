"""
MCP Tool Handlers - MCP 서버들이 공유하는 Tool 비즈니스 로직.

이 모듈은 storage 의존성을 주입받아 동작하므로,
FastMCP와 Pure MCP 모두에서 사용할 수 있습니다.
"""

from typing import Optional, List, Dict, Any
from ..core.storage.base import StorageBackend
from ..core.schemas.requests import AddParams, SearchParams, UpdateParams, StatsParams
from ..core.utils.logger import get_logger

logger = get_logger("mcp-tools")


class MCPToolHandlers:
    """MCP Tool 핸들러 클래스
    
    Storage 백엔드를 주입받아 모든 MCP tool 로직을 처리합니다.
    """
    
    def __init__(self, storage: StorageBackend):
        """
        Args:
            storage: 초기화된 StorageBackend 인스턴스
        """
        self._storage = storage
    
    @property
    def storage(self) -> StorageBackend:
        return self._storage
    
    async def add(
        self,
        content: str,
        project_id: Optional[str] = None,
        category: str = "task",
        source: str = "mcp",
        tags: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Add a new memory to the memory store
        
        Args:
            content: Memory content (10-10000 characters)
            project_id: Project identifier (optional)
            category: Memory category (task, bug, idea, decision, incident, code_snippet, git-history)
            source: Memory source
            tags: Memory tags
            
        Returns:
            dict: 생성된 메모리 정보
        """
        logger.info(
            "Tool add called",
            project_id=project_id,
            category=category,
            content_length=len(content)
        )
        
        try:
            params = AddParams(
                content=content,
                project_id=project_id,
                category=category,
                source=source,
                tags=tags
            )
            result = await self._storage.add_memory(params)
            logger.info("Successfully added memory", memory_id=result.id)
            return result.model_dump()
        except Exception as e:
            logger.error("Error in add", error=str(e))
            raise
    
    async def search(
        self,
        query: str,
        project_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 5,
        recency_weight: float = 0.0
    ) -> Dict[str, Any]:
        """Search memories using hybrid search (vector + metadata)
        
        Args:
            query: Search query (min 3 characters)
            project_id: Project filter
            category: Category filter
            limit: Maximum results (1-20)
            recency_weight: Recency weight (0.0-1.0)
            
        Returns:
            dict: 검색 결과
        """
        logger.info(
            "Tool search called",
            query=query,
            project_id=project_id,
            category=category,
            limit=limit
        )
        
        try:
            params = SearchParams(
                query=query,
                project_id=project_id,
                category=category,
                limit=limit,
                recency_weight=recency_weight
            )
            result = await self._storage.search_memories(params)
            logger.info("Search completed", result_count=len(result.memories))
            return result.model_dump()
        except Exception as e:
            logger.error("Error in search", error=str(e))
            raise
    
    async def context(
        self,
        memory_id: str,
        depth: int = 2,
        project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get context around a specific memory
        
        Args:
            memory_id: Memory ID to get context for
            depth: Search depth (1-5)
            project_id: Project filter
            
        Returns:
            dict: 컨텍스트 정보
        """
        logger.info(
            "Tool context called",
            memory_id=memory_id,
            depth=depth,
            project_id=project_id
        )
        
        try:
            result = await self._storage.get_context(memory_id, depth, project_id)
            logger.info("Context retrieved", memory_count=len(result.memories))
            return result.model_dump()
        except Exception as e:
            logger.error("Error in context", error=str(e))
            raise
    
    async def update(
        self,
        memory_id: str,
        content: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Update an existing memory
        
        Args:
            memory_id: Memory ID to update
            content: New content
            category: New category
            tags: New tags
            
        Returns:
            dict: 업데이트된 메모리 정보
        """
        logger.info(
            "Tool update called",
            memory_id=memory_id,
            has_content=content is not None,
            category=category
        )
        
        try:
            params = UpdateParams(content=content, category=category, tags=tags)
            result = await self._storage.update_memory(memory_id, params)
            logger.info("Successfully updated memory", memory_id=memory_id)
            return result.model_dump()
        except Exception as e:
            logger.error("Error in update", error=str(e))
            raise
    
    async def delete(self, memory_id: str) -> Dict[str, Any]:
        """Delete a memory from the store
        
        Args:
            memory_id: Memory ID to delete
            
        Returns:
            dict: 삭제 결과
        """
        logger.info("Tool delete called", memory_id=memory_id)
        
        try:
            result = await self._storage.delete_memory(memory_id)
            logger.info("Successfully deleted memory", memory_id=memory_id)
            return result.model_dump()
        except Exception as e:
            logger.error("Error in delete", error=str(e))
            raise
    
    async def stats(
        self,
        project_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get statistics about stored memories
        
        Args:
            project_id: Project filter
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
            
        Returns:
            dict: 통계 정보
        """
        logger.info(
            "Tool stats called",
            project_id=project_id,
            start_date=start_date,
            end_date=end_date
        )
        
        try:
            params = StatsParams(
                project_id=project_id,
                start_date=start_date,
                end_date=end_date
            )
            result = await self._storage.get_stats(params)
            logger.info("Stats retrieved", total_memories=result.total_memories)
            return result.model_dump()
        except Exception as e:
            logger.error("Error in stats", error=str(e))
            raise
