"""
MCP Tool Handlers - MCP 서버들이 공유하는 Tool 비즈니스 로직.

이 모듈은 storage 의존성을 주입받아 동작하므로,
FastMCP와 Pure MCP 모두에서 사용할 수 있습니다.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..core.schemas.requests import AddParams, SearchParams, StatsParams, UpdateParams
from ..core.storage.base import StorageBackend
from ..core.utils.logger import get_logger
from .prompt_optimizer import PromptOptimizer

if TYPE_CHECKING:
    from ..core.database.base import Database
    from ..web.websocket.realtime import RealtimeNotifier

logger = get_logger("mcp-tools")


class MCPToolHandlers:
    """MCP Tool 핸들러 클래스

    Storage 백엔드를 주입받아 모든 MCP tool 로직을 처리합니다.
    """

    def __init__(
        self,
        storage: StorageBackend,
        notifier: Optional["RealtimeNotifier"] = None,
        enable_compression: bool = True,
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
        client: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Add a new memory to the memory store

        Args:
            content: Memory content (10-10000 characters)
            project_id: Project identifier (optional)
            category: Memory category (task, bug, idea, decision, incident, code_snippet, git-history)
            source: Memory source
            client: Client tool name (cursor, kiro, claude_code, etc.)
            tags: Memory tags

        Returns:
            dict: 생성된 메모리 정보
        """
        logger.info_with_details(
            "Tool add called",
            details={"content": content, "tags": tags, "source": source, "client": client},
            project_id=project_id,
            category=category,
            content_length=len(content),
        )

        try:
            params = AddParams(
                content=content,
                project_id=project_id,
                category=category,
                source=source,
                client=client,
                tags=tags,
            )
            result = await self._storage.add_memory(params)
            logger.info("Successfully added memory", memory_id=result.id)

            # 실시간 알림 전송 - 완전한 메모리 데이터 조회 후 전송
            logger.debug(f"Checking notifier: {self._notifier is not None}")
            if self._notifier:
                try:
                    # 생성된 메모리의 완전한 데이터 조회 (MemoryService 사용)
                    has_memory_service = (
                        hasattr(self._storage, "memory_service")
                        and self._storage.memory_service
                    )
                    logger.debug(f"Has memory_service: {has_memory_service}")
                    if has_memory_service:
                        memory = await self._storage.memory_service.get(result.id)
                        logger.debug(
                            f"Retrieved memory for notification: {memory is not None}"
                        )
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
                                "updated_at": memory.updated_at,
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
        enable_noise_filter: bool = True,
        time_range: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        temporal_mode: str = "boost",
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
            time_range: Time range shortcut (today/this_week/this_month etc.)
            date_from: Start date (YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD)
            temporal_mode: Temporal mode (filter/boost/decay)

        Returns:
            dict: 검색 결과 (압축 가능)
        """
        logger.info_with_details(
            "Tool search called",
            details={
                "query_text": query,
                "recency_weight": recency_weight,
                "format": response_format,
                "noise_filter": enable_noise_filter,
                "time_range": time_range,
                "date_from": date_from,
                "date_to": date_to,
                "temporal_mode": temporal_mode,
            },
            project_id=project_id,
            category=category,
            limit=limit,
            query_length=len(query) if query else 0,
        )

        try:
            # 쿼리에서 한국어/영어 시간 표현 자동 추출
            if not time_range:
                from ..core.services.query_expander import extract_time_expression

                detected_range, cleaned_query = extract_time_expression(query)
                if detected_range:
                    time_range = detected_range
                    query = cleaned_query
                    logger.info(
                        f"Temporal expression detected: '{detected_range}' "
                        f"from query, cleaned: '{query}'"
                    )

            params = SearchParams(
                query=query,
                project_id=project_id,
                category=category,
                limit=(
                    limit * 2 if enable_noise_filter else limit
                ),  # 필터링 고려하여 더 많이 가져옴
                recency_weight=recency_weight,
                time_range=time_range,
                date_from=date_from,
                date_to=date_to,
                temporal_mode=temporal_mode,
            )
            result = await self._storage.search_memories(params)

            # 노이즈 필터 적용
            if enable_noise_filter and result.results:
                from ..core.services.noise_filter import SmartSearchFilter

                filter_service = SmartSearchFilter()
                context = {
                    "project": project_id,
                    "max_results": limit,
                    "aggressive_filter": False,
                }
                result = filter_service.apply(result, query, context)

            logger.info(
                "Search completed",
                result_count=len(result.results),
                filtered=enable_noise_filter,
            )

            # 응답 압축 (활성화된 경우)
            if (
                self._enable_compression
                and self._optimizer
                and response_format != "full"
            ):
                return self._compress_search_response(result, response_format)

            return result.model_dump()
        except Exception as e:
            logger.error("Error in search", error=str(e))
            raise

    def _compress_search_response(
        self, result: Any, format: str = "standard"
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
                "tags": r.tags,
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
                    "summary": (
                        r["content"][:80] + "..."
                        if len(r["content"]) > 80
                        else r["content"]
                    ),
                    "score": round(r["similarity_score"], 2),
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
            "compressed": True,
        }

    async def context(
        self,
        memory_id: str,
        depth: int = 2,
        project_id: Optional[str] = None,
        response_format: str = "standard",
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
            format=response_format,
        )

        try:
            result = await self._storage.get_context(memory_id, depth, project_id)
            logger.info("Context retrieved", memory_count=len(result.related_memories))

            # 응답 압축 (활성화된 경우)
            if (
                self._enable_compression
                and self._optimizer
                and response_format == "compact"
            ):
                return self._compress_context_response(result)

            return result.model_dump()
        except Exception as e:
            logger.error("Error in context", error=str(e))
            raise

    def _compress_context_response(self, result: Any) -> Dict[str, Any]:
        """컨텍스트 응답 압축"""
        primary = result.memory if hasattr(result, "memory") else {}
        related = result.related_memories if hasattr(result, "related_memories") else []

        compressed = {
            "primary": {
                "id": primary.id[:8] if hasattr(primary, "id") else "",
                "category": primary.category if hasattr(primary, "category") else "",
                "summary": (
                    (primary.content[:100] + "...")
                    if hasattr(primary, "content") and len(primary.content) > 100
                    else (primary.content if hasattr(primary, "content") else "")
                ),
            },
            "related_count": len(related),
            "related": [
                {
                    "id": r.id[:8] if hasattr(r, "id") else "",
                    "cat": r.category[:4] if hasattr(r, "category") else "",
                    "score": (
                        round(r.similarity_score, 2)
                        if hasattr(r, "similarity_score")
                        else 0
                    ),
                    "hint": (
                        (r.content[:40] + "...")
                        if hasattr(r, "content") and len(r.content) > 40
                        else (r.content if hasattr(r, "content") else "")
                    ),
                }
                for r in related[:5]  # 최대 5개만
            ],
            "compressed": True,
        }

        return compressed

    async def update(
        self,
        memory_id: str,
        content: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
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
            content_length=len(content) if content else 0,
        )

        try:
            params = UpdateParams(content=content, category=category, tags=tags)
            result = await self._storage.update_memory(memory_id, params)
            logger.info("Successfully updated memory", memory_id=memory_id)

            # 실시간 알림 전송
            if self._notifier:
                try:
                    await self._notifier.notify_memory_updated(
                        memory_id, result.model_dump()
                    )
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
        end_date: Optional[str] = None,
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
            end_date=end_date,
        )

        try:
            params = StatsParams(
                project_id=project_id, start_date=start_date, end_date=end_date
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
        tags: Optional[List[str]] = None,
        ide_session_id: Optional[str] = None,
        client_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a new pin (short-term task) to the current session

        Args:
            content: Pin content
            project_id: Project identifier
            importance: Importance score (1-5, auto-determined if not provided)
            tags: Pin tags
            ide_session_id: IDE native session ID. Optional.
            client_type: IDE/tool type. Optional.

        Returns:
            dict: Created pin information
        """
        logger.info_with_details(
            "Tool pin_add called",
            details={"content": content, "tags": tags},
            project_id=project_id,
            importance=importance,
        )

        try:
            from ..core.services.importance_analyzer import ImportanceAnalyzer
            from ..core.services.pin import PinService

            db = self._get_database()
            pin_service = PinService(
                db, getattr(self._storage, "embedding_service", None)
            )

            # importance가 명시되지 않으면 ImportanceAnalyzer로 자동 추정
            effective_importance = importance
            auto_importance = False

            if importance is None:
                analyzer = ImportanceAnalyzer()
                effective_importance = analyzer.analyze(content, tags)
                auto_importance = True
                logger.info(
                    f"Auto-determined importance: {effective_importance} for content: '{content[:50]}...'"
                )

            result = await pin_service.create_pin(
                project_id=project_id,
                content=content,
                importance=effective_importance,
                tags=tags,
                auto_importance=auto_importance,
                ide_session_id=ide_session_id,
                client_type=client_type,
            )

            response = result.model_dump()
            if auto_importance:
                response["importance_note"] = (
                    f"중요도가 자동으로 {effective_importance}점으로 설정되었습니다. "
                    "필요시 수정할 수 있습니다."
                )

            logger.info(
                "Successfully added pin",
                pin_id=result.id,
                importance=effective_importance,
                auto=auto_importance,
            )
            return response
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
            from ..core.services.pin import PinAlreadyCompletedError, PinService

            db = self._get_database()
            pin_service = PinService(
                db, getattr(self._storage, "embedding_service", None)
            )

            try:
                result = await pin_service.complete_pin(pin_id)
            except PinAlreadyCompletedError:
                # 이미 완료된 Pin - 현재 상태 반환
                logger.info(
                    "Pin already completed, returning current state", pin_id=pin_id
                )
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

            logger.info(
                "Successfully completed pin",
                pin_id=pin_id,
                suggest_promotion=suggest_promotion,
            )
            return response
        except Exception as e:
            logger.error("Error in pin_complete", error=str(e))
            raise

    async def pin_promote(self, pin_id: str, category: str = "task") -> Dict[str, Any]:
        """Promote a pin to a permanent memory

        Args:
            pin_id: Pin ID to promote
            category: Memory category (task, decision, bug, incident, idea, code_snippet)

        Returns:
            dict: Promotion result with memory_id
        """
        logger.info("Tool pin_promote called", pin_id=pin_id, category=category)

        try:
            from ..core.services.pin import PinService

            db = self._get_database()
            pin_service = PinService(
                db, getattr(self._storage, "embedding_service", None)
            )

            result = await pin_service.promote_to_memory(pin_id, category=category)

            logger.info(
                "Successfully promoted pin to memory",
                pin_id=pin_id,
                memory_id=result["memory_id"],
            )

            # 실시간 알림 전송 (pin → memory 승격)
            if self._notifier:
                try:
                    has_memory_service = (
                        hasattr(self._storage, "memory_service")
                        and self._storage.memory_service
                    )
                    if has_memory_service:
                        memory = await self._storage.memory_service.get(
                            result["memory_id"]
                        )
                        if memory:
                            import json as _json

                            memory_data = {
                                "id": memory.id,
                                "content": memory.content,
                                "project_id": memory.project_id,
                                "category": memory.category,
                                "tags": (
                                    _json.loads(memory.tags) if memory.tags else []
                                ),
                                "source": memory.source,
                                "created_at": memory.created_at,
                                "updated_at": memory.updated_at,
                            }
                            await self._notifier.notify_memory_created(memory_data)
                except Exception as e:
                    logger.warning(
                        f"Failed to send pin_promote realtime notification: {e}"
                    )

            return result
        except Exception as e:
            logger.error("Error in pin_promote", error=str(e))
            raise

    async def session_resume(
        self,
        project_id: str,
        expand: Any = False,
        limit: int = 10,
        ide_session_id: Optional[str] = None,
        client_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resume the last session for a project

        Args:
            project_id: Project identifier
            expand: false=compact, true=full, "smart"=4-tier matrix (status×importance, recommended)
            limit: Maximum number of pins to return (default 10)
            ide_session_id: IDE native session ID (e.g. Claude Code session_id). Optional.
            client_type: IDE/tool type (e.g. "claude-ai", "Cursor"). Optional.

        Returns:
            dict: Session context with pins and token tracking information
        """
        # expand 값 정규화: bool 또는 "smart"
        if isinstance(expand, str) and expand.lower() == "smart":
            normalized_expand = "smart"
        else:
            normalized_expand = bool(expand) if not isinstance(expand, bool) else expand

        logger.info(
            "Tool session_resume called",
            project_id=project_id,
            expand=normalized_expand,
            limit=limit,
        )

        try:
            from ..core.services.session import SessionService

            db = self._get_database()
            session_service = SessionService(db)

            # resume_with_token_tracking 메서드 사용
            session_context, token_info = (
                await session_service.resume_with_token_tracking(
                    project_id=project_id, expand=normalized_expand, limit=limit
                )
            )

            if session_context is None:
                return {
                    "status": "no_session",
                    "message": f"프로젝트 '{project_id}'에 활성 세션이 없습니다. pin_add로 새 작업을 시작하세요.",
                    "token_info": token_info,
                }

            # ide_session_id가 제공되었으면 활성 세션에 연결 (resume 이후)
            if ide_session_id:
                await session_service.get_or_create_active_session(
                    project_id=project_id,
                    ide_session_id=ide_session_id,
                    client_type=client_type,
                )

            # 세션 컨텍스트와 토큰 정보를 함께 반환
            response = session_context.model_dump()
            response["token_info"] = token_info

            # expand=false일 때 토큰 제한 경고 (smart 모드는 의도적이므로 제외)
            if normalized_expand is False and token_info["loaded_tokens"] > 100:
                response["token_warning"] = (
                    f"요약 모드에서 {token_info['loaded_tokens']} 토큰이 로드되었습니다. "
                    "100 토큰 이하를 권장합니다."
                )

            logger.info(
                "Successfully resumed session with token tracking",
                session_id=session_context.session_id,
                loaded_tokens=token_info["loaded_tokens"],
                saved_tokens=token_info["unloaded_tokens"],
            )
            return response
        except Exception as e:
            logger.error("Error in session_resume", error=str(e))
            raise

    async def session_end(
        self, project_id: str, summary: Optional[str] = None
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
            embedding_svc = getattr(self._storage, "embedding_service", None)
            session_service = SessionService(db, embedding_service=embedding_svc)

            # 현재 활성 세션 찾기
            sessions = await session_service.list_sessions(
                project_id=project_id, status="active", limit=1
            )

            if not sessions:
                return {
                    "status": "no_active_session",
                    "message": f"프로젝트 '{project_id}'에 활성 세션이 없습니다.",
                }

            result = await session_service.end_with_auto_promotion(
                session_id=sessions[0].id, summary=summary, auto_promote_threshold=4
            )

            session = result.get("session")
            promoted_pins = result.get("promoted_pins", [])

            if session is None:
                return {
                    "status": "error",
                    "message": f"세션 종료 실패: {sessions[0].id}",
                }

            response = session.model_dump()
            response["promoted_pins"] = promoted_pins
            response["promotion_count"] = len(promoted_pins)
            if promoted_pins:
                response["promotion_message"] = (
                    f"{len(promoted_pins)}개의 중요 Pin이 자동 승격되었습니다."
                )

            logger.info(
                "Successfully ended session with auto-promotion",
                session_id=session.id,
                promoted_count=len(promoted_pins),
            )
            return response
        except Exception as e:
            logger.error("Error in session_end", error=str(e))
            raise

    # ===== Memory Relations Tools =====

    async def link(
        self,
        source_id: str,
        target_id: str,
        relation_type: str = "related",
        strength: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a relation between two memories

        Args:
            source_id: Source memory ID
            target_id: Target memory ID
            relation_type: Type of relation (related, parent, child, supersedes, references, depends_on, similar)
            strength: Relation strength (0.0-1.0)
            metadata: Optional metadata for the relation

        Returns:
            dict: Created relation info with 'created' flag
        """
        logger.info(
            "Tool link called",
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
        )

        try:
            from ..core.schemas.relations import RelationCreate, RelationType
            from ..core.services.relation import MemoryNotFoundError, RelationService

            db = self._get_database()
            service = RelationService(db)

            # relation_type 검증
            try:
                rel_type = RelationType(relation_type)
            except ValueError:
                valid_types = [t.value for t in RelationType]
                return {
                    "error": f"Invalid relation_type. Must be one of: {valid_types}"
                }

            data = RelationCreate(
                source_id=source_id,
                target_id=target_id,
                relation_type=rel_type,
                strength=min(max(strength, 0.0), 1.0),  # clamp to 0-1
                metadata=metadata,
            )

            relation, created = await service.find_or_create_relation(data)

            logger.info(
                "Successfully linked memories", relation_id=relation.id, created=created
            )

            return {
                "id": relation.id,
                "source_id": relation.source_id,
                "target_id": relation.target_id,
                "relation_type": relation.relation_type.value,
                "strength": relation.strength,
                "created": created,
                "message": "Relation created" if created else "Relation already exists",
            }
        except MemoryNotFoundError as e:
            logger.warning("Memory not found for link", error=str(e))
            return {"error": str(e)}
        except Exception as e:
            logger.error("Error in link", error=str(e))
            raise

    async def unlink(
        self, source_id: str, target_id: str, relation_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Remove a relation between two memories

        Args:
            source_id: Source memory ID
            target_id: Target memory ID
            relation_type: Optional - specific relation type to remove. If not provided, removes all relations between the two memories.

        Returns:
            dict: Deletion result with count of removed relations
        """
        logger.info(
            "Tool unlink called",
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
        )

        try:
            from ..core.schemas.relations import RelationType

            db = self._get_database()

            # 관계 조회 및 삭제
            if relation_type:
                # 특정 타입만 삭제
                try:
                    RelationType(relation_type)
                except ValueError:
                    valid_types = [t.value for t in RelationType]
                    return {
                        "error": f"Invalid relation_type. Must be one of: {valid_types}"
                    }

                cursor = await db.execute(
                    """
                    DELETE FROM memory_relations 
                    WHERE source_id = ? AND target_id = ? AND relation_type = ?
                    """,
                    (source_id, target_id, relation_type),
                )
                deleted_count = cursor.rowcount
            else:
                # 모든 관계 삭제 (양방향)
                cursor = await db.execute(
                    """
                    DELETE FROM memory_relations 
                    WHERE (source_id = ? AND target_id = ?) 
                       OR (source_id = ? AND target_id = ?)
                    """,
                    (source_id, target_id, target_id, source_id),
                )
                deleted_count = cursor.rowcount

            logger.info("Successfully unlinked memories", deleted_count=deleted_count)

            return {
                "success": deleted_count > 0,
                "deleted_count": deleted_count,
                "source_id": source_id,
                "target_id": target_id,
                "message": (
                    f"Removed {deleted_count} relation(s)"
                    if deleted_count > 0
                    else "No relations found"
                ),
            }
        except Exception as e:
            logger.error("Error in unlink", error=str(e))
            raise

    async def get_links(
        self,
        memory_id: str,
        relation_type: Optional[str] = None,
        direction: str = "both",
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Get relations for a memory

        Args:
            memory_id: Memory ID to get relations for
            relation_type: Optional filter by relation type
            direction: 'outgoing', 'incoming', or 'both'
            limit: Maximum number of relations to return

        Returns:
            dict: List of relations with memory info
        """
        logger.info("Tool get_links called", memory_id=memory_id, direction=direction)

        try:
            from ..core.schemas.relations import RelationType
            from ..core.services.relation import RelationService

            db = self._get_database()
            service = RelationService(db)

            rel_type = None
            if relation_type:
                try:
                    rel_type = RelationType(relation_type)
                except ValueError:
                    valid_types = [t.value for t in RelationType]
                    return {
                        "error": f"Invalid relation_type. Must be one of: {valid_types}"
                    }

            relations = await service.get_relations_for_memory(
                memory_id=memory_id,
                relation_type=rel_type,
                direction=direction,
                limit=limit,
            )

            result = []
            for rel in relations:
                result.append(
                    {
                        "id": rel.id,
                        "source_id": rel.source_id,
                        "target_id": rel.target_id,
                        "relation_type": rel.relation_type.value,
                        "strength": rel.strength,
                        "source_content": (
                            rel.source_content[:100] + "..."
                            if rel.source_content and len(rel.source_content) > 100
                            else rel.source_content
                        ),
                        "target_content": (
                            rel.target_content[:100] + "..."
                            if rel.target_content and len(rel.target_content) > 100
                            else rel.target_content
                        ),
                    }
                )

            logger.info("Successfully retrieved links", count=len(result))

            return {"memory_id": memory_id, "relations": result, "total": len(result)}
        except Exception as e:
            logger.error("Error in get_links", error=str(e))
            raise

    # ===== Weekly Review Tool =====

    async def weekly_review(self, project_id: str, days: int = 7) -> Dict[str, Any]:
        """
        주간/기간별 회고 리포트 생성.

        미완료 pin, 저importance memory, zero-result 쿼리 등을 종합하여
        놓친 정보를 재발견할 수 있는 리포트를 생성합니다.

        Args:
            project_id: 프로젝트 ID
            days: 조회 기간 (기본 7일)

        Returns:
            dict: 주간 회고 리포트
        """
        logger.info(
            "Tool weekly_review called",
            project_id=project_id,
            days=days,
        )

        try:
            from datetime import datetime, timedelta, timezone

            db = self._get_database()
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            # 1. 미완료 핀 (open/in_progress)
            incomplete_pins = await db.fetchall(
                """
                SELECT id, content, importance, status, tags, created_at
                FROM pins
                WHERE project_id = ?
                AND status IN ('open', 'in_progress')
                AND created_at >= ?
                ORDER BY importance DESC, created_at DESC
                LIMIT 20
                """,
                (project_id, cutoff),
            )

            # 2. 저importance로 저장된 메모리 (importance 정보가 태그에 있을 수 있으므로 최근 것 중 관심도 낮은 것)
            low_engagement_memories = await db.fetchall(
                """
                SELECT id, content, category, tags, created_at
                FROM memories
                WHERE project_id = ?
                AND created_at >= ?
                ORDER BY created_at ASC
                LIMIT 10
                """,
                (project_id, cutoff),
            )

            # 3. 최근 세션 요약
            recent_sessions = await db.fetchall(
                """
                SELECT id, status, summary, started_at, ended_at
                FROM sessions
                WHERE project_id = ?
                AND started_at >= ?
                ORDER BY started_at DESC
                LIMIT 5
                """,
                (project_id, cutoff),
            )

            # 4. zero-result 검색 쿼리 (monitoring 테이블이 있는 경우)
            zero_result_queries = []
            try:
                zero_rows = await db.fetchall(
                    """
                    SELECT query, created_at
                    FROM search_logs
                    WHERE project_id = ?
                    AND results_count = 0
                    AND created_at >= ?
                    ORDER BY created_at DESC
                    LIMIT 10
                    """,
                    (project_id, cutoff),
                )
                zero_result_queries = [
                    {"query": r["query"], "created_at": r["created_at"]}
                    for r in zero_rows
                ]
            except Exception:
                pass

            # 5. 통계 집계
            total_memories = await db.fetchone(
                """
                SELECT COUNT(*) as count
                FROM memories
                WHERE project_id = ? AND created_at >= ?
                """,
                (project_id, cutoff),
            )

            total_pins = await db.fetchone(
                """
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed
                FROM pins
                WHERE project_id = ? AND created_at >= ?
                """,
                (project_id, cutoff),
            )

            import json as _json

            report = {
                "project_id": project_id,
                "period_days": days,
                "summary": {
                    "total_memories_created": (
                        total_memories["count"] if total_memories else 0
                    ),
                    "total_pins": total_pins["total"] if total_pins else 0,
                    "pins_completed": total_pins["completed"] if total_pins else 0,
                    "pins_incomplete": len(incomplete_pins),
                    "sessions_count": len(recent_sessions),
                    "zero_result_searches": len(zero_result_queries),
                },
                "incomplete_pins": [
                    {
                        "id": p["id"],
                        "content": (p["content"] or "")[:100],
                        "importance": p["importance"],
                        "status": p["status"],
                        "tags": (
                            _json.loads(p["tags"])
                            if isinstance(p.get("tags"), str) and p["tags"]
                            else []
                        ),
                        "created_at": p["created_at"],
                    }
                    for p in incomplete_pins
                ],
                "recent_memories": [
                    {
                        "id": m["id"],
                        "content": (m["content"] or "")[:100],
                        "category": m["category"],
                        "created_at": m["created_at"],
                    }
                    for m in low_engagement_memories
                ],
                "recent_sessions": [
                    {
                        "id": s["id"],
                        "status": s["status"],
                        "summary": s["summary"],
                        "started_at": s["started_at"],
                        "ended_at": s["ended_at"],
                    }
                    for s in recent_sessions
                ],
                "zero_result_queries": zero_result_queries,
                "recommendations": self._generate_review_recommendations(
                    incomplete_pins, zero_result_queries, total_pins
                ),
            }

            logger.info(
                "Weekly review generated",
                project_id=project_id,
                incomplete_pins=len(incomplete_pins),
            )

            return report
        except Exception as e:
            logger.error("Error in weekly_review", error=str(e))
            raise

    def _generate_review_recommendations(
        self,
        incomplete_pins: list,
        zero_result_queries: list,
        total_pins: dict,
    ) -> List[str]:
        """회고 리포트의 추천 사항 생성"""
        recommendations = []

        high_importance_incomplete = [
            p for p in incomplete_pins if p["importance"] >= 4
        ]
        if high_importance_incomplete:
            recommendations.append(
                f"중요도 높은 미완료 작업 {len(high_importance_incomplete)}개가 있습니다. 우선 처리를 고려하세요."
            )

        if len(incomplete_pins) > 5:
            recommendations.append(
                f"미완료 핀이 {len(incomplete_pins)}개입니다. 불필요한 핀은 정리하거나 완료 처리하세요."
            )

        if zero_result_queries:
            queries = [q["query"] for q in zero_result_queries[:3]]
            recommendations.append(
                f"결과 없는 검색이 {len(zero_result_queries)}건 있었습니다: {', '.join(queries)}. "
                "관련 메모리를 추가하거나 검색어를 조정해보세요."
            )

        total = total_pins["total"] if total_pins else 0
        completed = total_pins["completed"] if total_pins else 0
        if total > 0:
            rate = completed / total * 100
            if rate < 50:
                recommendations.append(
                    f"핀 완료율이 {rate:.0f}%입니다. 작업 범위를 줄이거나 우선순위를 재조정하세요."
                )

        if not recommendations:
            recommendations.append("특별한 조치 사항이 없습니다. 잘 운영되고 있습니다!")

        return recommendations

    def _get_database(self) -> "Database":
        """Storage에서 Database 인스턴스 가져오기"""
        # DirectStorageBackend의 경우 db 속성이 있음
        if hasattr(self._storage, "db") and self._storage.db is not None:
            return self._storage.db

        # 다른 방법으로 database 접근 시도
        if hasattr(self._storage, "_db"):
            return self._storage._db

        raise RuntimeError("Cannot access database from storage backend")
