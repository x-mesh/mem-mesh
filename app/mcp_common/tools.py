"""
MCP Tool Handlers - MCP 서버들이 공유하는 Tool 비즈니스 로직.

이 모듈은 storage 의존성을 주입받아 동작하므로,
FastMCP와 Pure MCP 모두에서 사용할 수 있습니다.
"""

from typing import Optional, List, Dict, Any, TYPE_CHECKING
from ..core.storage.base import StorageBackend
from ..core.schemas.requests import AddParams, SearchParams, UpdateParams, StatsParams
from ..core.utils.logger import get_logger
from .prompt_optimizer import PromptOptimizer

if TYPE_CHECKING:
    from ..web.websocket.realtime import RealtimeNotifier
    from ..core.database.base import Database

logger = get_logger("mcp-tools")


class MCPToolHandlers:
    """MCP Tool 핸들러 클래스
    
    Storage 백엔드를 주입받아 모든 MCP tool 로직을 처리합니다.
    """
    
    def __init__(
        self, 
        storage: StorageBackend, 
        notifier: Optional["RealtimeNotifier"] = None,
        enable_compression: bool = True
    ):
        """
        Args:
            storage: 초기화된 StorageBackend 인스턴스
            notifier: 실시간 알림 발송자 (선택사항)
            enable_compression: 응답 압축 활성화 (기본값: True)
        """
        self._storage = storage
        self._notifier = notifier
        self._enable_compression = enable_compression
        self._optimizer = PromptOptimizer() if enable_compression else None
    
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
        logger.info_with_details(
            "Tool add called",
            details={"content": content, "tags": tags, "source": source},
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
            
            # 실시간 알림 전송 - 완전한 메모리 데이터 조회 후 전송
            logger.debug(f"Checking notifier: {self._notifier is not None}")
            if self._notifier:
                try:
                    # 생성된 메모리의 완전한 데이터 조회 (MemoryService 사용)
                    has_memory_service = hasattr(self._storage, 'memory_service') and self._storage.memory_service
                    logger.debug(f"Has memory_service: {has_memory_service}")
                    if has_memory_service:
                        memory = await self._storage.memory_service.get(result.id)
                        logger.debug(f"Retrieved memory for notification: {memory is not None}")
                        if memory:
                            import json
                            memory_data = {
                                "id": memory.id,
                                "content": memory.content,
                                "project_id": memory.project_id,
                                "category": memory.category,
                                "tags": json.loads(memory.tags) if memory.tags else [],
                                "source": memory.source,
                                "created_at": memory.created_at,
                                "updated_at": memory.updated_at
                            }
                            await self._notifier.notify_memory_created(memory_data)
                except Exception as e:
                    logger.warning(f"Failed to send realtime notification: {e}")
            
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
        recency_weight: float = 0.0,
        response_format: str = "standard",
        enable_noise_filter: bool = True
    ) -> Dict[str, Any]:
        """Search memories using hybrid search (vector + metadata)
        
        Args:
            query: Search query (min 3 characters)
            project_id: Project filter
            category: Category filter
            limit: Maximum results (1-20)
            recency_weight: Recency weight (0.0-1.0)
            response_format: Response format (minimal/compact/standard/full)
            enable_noise_filter: Enable noise filtering (default: True)
            
        Returns:
            dict: 검색 결과 (압축 가능)
        """
        logger.info_with_details(
            "Tool search called",
            details={"query_text": query, "recency_weight": recency_weight, "format": response_format, "noise_filter": enable_noise_filter},
            project_id=project_id,
            category=category,
            limit=limit,
            query_length=len(query) if query else 0
        )
        
        try:
            params = SearchParams(
                query=query,
                project_id=project_id,
                category=category,
                limit=limit * 2 if enable_noise_filter else limit,  # 필터링 고려하여 더 많이 가져옴
                recency_weight=recency_weight
            )
            result = await self._storage.search_memories(params)
            
            # 노이즈 필터 적용
            if enable_noise_filter and result.results:
                from ..core.services.noise_filter import SmartSearchFilter
                filter_service = SmartSearchFilter()
                context = {
                    'project': project_id,
                    'max_results': limit,
                    'aggressive_filter': False
                }
                result = filter_service.apply(result, query, context)
            
            logger.info("Search completed", result_count=len(result.results), filtered=enable_noise_filter)
            
            # 응답 압축 (활성화된 경우)
            if self._enable_compression and self._optimizer and response_format != "full":
                return self._compress_search_response(result, response_format)
            
            return result.model_dump()
        except Exception as e:
            logger.error("Error in search", error=str(e))
            raise
    
    def _compress_search_response(
        self, 
        result: Any, 
        format: str = "standard"
    ) -> Dict[str, Any]:
        """검색 결과 압축"""
        results_list = [
            {
                "id": r.id,
                "content": r.content,
                "category": r.category,
                "similarity_score": r.similarity_score,
                "created_at": r.created_at,
                "project_id": r.project_id,
                "tags": r.tags
            }
            for r in result.results
        ]
        
        if format == "minimal":
            # 극도 압축: ID와 점수만
            compressed_results = [
                {"id": r["id"][:8], "score": round(r["similarity_score"], 2)}
                for r in results_list
            ]
        elif format == "compact":
            # 압축: ID, 카테고리, 요약
            compressed_results = [
                {
                    "id": r["id"][:8],
                    "category": r["category"],
                    "summary": r["content"][:80] + "..." if len(r["content"]) > 80 else r["content"],
                    "score": round(r["similarity_score"], 2)
                }
                for r in results_list
            ]
        else:  # standard
            # 표준: 전체 내용 포함하되 구조화
            compressed_results = results_list
        
        return {
            "results": compressed_results,
            "total": len(compressed_results),
            "format": format,
            "compressed": True
        }
    
    async def context(
        self,
        memory_id: str,
        depth: int = 2,
        project_id: Optional[str] = None,
        response_format: str = "standard"
    ) -> Dict[str, Any]:
        """Get context around a specific memory
        
        Args:
            memory_id: Memory ID to get context for
            depth: Search depth (1-5)
            project_id: Project filter
            response_format: Response format (compact/standard/full)
            
        Returns:
            dict: 컨텍스트 정보 (압축 가능)
        """
        logger.info(
            "Tool context called",
            memory_id=memory_id,
            depth=depth,
            project_id=project_id,
            format=response_format
        )
        
        try:
            result = await self._storage.get_context(memory_id, depth, project_id)
            logger.info("Context retrieved", memory_count=len(result.related_memories))
            
            # 응답 압축 (활성화된 경우)
            if self._enable_compression and self._optimizer and response_format == "compact":
                return self._compress_context_response(result)
            
            return result.model_dump()
        except Exception as e:
            logger.error("Error in context", error=str(e))
            raise
    
    def _compress_context_response(self, result: Any) -> Dict[str, Any]:
        """컨텍스트 응답 압축"""
        primary = result.memory if hasattr(result, 'memory') else {}
        related = result.related_memories if hasattr(result, 'related_memories') else []
        
        compressed = {
            "primary": {
                "id": primary.id[:8] if hasattr(primary, 'id') else "",
                "category": primary.category if hasattr(primary, 'category') else "",
                "summary": (primary.content[:100] + "...") if hasattr(primary, 'content') and len(primary.content) > 100 else (primary.content if hasattr(primary, 'content') else "")
            },
            "related_count": len(related),
            "related": [
                {
                    "id": r.id[:8] if hasattr(r, 'id') else "",
                    "cat": r.category[:4] if hasattr(r, 'category') else "",
                    "score": round(r.similarity_score, 2) if hasattr(r, 'similarity_score') else 0,
                    "hint": (r.content[:40] + "...") if hasattr(r, 'content') and len(r.content) > 40 else (r.content if hasattr(r, 'content') else "")
                }
                for r in related[:5]  # 최대 5개만
            ],
            "compressed": True
        }
        
        return compressed
    
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
        logger.info_with_details(
            "Tool update called",
            details={"content": content, "tags": tags},
            memory_id=memory_id,
            has_content=content is not None,
            category=category,
            content_length=len(content) if content else 0
        )
        
        try:
            params = UpdateParams(content=content, category=category, tags=tags)
            result = await self._storage.update_memory(memory_id, params)
            logger.info("Successfully updated memory", memory_id=memory_id)
            
            # 실시간 알림 전송
            if self._notifier:
                try:
                    await self._notifier.notify_memory_updated(memory_id, result.model_dump())
                except Exception as e:
                    logger.warning(f"Failed to send realtime notification: {e}")
            
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
            # 삭제 전에 메모리 정보 가져오기 (프로젝트 ID 확인용)
            project_id = None
            if self._notifier:
                try:
                    # 메모리 정보 조회 (삭제 전)
                    memory_info = await self._storage.get_memory(memory_id)
                    project_id = memory_info.project_id if memory_info else None
                except Exception:
                    pass  # 조회 실패해도 삭제는 진행
            
            result = await self._storage.delete_memory(memory_id)
            logger.info("Successfully deleted memory", memory_id=memory_id)
            
            # 실시간 알림 전송
            if self._notifier:
                try:
                    await self._notifier.notify_memory_deleted(memory_id, project_id)
                except Exception as e:
                    logger.warning(f"Failed to send realtime notification: {e}")
            
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


    # ===== Work Tracking System Tools =====
    
    async def pin_add(
        self,
        content: str,
        project_id: str,
        importance: Optional[int] = None,
        tags: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Add a new pin (short-term task) to the current session
        
        Args:
            content: Pin content
            project_id: Project identifier
            importance: Importance score (1-5, auto-determined if not provided)
            tags: Pin tags
            
        Returns:
            dict: Created pin information
        """
        logger.info_with_details(
            "Tool pin_add called",
            details={"content": content, "tags": tags},
            project_id=project_id,
            importance=importance
        )
        
        try:
            from ..core.services.pin import PinService
            
            db = self._get_database()
            pin_service = PinService(db)
            
            result = await pin_service.create_pin(
                project_id=project_id,
                content=content,
                importance=importance,
                tags=tags
            )
            
            logger.info("Successfully added pin", pin_id=result.id)
            return result.model_dump()
        except Exception as e:
            logger.error("Error in pin_add", error=str(e))
            raise
    
    async def pin_complete(self, pin_id: str) -> Dict[str, Any]:
        """Mark a pin as completed
        
        Args:
            pin_id: Pin ID to complete
            
        Returns:
            dict: Completed pin information with promotion suggestion
        """
        logger.info("Tool pin_complete called", pin_id=pin_id)
        
        try:
            from ..core.services.pin import PinService, PinAlreadyCompletedError
            
            db = self._get_database()
            pin_service = PinService(db)
            
            try:
                result = await pin_service.complete_pin(pin_id)
            except PinAlreadyCompletedError:
                # 이미 완료된 Pin - 현재 상태 반환
                logger.info("Pin already completed, returning current state", pin_id=pin_id)
                result = await pin_service.get_pin(pin_id)
                if not result:
                    raise ValueError(f"Pin not found: {pin_id}")
            
            # 승격 제안 여부 확인
            suggest_promotion = pin_service.should_suggest_promotion(result)
            
            response = result.model_dump()
            response["suggest_promotion"] = suggest_promotion
            if suggest_promotion:
                response["promotion_message"] = (
                    f"이 Pin의 중요도가 {result.importance}점입니다. "
                    "Memory로 승격하시겠습니까? pin_promote 도구를 사용하세요."
                )
            
            logger.info("Successfully completed pin", pin_id=pin_id, suggest_promotion=suggest_promotion)
            return response
        except Exception as e:
            logger.error("Error in pin_complete", error=str(e))
            raise
    
    async def pin_promote(self, pin_id: str) -> Dict[str, Any]:
        """Promote a pin to a permanent memory
        
        Args:
            pin_id: Pin ID to promote
            
        Returns:
            dict: Promotion result with memory_id
        """
        logger.info("Tool pin_promote called", pin_id=pin_id)
        
        try:
            from ..core.services.pin import PinService
            
            db = self._get_database()
            pin_service = PinService(db)
            
            result = await pin_service.promote_to_memory(pin_id)
            
            logger.info("Successfully promoted pin to memory", pin_id=pin_id, memory_id=result["memory_id"])
            return result
        except Exception as e:
            logger.error("Error in pin_promote", error=str(e))
            raise
    
    async def session_resume(
        self,
        project_id: str,
        expand: bool = False,
        limit: int = 10
    ) -> Dict[str, Any]:
        """Resume the last session for a project
        
        Args:
            project_id: Project identifier
            expand: If True, return full pin contents; if False, return summary only
            limit: Maximum number of pins to return (default 10)
            
        Returns:
            dict: Session context with pins
        """
        logger.info(
            "Tool session_resume called",
            project_id=project_id,
            expand=expand,
            limit=limit
        )
        
        try:
            from ..core.services.session import SessionService
            
            db = self._get_database()
            session_service = SessionService(db)
            
            result = await session_service.resume_last_session(
                project_id=project_id,
                expand=expand,
                limit=limit
            )
            
            if result is None:
                return {
                    "status": "no_session",
                    "message": f"프로젝트 '{project_id}'에 활성 세션이 없습니다. pin_add로 새 작업을 시작하세요."
                }
            
            logger.info("Successfully resumed session", session_id=result.session_id)
            return result.model_dump()
        except Exception as e:
            logger.error("Error in session_resume", error=str(e))
            raise
    
    async def session_end(
        self,
        project_id: str,
        summary: Optional[str] = None
    ) -> Dict[str, Any]:
        """End the current session for a project
        
        Args:
            project_id: Project identifier
            summary: Session summary (auto-generated if not provided)
            
        Returns:
            dict: Ended session information
        """
        logger.info("Tool session_end called", project_id=project_id)
        
        try:
            from ..core.services.session import SessionService
            
            db = self._get_database()
            session_service = SessionService(db)
            
            # 현재 활성 세션 찾기
            sessions = await session_service.list_sessions(
                project_id=project_id,
                status="active",
                limit=1
            )
            
            if not sessions:
                return {
                    "status": "no_active_session",
                    "message": f"프로젝트 '{project_id}'에 활성 세션이 없습니다."
                }
            
            result = await session_service.end_session(
                session_id=sessions[0].id,
                summary=summary
            )
            
            logger.info("Successfully ended session", session_id=result.id)
            return result.model_dump()
        except Exception as e:
            logger.error("Error in session_end", error=str(e))
            raise
    
    def _get_database(self) -> "Database":
        """Storage에서 Database 인스턴스 가져오기"""
        # DirectStorageBackend의 경우 db 속성이 있음
        if hasattr(self._storage, 'db') and self._storage.db is not None:
            return self._storage.db
        
        # 다른 방법으로 database 접근 시도
        if hasattr(self._storage, '_db'):
            return self._storage._db
        
        raise RuntimeError("Cannot access database from storage backend")
