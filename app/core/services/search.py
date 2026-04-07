"""
Search Service for mem-mesh
하이브리드 검색을 수행하는 서비스
"""

import json
import logging
import time
from datetime import datetime
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, List, Optional

from ..database.base import Database
from ..embeddings.service import EmbeddingService
from ..schemas.responses import SearchResponse, SearchResult

try:
    from .query_expander import get_query_expander
except ImportError:
    # None if no QueryExpander
    get_query_expander = None
from .cache_manager import get_cache_manager

if TYPE_CHECKING:
    from .metrics_collector import MetricsCollector

logger = logging.getLogger(__name__)


def _parse_tags(row) -> Optional[List[str]]:
    """DB Row에서 tags 값을 파싱하여 리스트로 변환"""
    try:
        # Get tags field from Row object
        tags_value = row["tags"] if "tags" in row.keys() else None

        if tags_value is None:
            return None
        if isinstance(tags_value, list):
            return tags_value
        if isinstance(tags_value, str):
            if not tags_value or tags_value == "[]":
                return None
            try:
                parsed = json.loads(tags_value)
                return parsed if isinstance(parsed, list) and len(parsed) > 0 else None
            except json.JSONDecodeError:
                return None
    except Exception as e:
        logger.debug(f"Failed to parse tags: {e}")
        return None
    return None


class SearchService:
    """하이브리드 검색 서비스"""

    def __init__(
        self,
        db: Database,
        embedding_service: EmbeddingService,
        metrics_collector: Optional["MetricsCollector"] = None,
    ):
        self.db = db
        self.embedding_service = embedding_service
        self.metrics_collector = metrics_collector
        self.similarity_threshold = 0.5
        self.cache_manager = get_cache_manager()  # Initialize cache manager
        logger.info("SearchService initialized with smart caching")

    async def search(
        self,
        query: str,
        project_id: Optional[str] = None,
        category: Optional[str] = None,
        source: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_direction: str = "desc",
        recency_weight: float = 0.0,
        search_mode: str = "hybrid",
    ) -> SearchResponse:
        """
        하이브리드 검색 수행

        Args:
            query: 검색 쿼리 (빈 문자열인 경우 모든 메모리 반환)
            project_id: 프로젝트 필터
            category: 카테고리 필터
            source: 소스 필터
            tag: 태그 필터
            limit: 결과 개수 제한
            offset: 결과 시작 위치 (페이지네이션)
            sort_by: 정렬 기준 (created_at, updated_at, category, project, size)
            sort_direction: 정렬 방향 (asc, desc)
            recency_weight: 최신성 가중치 (0.0 ~ 1.0)
            search_mode: 검색 모드 (hybrid, exact, semantic, fuzzy)

        Returns:
            SearchResponse: 검색 결과
        """
        # Start timing for metrics collection
        start_time = time.perf_counter()

        # Query Expansion for Korean/English (if available)
        original_query = query
        if query and get_query_expander and search_mode != "exact":
            try:
                expander = get_query_expander()
                expanded_query = expander.expand_query(query)
                if expanded_query != query:
                    logger.info(
                        f"Query expanded: '{query}' → '{expanded_query[:100]}...'"
                    )
                    query = expanded_query
            except Exception as e:
                logger.warning(f"Query expansion failed: {e}, using original query")

        logger.info(
            f"Searching for query: '{original_query}' (expanded: {len(query.split()) if query else 0} terms) with mode: {search_mode}, filters - project_id: {project_id}, category: {category}, source: {source}, tag: {tag}, limit: {limit}, offset: {offset}, sort: {sort_by} {sort_direction}"
        )

        try:
            # Check cache first (only when offset=0)
            if offset == 0:  # Cache first page only
                cached_results = await self.cache_manager.get_cached_search(
                    query=query, project_id=project_id, category=category, limit=limit
                )
                if cached_results:
                    logger.info(
                        f"[Cache HIT] Returning cached results for query: '{query}'"
                    )
                    # Collect metrics even on cache hit
                    await self._collect_search_metric(
                        query=original_query,
                        result=cached_results,
                        start_time=start_time,
                        project_id=project_id,
                        category=category,
                        embedding_time_ms=0,
                        search_time_ms=0,
                    )
                    return cached_results
            # Build SQL filter conditions
            filters = {}
            if project_id:
                filters["project_id"] = project_id
            if category:
                filters["category"] = category
            if source:
                filters["source"] = source
            if tag:
                filters["tag"] = tag

            # Return recent memories for empty query
            if not query.strip():
                raw_results = await self.db.get_recent_memories(
                    limit=limit,
                    offset=offset,
                    sort_by=sort_by,
                    sort_direction=sort_direction,
                    filters=filters,
                )

                # Also fetch total count
                total_count = await self.db.count_memories(filters=filters)

                if not raw_results:
                    logger.info("No recent memories found")
                    return SearchResponse(results=[], total=total_count)

                # Convert results to SearchResult format (recency-based score)
                search_results = []
                if raw_results:
                    # Get time range for recency-based score calculation
                    oldest_time = min(row["created_at"] for row in raw_results)
                    newest_time = max(row["created_at"] for row in raw_results)

                    for row in raw_results:
                        try:
                            # Calculate recency-based score (0.7 ~ 1.0 range)
                            recency_score = self._calculate_recency_score(
                                row["created_at"], oldest_time, newest_time
                            )
                            # Adjust recency score to 0.7 ~ 1.0 range
                            similarity_score = 0.7 + (recency_score * 0.3)

                            search_result = SearchResult(
                                id=row["id"],
                                content=row["content"],
                                similarity_score=similarity_score,
                                created_at=row["created_at"],
                                project_id=row["project_id"],
                                category=row["category"],
                                source=row["source"],
                                client=row["client"] if "client" in row.keys() else None,
                                tags=_parse_tags(row),
                            )
                            search_results.append(search_result)
                        except Exception as e:
                            logger.warning(
                                f"Failed to process recent memory result: {e}"
                            )
                            continue

                logger.info(
                    f"Found {len(search_results)} recent memories (total: {total_count})"
                )
                result = SearchResponse(results=search_results, total=total_count)
                # Collect metrics (empty query search)
                await self._collect_search_metric(
                    query=original_query,
                    result=result,
                    start_time=start_time,
                    project_id=project_id,
                    category=category,
                )
                return result

            # Perform different search based on search mode
            result = None
            if search_mode == "exact":
                logger.info("Using exact text search")
                result = await self._exact_search(query, filters, limit)
            elif search_mode == "semantic":
                logger.info("Using semantic vector search only")
                result = await self._semantic_search(
                    query, filters, limit, recency_weight
                )
            elif search_mode == "fuzzy":
                logger.info("Using fuzzy text search")
                result = await self._fuzzy_search(query, filters, limit)
            else:
                # hybrid (default)
                logger.info("Using hybrid search with sqlite-vec")
                result = await self._vector_search(
                    query, filters, limit, recency_weight
                )

            # Save results to cache (only when offset=0)
            if offset == 0 and result and query.strip():  # Do not cache empty queries
                await self.cache_manager.cache_search_results(
                    query=query,
                    results=result,
                    project_id=project_id,
                    category=category,
                    limit=limit,
                )
                logger.info(
                    f"[Cache] Cached search results for query: '{query[:50]}...'"
                )

            # Collect metrics
            await self._collect_search_metric(
                query=original_query,
                result=result,
                start_time=start_time,
                project_id=project_id,
                category=category,
            )

            return result

        except Exception as e:
            logger.error(f"Search failed: {e}")
            # Collect metrics even on search failure
            result = SearchResponse(results=[])
            await self._collect_search_metric(
                query=original_query,
                result=result,
                start_time=start_time,
                project_id=project_id,
                category=category,
            )
            return result

    def _calculate_recency_score(self, created_at, oldest, newest) -> float:
        """
        최신성 점수 계산 (0.0 ~ 1.0)

        Args:
            created_at: 메모리 생성 시간 (문자열 또는 datetime)
            oldest: 가장 오래된 메모리 시간 (문자열 또는 datetime)
            newest: 가장 최신 메모리 시간 (문자열 또는 datetime)

        Returns:
            float: 최신성 점수 (1.0이 가장 최신)
        """
        try:
            # Convert string to datetime if needed
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if isinstance(oldest, str):
                oldest = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
            if isinstance(newest, str):
                newest = datetime.fromisoformat(newest.replace("Z", "+00:00"))

            # Prevent mixing timezone-aware and timezone-naive datetimes
            # Unify all datetimes as naive (strip tzinfo)
            if hasattr(created_at, "tzinfo") and created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
            if hasattr(oldest, "tzinfo") and oldest.tzinfo is not None:
                oldest = oldest.replace(tzinfo=None)
            if hasattr(newest, "tzinfo") and newest.tzinfo is not None:
                newest = newest.replace(tzinfo=None)

            if oldest == newest:
                return 1.0

            # Calculate time difference in seconds
            total_range = (newest - oldest).total_seconds()
            time_from_oldest = (created_at - oldest).total_seconds()

            if total_range == 0:
                return 1.0

            # Normalize to 0.0 ~ 1.0 range
            recency_score = time_from_oldest / total_range
            return max(0.0, min(1.0, recency_score))

        except Exception as e:
            logger.warning(f"Failed to calculate recency score: {e}")
            return 0.5  # Default value

    async def _vector_search(
        self,
        query: str,
        filters: Optional[dict] = None,
        limit: int = 5,
        recency_weight: float = 0.0,
    ) -> SearchResponse:
        """
        Vector 기반 검색 (sqlite-vec 사용)

        Args:
            query: 검색 쿼리
            filters: 필터 조건
            limit: 결과 개수 제한
            recency_weight: 최신성 가중치

        Returns:
            SearchResponse: 검색 결과
        """
        try:
            # Check cache or generate embedding
            query_embedding_list = await self.cache_manager.get_cached_embedding(query)
            if query_embedding_list is None:
                query_embedding_list = self.embedding_service.embed(
                    query, is_query=True
                )
                await self.cache_manager.cache_embedding(query, query_embedding_list)
                logger.info(
                    f"[Cache MISS] Generated new embedding for query: '{query[:50]}...'"
                )

            query_embedding = self.embedding_service.to_bytes(query_embedding_list)

            # Perform vector search
            raw_results = await self.db.vector_search(
                embedding=query_embedding, limit=limit * 3, filters=filters
            )

            if not raw_results:
                logger.info(
                    "No vector search results found, falling back to text search"
                )
                return await self._text_based_search(query, filters, limit)

            # Configure scoring pipeline
            from .scoring import ScoringContext, ScoringPipeline

            pipeline = ScoringPipeline()
            pipeline.set_recency_weight(recency_weight)

            # Time range for recency score calculation
            if recency_weight > 0.0 and raw_results:
                oldest_time = min(r["created_at"] for r in raw_results)
                newest_time = max(r["created_at"] for r in raw_results)

            # Convert results to SearchResult format
            search_results = []
            for row in raw_results:
                try:
                    content = row["content"].strip()

                    # Vector search provides distance (lower = more similar)
                    if "distance" in row.keys():
                        distance = float(row["distance"])
                        vector_score = max(0.0, min(1.0, 1.0 - (distance / 2.0)))
                    else:
                        vector_score = 0.8

                    # Calculate recency score
                    recency_score = 0.5
                    if recency_weight > 0.0:
                        recency_score = self._calculate_recency_score(
                            row["created_at"], oldest_time, newest_time
                        )

                    # Create scoring context
                    scoring_context = ScoringContext(
                        query=query,
                        content=content,
                        vector_score=vector_score,
                        category=row["category"],
                        project_id=row["project_id"],
                        metadata={"recency_score": recency_score},
                    )

                    # Run scoring pipeline
                    scoring_result = pipeline.calculate(scoring_context)

                    # Skip if excluded
                    if not scoring_result.should_include:
                        logger.debug(f"Excluding result: {scoring_result.reason}")
                        continue

                    search_result = SearchResult(
                        id=row["id"],
                        content=row["content"],
                        similarity_score=scoring_result.final_score,
                        created_at=row["created_at"],
                        project_id=row["project_id"],
                        category=row["category"],
                        source=row["source"],
                        client=row["client"] if "client" in row.keys() else None,
                        tags=_parse_tags(row),
                    )
                    search_results.append(search_result)
                except Exception as e:
                    logger.warning(f"Failed to process vector search result: {e}")
                    continue

            # Sort by score and limit to originally requested count
            search_results.sort(key=lambda x: x.similarity_score, reverse=True)
            search_results = search_results[:limit]

            logger.info(f"Found {len(search_results)} vector search results")
            return SearchResponse(results=search_results)

        except Exception as e:
            logger.error(f"Vector search failed: {e}, falling back to text search")
            return await self._text_based_search(query, filters, limit)

    async def _text_based_search(
        self, query: str, filters: Optional[dict] = None, limit: int = 5
    ) -> SearchResponse:
        """
        텍스트 기반 검색 (벡터 검색이 불가능할 때 사용)

        Args:
            query: 검색 쿼리
            filters: 필터 조건
            limit: 결과 개수 제한

        Returns:
            SearchResponse: 검색 결과
        """
        try:
            # Perform SQL LIKE search
            base_query = "SELECT * FROM memories WHERE content LIKE ?"
            params = [f"%{query}%"]

            # Add filter conditions
            if filters:
                if filters.get("project_id"):
                    base_query += " AND project_id = ?"
                    params.append(filters["project_id"])
                if filters.get("category"):
                    base_query += " AND category = ?"
                    params.append(filters["category"])

            base_query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            raw_results = await self.db.fetchall(base_query, tuple(params))

            if not raw_results:
                logger.info("No text search results found")
                return SearchResponse(results=[])

            # Convert results to SearchResult format
            search_results = []
            for row in raw_results:
                try:
                    # Calculate more precise text matching score
                    content_lower = row["content"].lower()
                    query_lower = query.lower()
                    query_words = query_lower.split()

                    if not query_words:
                        similarity_score = 0.5
                    else:
                        # 1. Exact word matching score
                        matched_words = sum(
                            1 for word in query_words if word in content_lower
                        )
                        word_match_score = matched_words / len(query_words)

                        # 2. Substring matching score
                        substring_matches = sum(
                            1
                            for word in query_words
                            if any(
                                word in content_word
                                for content_word in content_lower.split()
                            )
                        )
                        substring_score = substring_matches / len(query_words)

                        # 3. Check if full query is contained
                        full_query_match = 0.3 if query_lower in content_lower else 0.0

                        # 4. Calculate final score as weighted average
                        similarity_score = (
                            word_match_score * 0.6  # Exact word matching 60%
                            + substring_score * 0.2  # Substring matching 20%
                            + full_query_match * 0.2  # Full query matching 20%
                        )

                        # Adjust score to 0.1 ~ 1.0 range (0.0 is too low)
                        similarity_score = max(0.1, min(1.0, similarity_score))

                    search_result = SearchResult(
                        id=row["id"],
                        content=row["content"],
                        similarity_score=similarity_score,
                        created_at=row["created_at"],
                        project_id=row["project_id"],
                        category=row["category"],
                        source=row["source"],
                        client=row["client"] if "client" in row.keys() else None,
                        tags=_parse_tags(row),
                    )
                    search_results.append(search_result)
                except Exception as e:
                    logger.warning(f"Failed to process text search result: {e}")
                    continue

            # Sort by score
            search_results.sort(key=lambda x: x.similarity_score, reverse=True)

            logger.info(f"Found {len(search_results)} text search results")
            return SearchResponse(results=search_results)

        except Exception as e:
            logger.error(f"Text search failed: {e}")
            return SearchResponse(results=[])

    async def _exact_search(
        self, query: str, filters: Optional[dict] = None, limit: int = 5
    ) -> SearchResponse:
        """
        정확한 텍스트 매칭 검색
        쿼리 문자열이 정확히 포함된 메모리만 반환

        Args:
            query: 검색 쿼리
            filters: 필터 조건
            limit: 결과 개수 제한

        Returns:
            SearchResponse: 검색 결과
        """
        try:
            # Exact string matching (case-insensitive)
            base_query = "SELECT * FROM memories WHERE LOWER(content) LIKE LOWER(?)"
            params = [f"%{query}%"]

            # Add filter conditions
            if filters:
                if filters.get("project_id"):
                    base_query += " AND project_id = ?"
                    params.append(filters["project_id"])
                if filters.get("category"):
                    base_query += " AND category = ?"
                    params.append(filters["category"])

            base_query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            raw_results = await self.db.fetchall(base_query, tuple(params))

            if not raw_results:
                logger.info("No exact search results found")
                return SearchResponse(results=[])

            # Convert results to SearchResult format
            search_results = []
            query_lower = query.lower()

            for row in raw_results:
                try:
                    content_lower = row["content"].lower()

                    # Calculate exact match score
                    # High score if full query is contained
                    if query_lower in content_lower:
                        # Score based on proportion of content covered by query
                        coverage = len(query) / len(row["content"])
                        # Query occurrence count
                        occurrences = content_lower.count(query_lower)
                        similarity_score = min(
                            1.0, 0.7 + (coverage * 0.2) + (occurrences * 0.05)
                        )
                    else:
                        similarity_score = 0.5

                    search_result = SearchResult(
                        id=row["id"],
                        content=row["content"],
                        similarity_score=similarity_score,
                        created_at=row["created_at"],
                        project_id=row["project_id"],
                        category=row["category"],
                        source=row["source"],
                        client=row["client"] if "client" in row.keys() else None,
                        tags=_parse_tags(row),
                    )
                    search_results.append(search_result)
                except Exception as e:
                    logger.warning(f"Failed to process exact search result: {e}")
                    continue

            # Sort by score
            search_results.sort(key=lambda x: x.similarity_score, reverse=True)

            logger.info(f"Found {len(search_results)} exact search results")
            return SearchResponse(results=search_results)

        except Exception as e:
            logger.error(f"Exact search failed: {e}")
            return SearchResponse(results=[])

    async def _semantic_search(
        self,
        query: str,
        filters: Optional[dict] = None,
        limit: int = 5,
        recency_weight: float = 0.0,
    ) -> SearchResponse:
        """
        순수 의미 기반 벡터 검색
        텍스트 매칭 없이 벡터 유사도만 사용

        Args:
            query: 검색 쿼리
            filters: 필터 조건
            limit: 결과 개수 제한
            recency_weight: 최신성 가중치

        Returns:
            SearchResponse: 검색 결과
        """
        try:
            # Check cache or generate embedding
            query_embedding_list = await self.cache_manager.get_cached_embedding(query)
            if query_embedding_list is None:
                query_embedding_list = self.embedding_service.embed(
                    query, is_query=True
                )
                await self.cache_manager.cache_embedding(query, query_embedding_list)
                logger.info(
                    f"[Cache MISS] Generated new embedding for query: '{query[:50]}...'"
                )

            query_embedding = self.embedding_service.to_bytes(query_embedding_list)

            # Perform vector search
            raw_results = await self.db.vector_search(
                embedding=query_embedding, limit=limit, filters=filters
            )

            if not raw_results:
                logger.info("No semantic search results found")
                return SearchResponse(results=[])

            # Convert results to SearchResult format
            search_results = []
            for row in raw_results:
                try:
                    # Vector search provides distance
                    if "distance" in row.keys():
                        distance = float(row["distance"])
                        similarity_score = max(0.0, min(1.0, 1.0 - (distance / 2.0)))
                    else:
                        similarity_score = 0.8

                    # Apply recency weight
                    if recency_weight > 0.0:
                        recency_score = self._calculate_recency_score(
                            row["created_at"],
                            min(r["created_at"] for r in raw_results),
                            max(r["created_at"] for r in raw_results),
                        )
                        similarity_score = (
                            similarity_score * (1.0 - recency_weight)
                            + recency_score * recency_weight
                        )

                    search_result = SearchResult(
                        id=row["id"],
                        content=row["content"],
                        similarity_score=similarity_score,
                        created_at=row["created_at"],
                        project_id=row["project_id"],
                        category=row["category"],
                        source=row["source"],
                        client=row["client"] if "client" in row.keys() else None,
                        tags=_parse_tags(row),
                    )
                    search_results.append(search_result)
                except Exception as e:
                    logger.warning(f"Failed to process semantic search result: {e}")
                    continue

            # Sort by score
            search_results.sort(key=lambda x: x.similarity_score, reverse=True)

            logger.info(f"Found {len(search_results)} semantic search results")
            return SearchResponse(results=search_results)

        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return SearchResponse(results=[])

    async def _fuzzy_search(
        self, query: str, filters: Optional[dict] = None, limit: int = 5
    ) -> SearchResponse:
        """
        퍼지 검색 (오타 허용)
        단어 단위로 유사도를 계산하여 오타가 있어도 매칭

        Args:
            query: 검색 쿼리
            filters: 필터 조건
            limit: 결과 개수 제한

        Returns:
            SearchResponse: 검색 결과
        """
        try:
            # Fetch all memories first (apply filters)
            base_query = "SELECT * FROM memories WHERE 1=1"
            params = []

            if filters:
                if filters.get("project_id"):
                    base_query += " AND project_id = ?"
                    params.append(filters["project_id"])
                if filters.get("category"):
                    base_query += " AND category = ?"
                    params.append(filters["category"])

            # Fetch more results for fuzzy matching
            base_query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit * 10)  # Fetch more, then filter down

            raw_results = await self.db.fetchall(base_query, tuple(params))

            if not raw_results:
                logger.info("No memories found for fuzzy search")
                return SearchResponse(results=[])

            # Calculate fuzzy matching score
            query_words = query.lower().split()
            scored_results = []

            for row in raw_results:
                try:
                    content_lower = row["content"].lower()
                    content_words = content_lower.split()

                    # Find the most similar content word for each query word
                    total_score = 0.0
                    matched_words = 0

                    for query_word in query_words:
                        best_match_score = 0.0

                        for content_word in content_words:
                            # Calculate similarity with SequenceMatcher
                            ratio = SequenceMatcher(
                                None, query_word, content_word
                            ).ratio()
                            if ratio > best_match_score:
                                best_match_score = ratio

                        # Consider matched if similarity >= 0.6 (allows typos)
                        if best_match_score >= 0.6:
                            matched_words += 1
                            total_score += best_match_score

                    if matched_words > 0:
                        # Average similarity score
                        avg_score = total_score / len(query_words)
                        # Reflect matched word ratio
                        match_ratio = matched_words / len(query_words)
                        final_score = (avg_score * 0.6) + (match_ratio * 0.4)

                        scored_results.append((row, final_score))

                except Exception as e:
                    logger.warning(f"Failed to process fuzzy search result: {e}")
                    continue

            # Sort by score and return top results only
            scored_results.sort(key=lambda x: x[1], reverse=True)
            top_results = scored_results[:limit]

            search_results = []
            for row, score in top_results:
                search_result = SearchResult(
                    id=row["id"],
                    content=row["content"],
                    similarity_score=score,
                    created_at=row["created_at"],
                    project_id=row["project_id"],
                    category=row["category"],
                    source=row["source"],
                    client=row["client"] if "client" in row.keys() else None,
                    tags=_parse_tags(row),
                )
                search_results.append(search_result)

            logger.info(f"Found {len(search_results)} fuzzy search results")
            return SearchResponse(results=search_results)

        except Exception as e:
            logger.error(f"Fuzzy search failed: {e}")
            return SearchResponse(results=[])

    async def _collect_search_metric(
        self,
        query: str,
        result: SearchResponse,
        start_time: float,
        project_id: Optional[str] = None,
        category: Optional[str] = None,
        embedding_time_ms: Optional[int] = None,
        search_time_ms: Optional[int] = None,
    ) -> None:
        """
        검색 메트릭 수집 헬퍼 메서드

        Args:
            query: 검색 쿼리
            result: 검색 결과
            start_time: 검색 시작 시간 (time.perf_counter())
            project_id: 프로젝트 ID
            category: 카테고리
            embedding_time_ms: 임베딩 생성 시간 (ms)
            search_time_ms: 검색 시간 (ms)
        """
        if self.metrics_collector is None:
            logger.warning("MetricsCollector is None - metrics will not be collected")
            return

        logger.info(
            f"[METRICS] Collecting search metric for query: '{query[:50]}...' (results: {len(result.results)})"
        )

        try:
            # Calculate total response time
            response_time_ms = int((time.perf_counter() - start_time) * 1000)

            # Calculate similarity score
            avg_similarity = None
            top_similarity = None
            if result.results:
                scores = [
                    r.similarity_score
                    for r in result.results
                    if r.similarity_score is not None
                ]
                if scores:
                    avg_similarity = sum(scores) / len(scores)
                    top_similarity = max(scores)

            await self.metrics_collector.collect_search_metric(
                query=query,
                result_count=len(result.results),
                response_time_ms=response_time_ms,
                avg_similarity=avg_similarity,
                top_similarity=top_similarity,
                project_id=project_id,
                category=category,
                embedding_time_ms=embedding_time_ms,
                search_time_ms=search_time_ms,
                source="search_service",
            )
            logger.info(
                f"[METRICS] Successfully collected search metric (response_time: {response_time_ms}ms, results: {len(result.results)})"
            )
        except Exception as e:
            # Metric collection failure does not affect search results
            logger.error(
                f"[METRICS] Failed to collect search metric: {e}", exc_info=True
            )
