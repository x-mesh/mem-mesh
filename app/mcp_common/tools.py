"""
MCP Tool Handlers - MCP 서버들이 공유하는 Tool 비즈니스 로직.

이 모듈은 storage 의존성을 주입받아 동작하므로,
FastMCP와 Pure MCP 모두에서 사용할 수 있습니다.
"""

import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from ..core.errors import ContextNotFoundError, ValidationError
from ..core.schemas.requests import AddParams, SearchParams, StatsParams, UpdateParams
from ..core.storage.base import StorageBackend
from ..core.utils.logger import get_logger
from .prompt_optimizer import PromptOptimizer

if TYPE_CHECKING:
    from ..core.database.base import Database
    from ..core.schemas.responses import ContextResponse, SearchResponse
    from ..web.websocket.realtime import RealtimeNotifier

logger = get_logger("mcp-tools")

# Batch drill-down cap: keeps a single context(ids=[...]) call inside a sane
# token/latency budget (10 full memories ≈ the practical injection ceiling).
_CONTEXT_BATCH_MAX_IDS = 10


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
        anchors: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Add a new memory to the memory store

        Args:
            content: Memory content (10-50000 characters)
            project_id: Project identifier (optional)
            category: Memory category (task, bug, idea, decision, incident, code_snippet, git-history)
            source: Memory source
            client: Client tool name (cursor, kiro, claude_code, etc.)
            tags: Memory tags
            anchors: Git anchors {commit_hash, file_paths, branch} the client
                collected for this memory (metadata only, not embedded)

        Returns:
            dict: 생성된 메모리 정보
        """
        # Fallback: auto-detect client from environment if not provided
        if not client:
            client = os.environ.get("MEM_MESH_CLIENT")

        logger.info_with_details(
            "Tool add called",
            details={
                "content": content,
                "tags": tags,
                "source": source,
                "client": client,
            },
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
                anchors=anchors,
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
        scope: str = "local",
        anchored_path: Optional[str] = None,
        starred_only: bool = False,
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
            scope: Search scope — local (default) / hub (team hub only) /
                all (local + hub fused via weighted RRF)
            anchored_path: Only memories git-anchored to this repo-relative
                file/directory prefix (forces scope=local — hub rows carry
                foreign-repo anchors the filter can't judge)
            starred_only: Only memories the user starred (forces scope=local —
                stars are a local judgement, never shared to the hub)

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

            async def _local_search():
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
                    anchored_path=anchored_path,
                    starred_only=starred_only,
                )
                local_result = await self._storage.search_memories(params)

                # 노이즈 필터 적용 (로컬 결과 전용 — hub 결과는 필터 대상 아님)
                if enable_noise_filter and local_result.results:
                    from ..core.services.noise_filter import SmartSearchFilter

                    filter_service = SmartSearchFilter()
                    context = {
                        "project": project_id,
                        "max_results": limit,
                        "aggressive_filter": False,
                    }
                    local_result = filter_service.apply(local_result, query, context)
                return local_result

            if scope not in ("local", "hub", "all"):
                scope = "local"
            if anchored_path and scope != "local":
                # Hub rows carry anchors from other repos — the path filter
                # can't be applied to them, so an anchored search is local-only
                # rather than leaking unfiltered hub rows past the filter.
                logger.info("anchored_path forces scope=local", requested_scope=scope)
                scope = "local"
            if starred_only and scope != "local":
                # Stars live only on this node — a hub row can never be starred,
                # so a starred search that fanned out would just leak unfiltered
                # hub rows past the filter.
                logger.info("starred_only forces scope=local", requested_scope=scope)
                scope = "local"
            if scope == "local":
                result = await _local_search()
            else:
                # Federated: this node reaches the hub server-side; the caller
                # still only ever talks to this personal endpoint.
                db = getattr(self._storage, "db", None)
                if db is None:
                    # API-backed storage has no local DB handle; federation is
                    # handled by the remote server instead (Phase 2). Degrade —
                    # but never answer a hub-only request with local results.
                    if scope == "hub":
                        from ..core.schemas.responses import SearchResponse

                        result = SearchResponse(
                            results=[], total=0, hub_status="skipped"
                        )
                    else:
                        result = await _local_search()
                        result.hub_status = "skipped"
                else:
                    from ..core.config import get_settings
                    from ..core.services.federated_search import FederatedHubSearch

                    federated = FederatedHubSearch(db, get_settings())
                    result = await federated.search(
                        scope=scope,
                        query=query,
                        limit=limit,
                        local_search=_local_search,
                        categories=[category] if category else None,
                    )

            logger.info(
                "Search completed",
                result_count=len(result.results),
                filtered=enable_noise_filter,
            )

            # 검색 서비스는 enrichment를 안 붙인다 — 노출 계층이 붙여야 한다.
            # 대시보드 REST 라우트와 같은 헬퍼를 쓴다(구현이 갈라져 있어서 웹에서만
            # enrich가 안 보이는 버그가 났다).
            from ..core.services.recall import attach_enrichment_to_results

            enrichment_map: Dict[str, Any] = await attach_enrichment_to_results(
                getattr(self._storage, "db", None), result.results
            )

            # 응답 압축 (활성화된 경우)
            if (
                self._enable_compression
                and self._optimizer
                and response_format != "full"
            ):
                return self._compress_search_response(
                    result, response_format, enrichment_map
                )

            return result.model_dump()
        except Exception as e:
            logger.error("Error in search", error=str(e))
            raise

    def _compress_search_response(
        self,
        result: "SearchResponse",
        format: str = "standard",
        enrichment_map: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """검색 결과 압축. enrichment_map(id→title/abstract/tags)이 있으면 compact
        요약을 원문 절단 대신 enriched abstract로 치환하고 topic tags를 실어,
        같은 토큰으로 정보 밀도를 높인다(원문은 context()/get() 드릴다운)."""
        emap = enrichment_map or {}
        results_list = []
        for r in result.results:
            enr = emap.get(str(r.id)) or {}
            results_list.append(
                {
                    "id": r.id,
                    "content": r.content,
                    "category": r.category,
                    "similarity_score": r.similarity_score,
                    "created_at": r.created_at,
                    "project_id": r.project_id,
                    "tags": r.tags,
                    "anchors": r.anchors,
                    "is_starred": getattr(r, "is_starred", False),
                    "title": (r.title or enr.get("title")),
                    "abstract": (r.abstract or enr.get("abstract")),
                    "enrichment_tags": enr.get("tags") or [],
                    "origin": getattr(r, "origin", "local"),
                }
            )

        if format == "minimal":
            # 극도 압축: ID와 점수만
            compressed_results = [
                {"id": r["id"][:8], "score": round(r["similarity_score"], 2)}
                for r in results_list
            ]
        elif format == "compact":
            # 압축: enriched abstract 우선(없으면 원문 절단), title + topic tags.
            compressed_results = []
            for r in results_list:
                item: Dict[str, Any] = {
                    "id": r["id"][:8],
                    "category": r["category"],
                    "score": round(r["similarity_score"], 2),
                }
                if r["title"]:
                    item["title"] = r["title"]
                content = r["content"] or ""
                item["summary"] = r["abstract"] or (
                    content[:80] + "..." if len(content) > 80 else content
                )
                topic_tags = r["enrichment_tags"] or r["tags"]
                if topic_tags:
                    item["tags"] = topic_tags
                if r["origin"] == "hub":
                    item["origin"] = "hub"
                compressed_results.append(item)
        else:  # standard — abstract-first (progressive disclosure)
            # enriched 결과는 title+abstract로 요약하고 raw content는 생략한다
            # (원문은 context()/get(<id>) 드릴다운). enrichment가 아직 없는
            # 메모리는 full content를 유지해 커버리지 공백 동안 회귀가 없다.
            compressed_results = []
            for r in results_list:
                item: Dict[str, Any] = {
                    "id": r["id"],  # full id — get()/context() 드릴다운용
                    "category": r["category"],
                    "similarity_score": r["similarity_score"],
                    "created_at": r["created_at"],
                    "project_id": r["project_id"],
                    "anchors": r["anchors"],
                }
                # Only carried when true — an is_starred:false on every row would
                # cost tokens on the overwhelmingly common unstarred case.
                if r["is_starred"]:
                    item["is_starred"] = True
                topic_tags = r["enrichment_tags"] or r["tags"]
                if topic_tags:
                    item["tags"] = topic_tags
                if r["origin"] == "hub":
                    item["origin"] = "hub"
                if r["abstract"]:
                    if r["title"]:
                        item["title"] = r["title"]
                    item["abstract"] = r["abstract"]
                    # raw content 생략 — 필요하면 context()/get()으로 드릴다운
                else:
                    item["content"] = r["content"]
                compressed_results.append(item)

        return {
            "results": compressed_results,
            "total": len(compressed_results),
            "format": format,
            "compressed": True,
            # federation 메타: 모든 포맷 top-level에 항상 포함(None이어도 키 유지).
            # scope=local이면 None, federated면 'ok'/'unavailable'/'skipped'.
            "hub_status": getattr(result, "hub_status", None),
        }

    async def context(
        self,
        memory_id: Optional[str] = None,
        depth: int = 2,
        project_id: Optional[str] = None,
        response_format: str = "standard",
        ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Get context around a specific memory, or several memories at once

        Args:
            memory_id: Memory ID to get context for (single-ID mode)
            depth: Search depth (1-5)
            project_id: Project filter
            response_format: Response format (compact/standard/full)
            ids: Batch mode — fetch up to 10 memories in one call. A missing
                id lands in ``not_found`` instead of failing the whole batch.

        Returns:
            dict: 컨텍스트 정보 (압축 가능); batch mode returns
                {"memories": [...], "not_found": [...], "batch": True}
        """
        logger.info(
            "Tool context called",
            memory_id=memory_id,
            ids_count=len(ids) if ids else 0,
            depth=depth,
            project_id=project_id,
            format=response_format,
        )

        if ids is not None:
            return await self._context_batch(ids, depth, project_id, response_format)

        if not memory_id:
            raise ValidationError("context requires either memory_id or ids")

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

    async def _context_batch(
        self,
        ids: List[str],
        depth: int,
        project_id: Optional[str],
        response_format: str,
    ) -> Dict[str, Any]:
        """Batch drill-down: one call for several full memories.

        Runs the same single-ID flow per id so every storage backend works
        unchanged. Only a genuinely missing id lands in ``not_found``
        (all-or-nothing would waste the ids that DID resolve); any other
        failure — DB down, API unreachable — re-raises, matching single-ID
        semantics: an infra outage must not masquerade as "memory not found",
        or the agent would wrongly mark those memories stale/gone.
        """
        # The Pure-MCP path does no schema validation, so a string here would
        # otherwise be iterated character by character (8 bogus lookups).
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValidationError("context ids must be a list of memory id strings")
        if not ids:
            raise ValidationError("context ids must be a non-empty list")
        if len(ids) > _CONTEXT_BATCH_MAX_IDS:
            raise ValidationError(
                f"context ids cannot exceed {_CONTEXT_BATCH_MAX_IDS} entries"
            )

        memories: List[Dict[str, Any]] = []
        not_found: List[str] = []
        for mid in ids:
            try:
                result = await self._storage.get_context(mid, depth, project_id)
            except ContextNotFoundError:
                not_found.append(mid)
                continue
            if (
                self._enable_compression
                and self._optimizer
                and response_format == "compact"
            ):
                memories.append(self._compress_context_response(result))
            else:
                memories.append(result.model_dump())

        logger.info(
            "Context batch retrieved",
            requested=len(ids),
            found=len(memories),
            not_found=len(not_found),
        )
        return {"memories": memories, "not_found": not_found, "batch": True}

    def _compress_context_response(self, result: "ContextResponse") -> Dict[str, Any]:
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
        staging: bool = False,
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
                client=os.environ.get("MEM_MESH_CLIENT"),
                is_staging=staging,
            )

            logger.info(
                "Successfully added pin",
                pin_id=result.id,
                importance=effective_importance,
                auto=auto_importance,
            )

            # 실시간 알림 전송 (full response for dashboard)
            if self._notifier:
                try:
                    await self._notifier.notify_pin_created(result.model_dump())
                except Exception as e:
                    logger.warning(f"Failed to send pin_add notification: {e}")

            # MCP 반환은 compact
            response = {
                "id": result.id,
                "importance": effective_importance,
                "status": result.status,
            }
            if auto_importance:
                response["auto_importance"] = True
            return response
        except Exception as e:
            logger.error("Error in pin_add", error=str(e))
            raise

    async def pin_complete(
        self,
        pin_id: str,
        promote: bool = False,
        category: str = "task",
    ) -> Dict[str, Any]:
        """Mark a pin as completed, optionally promoting to permanent memory.

        Args:
            pin_id: Pin ID to complete
            promote: If True, also promote to permanent memory (saves a round-trip)
            category: Memory category when promoting (task, decision, bug, incident, idea, code_snippet)

        Returns:
            dict: Completed pin information with promotion suggestion (and memory_id if promoted)
        """
        logger.info("Tool pin_complete called", pin_id=pin_id, promote=promote)

        try:
            from ..core.errors import PinAlreadyCompletedError
            from ..core.services.pin import PinService

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

            logger.info(
                "Successfully completed pin",
                pin_id=pin_id,
                suggest_promotion=suggest_promotion,
            )

            # 실시간 알림 전송 (full response for dashboard)
            if self._notifier:
                try:
                    full_response = result.model_dump()
                    full_response["suggest_promotion"] = suggest_promotion
                    await self._notifier.notify_pin_completed(full_response)
                except Exception as e:
                    logger.warning(f"Failed to send pin_complete notification: {e}")

            # MCP 반환은 compact
            response = {
                "id": pin_id,
                "status": result.status,
                "suggest_promotion": suggest_promotion,
            }

            # promote=True이면 자동 승격
            if promote:
                try:
                    promote_result = await pin_service.promote_to_memory(
                        pin_id, category=category
                    )
                    response["promoted"] = True
                    response["memory_id"] = promote_result["memory_id"]

                    # 승격 알림
                    if self._notifier:
                        try:
                            await self._notifier.notify_pin_promoted(
                                pin_id, promote_result["memory_id"]
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send promote notification: {e}")
                except Exception as e:
                    logger.warning(f"Auto-promote failed for pin {pin_id}: {e}")
                    response["promoted"] = False
                    response["promote_error"] = str(e)

            return response
        except Exception as e:
            logger.error("Error in pin_complete", error=str(e))
            raise

    async def pin_promote(
        self,
        pin_id: str,
        category: str = "task",
        anchors: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Promote a pin to a permanent memory

        Args:
            pin_id: Pin ID to promote
            category: Memory category (task, decision, bug, incident, idea, code_snippet)
            anchors: Git anchors {commit_hash, file_paths, branch} to attach to the
                promoted memory (metadata only, not embedded)

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

            result = await pin_service.promote_to_memory(
                pin_id, category=category, anchors=anchors
            )

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
                    await self._notifier.notify_pin_promoted(
                        pin_id, result["memory_id"]
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to send pin_promote realtime notification: {e}"
                    )

            return result
        except Exception as e:
            logger.error("Error in pin_promote", error=str(e))
            raise

    async def pin_list(
        self,
        project_id: str,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
        min_importance: Optional[int] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
        include_stats: bool = False,
    ) -> Dict[str, Any]:
        """List pins with filtering options

        Args:
            project_id: Project identifier
            session_id: Filter by specific session (optional)
            status: Filter by status (open, in_progress, completed)
            min_importance: Minimum importance score (1-5)
            tags: Filter by tags (AND condition)
            limit: Maximum number of pins to return
            include_stats: Include pin statistics in response

        Returns:
            dict: Pin list with optional statistics
        """
        logger.info(
            "Tool pin_list called",
            project_id=project_id,
            session_id=session_id,
            status=status,
            min_importance=min_importance,
        )

        try:
            from ..core.services.pin import PinService

            db = self._get_database()
            pin_service = PinService(
                db, getattr(self._storage, "embedding_service", None)
            )

            # Use get_pins for project-level query, get_pins_filtered for session-level
            needs_client_filter = False
            if session_id:
                pins = await pin_service.get_pins_filtered(
                    session_id=session_id,
                    min_importance=min_importance,
                    status=status,
                    tags=tags,
                    limit=limit,
                )
            else:
                # When client-side filters are needed, fetch without limit
                # to avoid returning fewer results than requested
                needs_client_filter = min_importance is not None or bool(tags)
                fetch_limit = 200 if needs_client_filter else limit
                pins = await pin_service.get_pins(
                    project_id=project_id,
                    status=status,
                    limit=fetch_limit,
                )
                if min_importance is not None:
                    pins = [p for p in pins if p.importance >= min_importance]
                if tags:
                    pins = [
                        p for p in pins if all(tag in (p.tags or []) for tag in tags)
                    ]
                if needs_client_filter:
                    pins = pins[:limit]

            # Compact pin format + stats in single pass
            pin_items = []
            by_status: Dict[str, int] = {"open": 0, "in_progress": 0, "completed": 0}
            for p in pins:
                content = (p.content or "")[:200]
                item: Dict[str, Any] = {
                    "id": p.id,
                    "content": content,
                    "status": p.status,
                    "importance": p.importance,
                }
                if p.tags:
                    item["tags"] = p.tags
                if p.session_id:
                    item["session_id"] = p.session_id
                if p.completed_at:
                    item["completed_at"] = p.completed_at
                pin_items.append(item)
                if p.status in by_status:
                    by_status[p.status] += 1

            result: Dict[str, Any] = {
                "pins": pin_items,
                "count": len(pin_items),
                "project_id": project_id,
            }

            # Include statistics if requested
            if include_stats and session_id:
                stats = await pin_service.get_pin_statistics(session_id)
                result["stats"] = stats
            elif include_stats:
                result["stats"] = {
                    "total": len(pins),
                    "by_status": by_status,
                }

            logger.info(
                "Successfully listed pins",
                project_id=project_id,
                count=len(pin_items),
            )
            return result
        except Exception as e:
            logger.error("Error in pin_list", error=str(e))
            raise

    async def pin_get(self, pin_id: str) -> Dict[str, Any]:
        """Get a single pin by its full ID.

        Unlike pin_list (filtered list) and session_resume (active pins only),
        this resolves any pin — including completed ones — directly by id, which
        is the only way to read a pin back once it has left the active set.

        Args:
            pin_id: Full pin ID (36-char UUID)

        Returns:
            dict: {found: True, pin: {...}} or {found: False, pin_id, message}
        """
        logger.info("Tool pin_get called", pin_id=pin_id)

        try:
            from ..core.services.pin import PinService

            db = self._get_database()
            pin_service = PinService(
                db, getattr(self._storage, "embedding_service", None)
            )

            pin = await pin_service.get_pin(pin_id)
            if pin is None:
                return {
                    "found": False,
                    "pin_id": pin_id,
                    "message": f"Pin not found: {pin_id}",
                }

            return {"found": True, "pin": pin.model_dump()}
        except Exception as e:
            logger.error("Error in pin_get", error=str(e))
            raise

    async def session_resume(
        self,
        project_id: str,
        expand: Union[bool, str] = False,
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

            # Close the read loop on the explicit tool path too: surface curated
            # memories for the open work (read-only — does not bump access_count,
            # so auto-surfacing never inflates recall analytics). Best-effort.
            try:
                search_svc = getattr(self._storage, "unified_search_service", None)
                pins = getattr(session_context, "pins", None) or []
                open_texts: list[str] = []
                for p in pins:
                    pd = p if isinstance(p, dict) else p.dict()
                    if pd.get("status") in ("open", "in_progress"):
                        open_texts.append(str(pd.get("content", ""))[:100])
                if search_svc is not None and open_texts:
                    from ..core.services.recall import surface_relevant_memories

                    session_context.relevant_memories = await surface_relevant_memories(
                        search_svc, project_id, query=" ".join(open_texts)
                    )
            except Exception as e:  # noqa: BLE001
                logger.debug("relevant-memory surfacing skipped", error=str(e))

            # Team hub digest 주입 (best-effort, 로컬 read only — 네트워크 0회).
            # worker가 prefetch한 캐시를 read_cached_team_digest로 읽어 붙인다.
            # auto-share 미구독/캐시 없음/만료/미지원이면 None으로 남는다.
            try:
                db = getattr(self._storage, "db", None)
                if db is not None:
                    from ..core.services.federated_search import (
                        read_cached_team_digest,
                    )

                    session_context.team_hub = await read_cached_team_digest(
                        db, project_id
                    )
            except Exception as e:  # noqa: BLE001 — session start must never fail
                logger.debug("team-hub digest injection skipped", error=str(e))

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
        self,
        project_id: str,
        summary: Optional[str] = None,
        auto_complete_pins: Union[bool, str] = "none",
    ) -> Dict[str, Any]:
        """End the current session for a project

        Args:
            project_id: Project identifier
            summary: Session summary (auto-generated if not provided)
            auto_complete_pins: Pin auto-complete strategy: 'none'(default),
                'in_progress'(complete active only, keep open), 'all'(complete everything).
                Boolean also accepted (false=none, true=all).

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
                session_id=sessions[0].id,
                summary=summary,
                auto_promote_threshold=4,
                auto_complete_pins=auto_complete_pins,
            )

            session = result.get("session")
            promoted_pins = result.get("promoted_pins", [])
            auto_completed = result.get("auto_completed_pins", [])

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
            if auto_completed:
                response["auto_completed_pins"] = auto_completed
                response["auto_completed_count"] = len(auto_completed)

            logger.info(
                "Successfully ended session with auto-promotion",
                session_id=session.id,
                promoted_count=len(promoted_pins),
                auto_completed_count=len(auto_completed),
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
            from ..core.errors import MemoryNotFoundError
            from ..core.schemas.relations import RelationCreate, RelationType
            from ..core.services.relation import RelationService

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

            # 4. zero-result 검색 쿼리. 실측 테이블은 search_metrics이며 컬럼은
            # result_count / timestamp(존재하지 않는 search_logs.results_count/
            # created_at가 아님) — 이 쿼리는 이전엔 항상 예외로 빈 리스트를 반환하던
            # 죽은 코드였다. search_metrics는 initializer가 항상 생성하지만, 구버전
            # 스키마 대비 방어적으로 try/except는 유지한다.
            zero_result_queries = []
            try:
                zero_rows = await db.fetchall(
                    """
                    SELECT query, timestamp
                    FROM search_metrics
                    WHERE project_id = ?
                    AND result_count = 0
                    AND timestamp >= ?
                    ORDER BY timestamp DESC
                    LIMIT 10
                    """,
                    (project_id, cutoff),
                )
                zero_result_queries = [
                    {"query": r["query"], "created_at": r["timestamp"]}
                    for r in zero_rows
                ]
            except Exception as e:
                logger.warning("zero-result query lookup failed", error=str(e))

            # 4.5. 주입 메모리 적중률 (t9). injected_memories의 utilized 판정을
            # 집계하여 "주입된 세션 메모리가 실제로 활용됐는가"를 지표로 노출한다.
            # judged = 판정 완료(utilized IS NOT NULL) 건수, hit_rate = utilized/judged.
            # v13 이전 스키마(utilized 컬럼 부재) 대비 방어적으로 try/except 유지.
            injection_stats = {
                "injected": 0,
                "judged": 0,
                "utilized": 0,
                "hit_rate": 0.0,
                "by_method": {},
            }
            try:
                inj_row = await db.fetchone(
                    """
                    SELECT
                        COUNT(*) AS injected,
                        SUM(CASE WHEN utilized IS NOT NULL THEN 1 ELSE 0 END)
                            AS judged,
                        SUM(CASE WHEN utilized = 1 THEN 1 ELSE 0 END) AS utilized
                    FROM injected_memories
                    WHERE project_id = ? AND created_at >= ?
                    """,
                    (project_id, cutoff),
                )
                by_method_rows = await db.fetchall(
                    """
                    SELECT judge_method, COUNT(*) AS c
                    FROM injected_memories
                    WHERE project_id = ? AND created_at >= ?
                    AND judge_method IS NOT NULL
                    GROUP BY judge_method
                    """,
                    (project_id, cutoff),
                )
                injected = (inj_row["injected"] if inj_row else 0) or 0
                judged = (inj_row["judged"] if inj_row else 0) or 0
                utilized = (inj_row["utilized"] if inj_row else 0) or 0
                injection_stats = {
                    "injected": injected,
                    "judged": judged,
                    "utilized": utilized,
                    "hit_rate": round(utilized / judged, 4) if judged else 0.0,
                    "by_method": {r["judge_method"]: r["c"] for r in by_method_rows},
                }
            except Exception as e:
                logger.warning("injection stats lookup failed", error=str(e))

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

            # Enrichment coverage — "개선되고 있는가"를 세션 안에서 볼 수 있는
            # 지표. memory_enrichment는 lazy 테이블이라 부재 시 0으로 폴백.
            enrichment_coverage = {"total": 0, "enriched": 0, "ratio": 0.0}
            try:
                cov_row = await db.fetchone(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN e.title IS NOT NULL
                                     AND TRIM(e.title) != '' THEN 1 ELSE 0 END)
                               AS enriched
                    FROM memories m
                    LEFT JOIN memory_enrichment e ON e.memory_id = m.id
                    WHERE m.project_id = ?
                    """,
                    (project_id,),
                )
                if cov_row and cov_row["total"]:
                    enrichment_coverage = {
                        "total": cov_row["total"],
                        "enriched": cov_row["enriched"] or 0,
                        "ratio": round(
                            (cov_row["enriched"] or 0) / cov_row["total"], 4
                        ),
                    }
            except Exception as cov_exc:  # noqa: BLE001 — lazy 테이블 부재 등
                logger.debug(f"enrichment coverage skipped: {cov_exc}")

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
                    "injection_stats": injection_stats,
                    "enrichment_coverage": enrichment_coverage,
                },
                "incomplete_pins": [
                    {
                        "id": p["id"],
                        "content": (p["content"] or "")[:100],
                        "importance": p["importance"],
                        "status": p["status"],
                        "tags": (
                            _json.loads(p["tags"])
                            if isinstance(p["tags"], str) and p["tags"]
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

    async def doc_proposals(
        self,
        project_id: str,
        status: str = "approved",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Approved doc-promotion 제안을 조회한다 (에이전트가 로컬 적용).

        서버는 파일에 쓰지 않으므로 적용 주체는 대상 저장소 cwd의 에이전트다. 각
        제안은 file_path(상대 경로) + proposed_content(개정 전문) + original_hash를
        담는다. 에이전트는 원본이 original_hash와 여전히 일치하는지 확인한 뒤 파일을
        수정하고 doc_proposal_applied로 보고한다.

        Args:
            project_id: 프로젝트 ID
            status: 제안 상태 필터 (기본 approved)
            limit: 최대 반환 개수

        Returns:
            dict: {proposals: [...], count, project_id, status}
        """
        logger.info(
            "Tool doc_proposals called",
            project_id=project_id,
            status=status,
        )

        from ..core.schemas.doc_proposal import DocProposalAgentView
        from ..core.services.doc_proposal import DocProposalService

        db = self._get_database()
        service = DocProposalService(db)
        rows = await service.list_proposals(
            project_id=project_id, status=status, limit=limit
        )
        proposals = [DocProposalAgentView.from_row(r).model_dump() for r in rows]
        return {
            "proposals": proposals,
            "count": len(proposals),
            "project_id": project_id,
            "status": status,
        }

    async def doc_proposal_applied(self, proposal_id: str) -> Dict[str, Any]:
        """적용 보고: approved 제안을 applied(terminal)로 전이한다.

        에이전트가 proposed_content를 로컬 파일에 반영한 뒤 호출한다. 서버는 파일을
        쓰지 않으므로 여기서 하는 일은 상태 전이 기록뿐이다. 승인되지 않은 제안에
        대한 호출은 상태 머신이 ``InvalidStatusTransitionError``로 거부한다.

        Args:
            proposal_id: 적용된 제안 ID

        Returns:
            dict: {proposal_id, status: "applied", applied: True}
        """
        logger.info("Tool doc_proposal_applied called", proposal_id=proposal_id)

        from ..core.services.doc_proposal import DocProposalService

        db = self._get_database()
        service = DocProposalService(db)
        updated = await service.mark_applied(proposal_id)
        return {
            "proposal_id": proposal_id,
            "status": updated["status"],
            "applied": True,
        }

    async def report_anchor_status(
        self,
        memory_id: str,
        status: str,
        detail: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a client's local anchor-verification verdict (fresh|stale).

        The server has no git access, so the agent verifies a memory's anchors
        locally (file_paths exist, commit reachable) and reports here. A 'stale'
        memory is excluded from future auto-injection; 'fresh' clears the weak
        aged-anchor warning.

        Args:
            memory_id: Memory whose anchors were verified (full UUID)
            status: 'fresh' (intact) or 'stale' (rotted)
            detail: Optional note on what failed (logged only)

        Returns:
            dict: {memory_id, stale_status, stale_checked_at}
        """
        logger.info(
            "Tool report_anchor_status called",
            memory_id=memory_id,
            status=status,
        )

        try:
            memory_service = getattr(self._storage, "memory_service", None)
            if memory_service is None:
                raise RuntimeError(
                    "report_anchor_status requires a local memory service"
                )
            result = await memory_service.report_anchor_status(
                memory_id, status, detail
            )
            logger.info("Recorded anchor status", memory_id=memory_id, status=status)
            return result
        except Exception as e:
            logger.error("Error in report_anchor_status", error=str(e))
            raise

    async def star(self, memory_id: str) -> Dict[str, Any]:
        """Star a memory (durable display/filter marker; idempotent).

        Args:
            memory_id: Memory to star (full UUID)

        Returns:
            dict: {memory_id, is_starred}
        """
        return await self._set_starred(memory_id, True)

    async def unstar(self, memory_id: str) -> Dict[str, Any]:
        """Remove a memory's star (idempotent).

        Args:
            memory_id: Memory to unstar (full UUID)

        Returns:
            dict: {memory_id, is_starred}
        """
        return await self._set_starred(memory_id, False)

    async def _set_starred(self, memory_id: str, starred: bool) -> Dict[str, Any]:
        """Shared star/unstar path.

        Goes straight to the local memory service rather than through
        StorageBackend — the same local-only pattern report_anchor_status uses,
        because APIStorageBackend has no memory_service and adding an abstract
        method would break both backends.
        """
        logger.info("Tool star called", memory_id=memory_id, starred=starred)

        try:
            memory_service = getattr(self._storage, "memory_service", None)
            if memory_service is None:
                raise RuntimeError("star/unstar requires a local memory service")
            result = await memory_service.set_starred(memory_id, starred)
            logger.info("Set starred", memory_id=memory_id, starred=starred)
            return result
        except Exception as e:
            logger.error("Error in star/unstar", error=str(e))
            raise

    def _get_database(self) -> "Database":
        """Storage에서 Database 인스턴스 가져오기"""
        # DirectStorageBackend의 경우 db 속성이 있음
        if hasattr(self._storage, "db") and self._storage.db is not None:
            return self._storage.db

        # 다른 방법으로 database 접근 시도
        if hasattr(self._storage, "_db"):
            return self._storage._db

        raise RuntimeError("Cannot access database from storage backend")
