"""
Unified Search Service - 통합 검색 서비스
모든 검색 기능을 하나로 통합한 서비스

기존 5개 구현의 장점을 모두 통합:
- search.py: 하이브리드 검색, 캐싱
- enhanced_search.py: 품질 최적화, 의도 분석
- improved_search.py: 한국어 최적화
- final_improved_search.py: 한영 번역
- simple_improved_search.py: 간단한 한영 변환
"""

import asyncio
import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import sqlite3

if TYPE_CHECKING:
    from .search_quality import SearchIntent

from ..database.base import Database
from ..embeddings.service import EmbeddingService
from ..schemas.responses import SearchResponse, SearchResult
from .cache_manager import get_cache_manager
from .noise_filter import SmartSearchFilter
from .query_expander import get_query_expander
from .score_normalizer import get_score_normalizer
from .scoring import ScoringContext, ScoringPipeline

if TYPE_CHECKING:
    from .metrics_collector import MetricsCollector

logger = logging.getLogger(__name__)


class UnifiedSearchService:
    """통합 검색 서비스 - 모든 검색 기능을 하나로"""

    def __init__(
        self,
        db: Database,
        embedding_service: EmbeddingService,
        metrics_collector: Optional["MetricsCollector"] = None,
        enable_quality_features: bool = True,
        enable_korean_optimization: bool = True,
        enable_noise_filter: bool = True,
        enable_score_normalization: bool = True,
        score_normalization_method: str = "sigmoid",
        cache_embedding_ttl: Optional[int] = None,
        cache_search_ttl: Optional[int] = None,
        cache_context_ttl: Optional[int] = None,
        enable_reranking: bool = False,
        reranking_model: Optional[str] = None,
        reranking_top_k_multiplier: int = 3,
    ):
        """
        Args:
            db: Database instance
            embedding_service: Embedding service
            metrics_collector: Metrics collector (optional)
            enable_quality_features: Enable quality scoring and intent analysis
            enable_korean_optimization: Enable Korean language optimization
            enable_noise_filter: Enable noise filtering
            enable_score_normalization: Enable score normalization
            score_normalization_method: Normalization method (sigmoid/minmax/zscore/percentile)
            cache_embedding_ttl: Embedding cache TTL in seconds (default: 24 hours)
            cache_search_ttl: Search cache TTL in seconds (default: 1 hour)
            cache_context_ttl: Context cache TTL in seconds (default: 30 minutes)
        """
        self.db = db
        self.embedding_service = embedding_service
        self.metrics_collector = metrics_collector

        # Feature flags
        self.enable_quality_features = enable_quality_features
        self.enable_korean_optimization = enable_korean_optimization
        self.enable_noise_filter = enable_noise_filter
        self.enable_score_normalization = enable_score_normalization

        # Core components
        self.cache_manager = get_cache_manager(
            embedding_ttl=cache_embedding_ttl,
            search_ttl=cache_search_ttl,
            context_ttl=cache_context_ttl,
        )
        self.scoring_pipeline = ScoringPipeline()

        # Optional components
        self.noise_filter = SmartSearchFilter() if enable_noise_filter else None
        self.query_expander = (
            get_query_expander() if enable_korean_optimization else None
        )
        self.intent_analyzer = None
        self.score_normalizer = (
            get_score_normalizer(score_normalization_method)
            if enable_score_normalization
            else None
        )

        # Load quality components if enabled
        self.quality_scorer = None
        if enable_quality_features:
            try:
                from .search_quality import SearchIntentAnalyzer, SearchQualityScorer

                self.intent_analyzer = SearchIntentAnalyzer()
                self.quality_scorer = SearchQualityScorer()
                logger.info(
                    "Quality features enabled (intent analyzer + quality scorer)"
                )
            except ImportError:
                logger.warning(
                    "SearchIntentAnalyzer not available, quality features disabled"
                )
                self.enable_quality_features = False

        # Reranking
        self.enable_reranking = enable_reranking
        self.reranking_top_k_multiplier = reranking_top_k_multiplier
        self.reranker = None
        if enable_reranking:
            try:
                from .reranker import RerankerService

                self.reranker = RerankerService(
                    model_name=reranking_model or "cross-encoder/ms-marco-MiniLM-L6-v2",
                    preload=True,
                )
                logger.info(
                    "Reranking enabled with %s", reranking_model or "default model"
                )
            except Exception as e:
                logger.warning("Failed to initialize reranker: %s", e)
                self.enable_reranking = False

        # RRF weights from config
        try:
            from ..config import get_settings

            _settings = get_settings()
            self._rrf_vector_weight = _settings.rrf_vector_weight
            self._rrf_text_weight = _settings.rrf_text_weight
        except Exception as e:
            logger.debug(f"Failed to load RRF weights from settings, using defaults: {e}")
            self._rrf_vector_weight = 1.0
            self._rrf_text_weight = 1.2

        # Korean translation dictionary
        self.korean_translations = self._init_korean_translations()

        logger.info(
            f"UnifiedSearchService initialized - "
            f"Quality: {enable_quality_features}, "
            f"Korean: {enable_korean_optimization}, "
            f"NoiseFilter: {enable_noise_filter}, "
            f"ScoreNorm: {enable_score_normalization} ({score_normalization_method}), "
            f"RRF weights: vector={self._rrf_vector_weight}, text={self._rrf_text_weight}"
        )

    def _init_korean_translations(self) -> Dict[str, List[str]]:
        """한영 번역 사전 초기화"""
        return {
            # Korean → English
            "토큰": ["token", "tokens"],
            "최적화": ["optimization", "optimize", "optimized"],
            "검색": ["search", "searching", "query"],
            "품질": ["quality", "quality improvement"],
            "캐시": ["cache", "caching", "cached"],
            "캐싱": ["caching", "cache"],
            "임베딩": ["embedding", "embeddings", "vector"],
            "배치": ["batch", "batching"],
            "의도": ["intent", "intention"],
            "분석": ["analysis", "analyze", "analyzer"],
            "관리": ["management", "manage", "manager"],
            "필터": ["filter", "filtering"],
            "노이즈": ["noise"],
            "스코어": ["score", "scoring"],
            # English → Korean
            "token": ["토큰"],
            "optimization": ["최적화"],
            "search": ["검색"],
            "quality": ["품질"],
            "cache": ["캐시", "캐싱"],
            "embedding": ["임베딩"],
            "batch": ["배치"],
            "intent": ["의도"],
            "analysis": ["분석"],
            "filter": ["필터"],
            "noise": ["노이즈"],
            "score": ["스코어"],
        }

    async def search(
        self,
        query: str,
        project_id: Optional[str] = None,
        category: Optional[str] = None,
        source: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
        sort_by: str = "relevance",
        sort_direction: str = "desc",
        recency_weight: float = 0.0,
        search_mode: str = "smart",
        min_quality_score: float = 0.3,
        time_range: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        temporal_mode: str = "boost",
    ) -> SearchResponse:
        """
        통합 검색 수행

        Args:
            query: 검색 쿼리
            project_id: 프로젝트 필터
            category: 카테고리 필터
            source: 소스 필터
            tag: 태그 필터
            limit: 결과 개수
            offset: 오프셋
            sort_by: 정렬 기준 (relevance/created_at/quality)
            sort_direction: 정렬 방향
            recency_weight: 최신성 가중치 (0.0-1.0)
            search_mode: 검색 모드 (smart/hybrid/exact/semantic/fuzzy)
            min_quality_score: 최소 품질 점수
            time_range: 시간 범위 단축어 (today/this_week/this_month 등)
            date_from: 시작 날짜 (YYYY-MM-DD)
            date_to: 종료 날짜 (YYYY-MM-DD)
            temporal_mode: 시간 모드 (filter/boost/decay)

        Returns:
            SearchResponse: 검색 결과
        """
        start_time = time.perf_counter()

        # Handle URL-encoded spaces (+) and normalize
        # FastAPI does not auto-convert '+' to space, so handle manually
        query = query.replace("+", " ").strip() if query else ""
        original_query = query

        # 1. Intent analysis (when quality feature is enabled)
        intent = None
        if self.enable_quality_features and self.intent_analyzer and query:
            intent = self.intent_analyzer.analyze(query)
            logger.info(
                f"Query intent: {intent.intent_type}, "
                f"urgency: {intent.urgency:.2f}, "
                f"specificity: {intent.specificity:.2f}"
            )

            # Auto-adjust parameters based on intent
            if search_mode == "smart":
                search_mode, limit, category = self._auto_adjust_params(
                    intent, search_mode, limit, category
                )

        # 2. Query expansion (when Korean optimization is enabled)
        expanded_query = query
        if self.enable_korean_optimization and query and search_mode != "exact":
            expanded_query = self._expand_query(query)
            if expanded_query != query:
                logger.info(f"Query expanded: '{query}' → '{expanded_query[:100]}...'")

        # 3. Check cache (only when offset=0)
        if offset == 0 and query:
            cached_results = await self.cache_manager.get_cached_search(
                query=expanded_query,
                project_id=project_id,
                category=category,
                limit=limit,
            )
            if cached_results:
                logger.info(
                    f"[Cache HIT] Returning cached results for query: '{query}'"
                )
                return cached_results

        # 4. Build filter conditions
        filters = {}
        if project_id:
            filters["project_id"] = project_id
        if category:
            filters["category"] = category
        if source:
            filters["source"] = source
        if tag:
            filters["tag"] = tag

        # Check if query is empty (to decide whether to skip post-processing)
        is_empty_query = not query.strip()

        # 5. Perform search based on search mode
        if is_empty_query:
            # Empty query: return recent memories (skip noise/quality/normalization)
            result = await self._get_recent_memories(
                filters, limit, offset, sort_by, sort_direction
            )
            # Apply temporal filter even for empty query
            if result.results and (
                time_range or date_from or date_to or temporal_mode == "decay"
            ):
                result = self._apply_temporal(
                    result, time_range, date_from, date_to, temporal_mode
                )
            search_time = time.perf_counter() - start_time
            logger.info(
                f"Recent memories returned in {search_time:.3f}s - "
                f"results: {len(result.results)}"
            )
            return result
        elif search_mode == "exact":
            result = await self._exact_search(expanded_query, filters, limit)
        elif search_mode == "semantic":
            result = await self._semantic_search(
                expanded_query, filters, limit, recency_weight
            )
        elif search_mode == "fuzzy":
            result = await self._fuzzy_search(expanded_query, filters, limit)
        else:
            # hybrid or smart (default)
            result = await self._hybrid_search(
                expanded_query, filters, limit, recency_weight
            )

        # 5.5 Reranking (when reranking is enabled — recalculate precise scores)
        if self.reranker and result.results:
            result = self._apply_reranking(result, original_query, limit)

        # 6. Temporal filter/boost/decay (Temporal-Aware Search)
        if result.results and (
            time_range or date_from or date_to or temporal_mode == "decay"
        ):
            result = self._apply_temporal(
                result, time_range, date_from, date_to, temporal_mode
            )

        # 7. Quality scoring and reranking (when quality feature is enabled)
        if self.enable_quality_features and result.results and intent:
            result = await self._apply_quality_scoring(
                result, original_query, intent, min_quality_score, sort_by
            )

        # 7. Noise filtering (when enabled)
        if self.enable_noise_filter and self.noise_filter and result.results:
            context = {
                "project": project_id,
                "max_results": limit,
                "aggressive_filter": False,
            }
            result = self.noise_filter.apply(result, original_query, context)

        # 8. Project name match boosting (applied before normalization)
        if result.results and original_query:
            result = self._boost_project_name_match(original_query, result)

        # 9. Score normalization (when enabled)
        if self.enable_score_normalization and self.score_normalizer and result.results:
            # Extract all scores
            scores = [
                r.similarity_score
                for r in result.results
                if r.similarity_score is not None
            ]

            if scores:
                # Perform normalization
                normalized_scores = self.score_normalizer.normalize(scores)

                # Apply normalized scores
                for i, res in enumerate(result.results):
                    if res.similarity_score is not None and i < len(normalized_scores):
                        res.similarity_score = normalized_scores[i]

                logger.debug(f"Scores normalized: {len(scores)} scores")

        # 9. Save to cache (only when offset=0)
        if offset == 0 and query and result.results:
            await self.cache_manager.cache_search_results(
                query=expanded_query,
                results=result,
                project_id=project_id,
                category=category,
                limit=limit,
            )

        # 9. Log search duration
        search_time = time.perf_counter() - start_time
        logger.info(
            f"Search completed in {search_time:.3f}s - "
            f"mode: {search_mode}, "
            f"results: {len(result.results)}, "
            f"quality: {self.enable_quality_features}, "
            f"korean: {self.enable_korean_optimization}"
        )

        # 10. Log intent analysis result
        if intent:
            logger.debug(
                f"Intent analysis: type={intent.intent_type}, "
                f"urgency={intent.urgency}, specificity={intent.specificity}"
            )

        # 11. Collect metrics
        await self._collect_metrics(
            original_query, result, start_time, project_id, category
        )

        # 12. Generate suggestions on empty/low-quality results
        if original_query and (
            not result.results
            or (
                result.results and max(r.similarity_score for r in result.results) < 0.3
            )
        ):
            result.suggestions = self._generate_suggestions(original_query, project_id)

        # 13. Expand with relation graph (supplement only when results are sparse)
        if result.results and len(result.results) < 3:
            related = await self._expand_with_relations(result, limit=3)
            if related:
                result.related_memories = related

        logger.info(
            f"Search completed: query='{original_query[:50]}...', "
            f"results={len(result.results)}, time={search_time:.3f}s"
        )

        return result

    def _expand_query(self, query: str) -> str:
        """쿼리 확장 (한영 번역 + Query Expander)"""
        expanded_terms = set([query])

        # 1. Use Query Expander (if available)
        if self.query_expander:
            try:
                expanded = self.query_expander.expand_query(query)
                if expanded != query:
                    expanded_terms.add(expanded)
            except Exception as e:
                logger.warning(f"Query expander failed: {e}")

        # 2. Add Korean-English translation (only for Korean queries)
        if self.enable_korean_optimization and self._is_korean(query):
            words = query.lower().split()
            for word in words:
                if word in self.korean_translations:
                    expanded_terms.update(self.korean_translations[word])

        # 3. Combine
        if len(expanded_terms) > 1:
            return " ".join(expanded_terms)
        return query

    def _auto_adjust_params(
        self, intent: "SearchIntent", search_mode: str, limit: int, category: Optional[str]
    ) -> tuple:
        """의도 기반 파라미터 자동 조정"""
        # Adjust search mode
        if intent.intent_type == "debug":
            search_mode = "exact"
        elif intent.intent_type == "explore":
            search_mode = "semantic"
        elif intent.specificity > 0.7:
            search_mode = "exact"
        else:
            search_mode = "hybrid"

        # Adjust result count
        if intent.urgency > 0.8:
            limit = min(limit, 5)
        elif intent.specificity > 0.8:
            limit = min(limit, 3)
        elif intent.intent_type == "explore":
            limit = max(limit, 10)

        # Predict category
        if not category and intent.expected_category:
            category = intent.expected_category

        return search_mode, limit, category

    async def _get_recent_memories(
        self,
        filters: Dict[str, Any],
        limit: int,
        offset: int,
        sort_by: str,
        sort_direction: str,
    ) -> SearchResponse:
        """최근 메모리 조회"""
        raw_results = await self.db.get_recent_memories(
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_direction=sort_direction,
            filters=filters,
        )

        total_count = await self.db.count_memories(filters=filters)

        if not raw_results:
            return SearchResponse(results=[], total=total_count)

        # Convert to SearchResult
        search_results = []
        oldest_time = min(row["created_at"] for row in raw_results)
        newest_time = max(row["created_at"] for row in raw_results)

        for row in raw_results:
            recency_score = self._calculate_recency_score(
                row["created_at"], oldest_time, newest_time
            )
            similarity_score = 0.7 + (recency_score * 0.3)

            search_results.append(
                SearchResult(
                    id=row["id"],
                    content=row["content"],
                    similarity_score=similarity_score,
                    created_at=row["created_at"],
                    project_id=row["project_id"],
                    category=row["category"],
                    source=row["source"],
                    client=row["client"] if "client" in row.keys() else None,
                    tags=self._parse_tags(row),
                )
            )

        return SearchResponse(results=search_results, total=total_count)

    async def _hybrid_search(
        self, query: str, filters: Dict[str, Any], limit: int, recency_weight: float
    ) -> SearchResponse:
        """
        RRF 기반 하이브리드 검색 (벡터 + 텍스트 병렬 수행)
        """
        # 1. Generate embedding (use cache; is_query=True for search queries)
        query_embedding_list = await self.cache_manager.get_cached_embedding(query)
        if query_embedding_list is None:
            query_embedding_list = self.embedding_service.embed(query, is_query=True)
            await self.cache_manager.cache_embedding(query, query_embedding_list)

        query_embedding = self.embedding_service.to_bytes(query_embedding_list)

        # 2. Perform parallel search (Vector + Text)
        # Get wider candidate pool when reranking is enabled (topk * multiplier)
        if self.reranker:
            search_limit = limit * self.reranking_top_k_multiplier
        else:
            search_limit = limit * 2  # 2x candidates by default for RRF

        # Vector Search Task
        vector_task = self.db.vector_search(
            embedding=query_embedding, limit=search_limit, filters=filters
        )

        # Text Search Task (Exact Match)
        text_task = self._exact_search(query, filters, search_limit)

        # Wait for both
        raw_vector_results, text_response = await asyncio.gather(vector_task, text_task)

        # 3. Process vector results (score calculation)
        vector_search_results = []
        if raw_vector_results:
            self.scoring_pipeline.set_recency_weight(recency_weight)
            for row in raw_vector_results:
                try:
                    distance = float(row["distance"])
                except (KeyError, IndexError, TypeError):
                    distance = 1.0

                vector_score = max(0.0, min(1.0, 1.0 - (distance / 2.0)))

                context = ScoringContext(
                    query=query,
                    content=row["content"],
                    vector_score=vector_score,
                    category=row["category"],
                    project_id=row["project_id"],
                    tags=self._parse_tags(row),
                    metadata={
                        "recency_score": self._absolute_recency_score(row["created_at"])
                    },
                )

                scoring_result = self.scoring_pipeline.calculate(context)
                if scoring_result.should_include:
                    vector_search_results.append(
                        SearchResult(
                            id=row["id"],
                            content=row["content"],
                            similarity_score=scoring_result.final_score,
                            created_at=row["created_at"],
                            project_id=row["project_id"],
                            category=row["category"],
                            source=row["source"],
                            client=row["client"] if "client" in row.keys() else None,
                            tags=self._parse_tags(row),
                        )
                    )

        # 4. RRF merge
        if not vector_search_results and not text_response.results:
            return SearchResponse(results=[])

        merged_results = self._apply_rrf(
            vector_search_results, text_response.results, limit
        )

        return SearchResponse(results=merged_results, total=len(merged_results))

    def _absolute_recency_score(self, created_at: Optional[str]) -> float:
        """created_at 기반 절대 최신성 점수 (지수 감쇠: 오늘=1.0, 7일≈0.79, 30일≈0.37)"""
        if not created_at:
            return 0.5
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - created).days
            return max(0.0, min(1.0, math.exp(-age_days / 30.0)))
        except Exception as e:
            logger.debug(f"Failed to calculate recency score: {e}")
            return 0.5

    def _is_korean(self, text: str) -> bool:
        """쿼리에 한국어가 포함되어 있는지 확인"""
        for char in text:
            if "가" <= char <= "힣":
                return True
        return False

    def _apply_rrf(
        self,
        vector_results: List[SearchResult],
        text_results: List[SearchResult],
        limit: int,
        k: int = 60,
        vector_weight: Optional[float] = None,
        text_weight: Optional[float] = None,
    ) -> List[SearchResult]:
        """
        Reciprocal Rank Fusion 알고리즘 적용
        Score = weight * (1 / (k + rank))

        RRF는 순위 결정에만 사용하고, 최종 점수는 원래 벡터 유사도를 유지.
        text_weight > vector_weight 이면 키워드 정확 매칭을 우대 (작은 모델에 유리).
        """
        if vector_weight is None:
            vector_weight = self._rrf_vector_weight
        if text_weight is None:
            text_weight = self._rrf_text_weight

        rrf_scores: Dict[str, float] = {}
        content_map: Dict[str, SearchResult] = {}
        original_scores: Dict[str, float] = {}

        # Accumulate Vector Results scores
        for rank, item in enumerate(vector_results):
            if item.id not in content_map:
                content_map[item.id] = item
                original_scores[item.id] = item.similarity_score
            rrf_scores[item.id] = rrf_scores.get(item.id, 0) + vector_weight * (
                1.0 / (k + rank + 1)
            )

        # Accumulate Text Results scores
        for rank, item in enumerate(text_results):
            if item.id not in content_map:
                content_map[item.id] = item
                original_scores[item.id] = item.similarity_score
            rrf_scores[item.id] = rrf_scores.get(item.id, 0) + text_weight * (
                1.0 / (k + rank + 1)
            )
            if item.id in original_scores:
                original_scores[item.id] = min(1.0, original_scores[item.id] + 0.1)

        # Sort by RRF score
        sorted_ids = sorted(
            rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True
        )

        final_results = []
        for doc_id in sorted_ids[:limit]:
            item = content_map[doc_id]
            item.similarity_score = original_scores.get(doc_id, 0.5)
            final_results.append(item)

        return final_results

    def _apply_reranking(
        self,
        response: SearchResponse,
        query: str,
        limit: int,
    ) -> SearchResponse:
        """Cross-Encoder 리랭킹 적용.

        1단계 검색(bi-encoder + RRF)의 후보를 Cross-Encoder로 정밀 재점수화한 뒤
        상위 limit개만 반환한다.
        """
        if not self.reranker or not response.results:
            return response

        documents = [r.content for r in response.results]
        rerank_results = self.reranker.rerank(query, documents, top_k=limit)

        reranked: List[SearchResult] = []
        for rr in rerank_results:
            item = response.results[rr.original_index]
            # Use Cross-Encoder score as final similarity_score
            item.similarity_score = rr.score
            reranked.append(item)

        logger.info(
            "Reranking applied: %d candidates → %d results (top=%.3f)",
            len(documents),
            len(reranked),
            reranked[0].similarity_score if reranked else 0,
        )

        return SearchResponse(results=reranked, total=len(reranked))

    def _split_korean_compound(self, token: str) -> List[str]:
        """
        한국어 복합어를 가능한 서브토큰으로 분해.

        unicode61 토크나이저는 공백 없는 한국어 복합어를 하나의 토큰으로 처리하므로,
        2~3음절 단위로 분해하여 OR 검색이 가능하게 함.
        예: "토큰최적화" → ["토큰최적화", "토큰", "최적화", "토큰최", "적화"]
        """
        korean_chars = [c for c in token if "가" <= c <= "힣"]
        if len(korean_chars) < 4:
            return [token]

        sub_tokens = {token}
        n = len(token)
        for size in (2, 3):
            for i in range(n - size + 1):
                chunk = token[i : i + size]
                if any("가" <= c <= "힣" for c in chunk) and len(chunk) >= 2:
                    sub_tokens.add(chunk)
        return list(sub_tokens)

    async def _exact_search(
        self, query: str, filters: Dict[str, Any], limit: int
    ) -> SearchResponse:
        """정확한 텍스트 매칭 검색"""
        # Prepare FTS Query
        clean = query.replace('"', '""')
        tokens = clean.split()
        if not tokens:
            return SearchResponse(results=[])

        # Decompose Korean compound words: expand each token to sub-tokens
        if self.enable_korean_optimization:
            expanded_token_groups = []
            for t in tokens:
                subs = self._split_korean_compound(t)
                if len(subs) > 1:
                    expanded_token_groups.append(
                        "(" + " OR ".join(f'"{s}"' for s in subs) + ")"
                    )
                else:
                    expanded_token_groups.append(f'"{t}"')
            fts_query = " AND ".join(expanded_token_groups)
        else:
            fts_query = " AND ".join([f'"{t}"' for t in tokens])

        # Execute FTS query
        sql = """
            SELECT m.id, m.content, m.created_at, m.project_id, m.category, m.source, m.client, m.tags
            FROM memories_fts fts
            JOIN memories m ON fts.id = m.id
            WHERE fts.memories_fts MATCH ?
        """
        params = [fts_query]

        if filters:
            if filters.get("project_id"):
                sql += " AND m.project_id = ?"
                params.append(filters["project_id"])
            if filters.get("category"):
                sql += " AND m.category = ?"
                params.append(filters["category"])

        sql += " ORDER BY fts.rank LIMIT ?"
        params.append(limit)

        try:
            rows = await self.db.fetchall(sql, tuple(params))

            results = []
            # Calculate score based on FTS rank (0.9 ~ 0.7 range by rank)
            for i, row in enumerate(rows):
                # Text match gets high score but not 1.0
                text_score = max(0.7, 0.9 - (i * 0.02))
                results.append(
                    SearchResult(
                        id=row["id"],
                        content=row["content"],
                        similarity_score=text_score,
                        created_at=row["created_at"],
                        project_id=row["project_id"],
                        category=row["category"],
                        source=row["source"],
                        client=row["client"] if "client" in row.keys() else None,
                        tags=self._parse_tags(row),
                    )
                )

            return SearchResponse(results=results, total=len(results))

        except Exception as e:
            # FTS failure (missing table etc.) — return empty so vector search still runs
            logger.debug(f"FTS search failed, returning empty results: {e}")
            return SearchResponse(results=[])

    async def _semantic_search(
        self, query: str, filters: Dict[str, Any], limit: int, recency_weight: float
    ) -> SearchResponse:
        """순수 의미 기반 벡터 검색"""
        # Generate embedding (is_query=True since this is a search query)
        query_embedding_list = await self.cache_manager.get_cached_embedding(query)
        if query_embedding_list is None:
            query_embedding_list = self.embedding_service.embed(query, is_query=True)
            await self.cache_manager.cache_embedding(query, query_embedding_list)

        query_embedding = self.embedding_service.to_bytes(query_embedding_list)

        # Vector search
        raw_results = await self.db.vector_search(
            embedding=query_embedding, limit=limit, filters=filters
        )

        if not raw_results:
            return SearchResponse(results=[])

        search_results = []
        for row in raw_results:
            try:
                distance = float(row["distance"])
            except (KeyError, IndexError, TypeError):
                distance = 1.0

            similarity_score = max(0.0, min(1.0, 1.0 - (distance / 2.0)))

            # Apply recency weight
            if recency_weight > 0.0:
                recency_score = self._absolute_recency_score(row["created_at"])
                similarity_score = (
                    similarity_score * (1.0 - recency_weight)
                    + recency_score * recency_weight
                )

            search_results.append(
                SearchResult(
                    id=row["id"],
                    content=row["content"],
                    similarity_score=similarity_score,
                    created_at=row["created_at"],
                    project_id=row["project_id"],
                    category=row["category"],
                    source=row["source"],
                    client=row["client"] if "client" in row.keys() else None,
                    tags=self._parse_tags(row),
                )
            )

        # Primary: similarity_score descending, secondary: created_at descending (stable sort)
        search_results.sort(
            key=lambda x: (x.similarity_score, x.created_at or ""), reverse=True
        )
        return SearchResponse(results=search_results, total=len(search_results))

    async def _fuzzy_search(
        self, query: str, filters: Dict[str, Any], limit: int
    ) -> SearchResponse:
        """퍼지 검색 (오타 허용)"""
        from difflib import SequenceMatcher

        # Fetch all memories
        base_query = "SELECT * FROM memories WHERE 1=1"
        params = []

        if filters:
            if filters.get("project_id"):
                base_query += " AND project_id = ?"
                params.append(filters["project_id"])
            if filters.get("category"):
                base_query += " AND category = ?"
                params.append(filters["category"])

        base_query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit * 10)

        raw_results = await self.db.fetchall(base_query, tuple(params))

        if not raw_results:
            return SearchResponse(results=[])

        # Fuzzy matching
        query_words = query.lower().split()
        scored_results = []

        for row in raw_results:
            content_lower = row["content"].lower()
            content_words = content_lower.split()

            total_score = 0.0
            matched_words = 0

            for query_word in query_words:
                best_match_score = 0.0
                for content_word in content_words:
                    ratio = SequenceMatcher(None, query_word, content_word).ratio()
                    if ratio > best_match_score:
                        best_match_score = ratio

                if best_match_score >= 0.6:
                    matched_words += 1
                    total_score += best_match_score

            if matched_words > 0:
                avg_score = total_score / len(query_words)
                match_ratio = matched_words / len(query_words)
                final_score = (avg_score * 0.6) + (match_ratio * 0.4)

                scored_results.append((row, final_score))

        # Sort and limit (primary: score descending, secondary: created_at descending)
        scored_results.sort(
            key=lambda x: (x[1], x[0]["created_at"] or ""), reverse=True
        )
        scored_results = scored_results[:limit]

        search_results = []
        for row, score in scored_results:
            search_results.append(
                SearchResult(
                    id=row["id"],
                    content=row["content"],
                    similarity_score=score,
                    created_at=row["created_at"],
                    project_id=row["project_id"],
                    category=row["category"],
                    source=row["source"],
                    client=row["client"] if "client" in row.keys() else None,
                    tags=self._parse_tags(row),
                )
            )

        return SearchResponse(results=search_results, total=len(search_results))

    async def _text_search(
        self, query: str, filters: Dict[str, Any], limit: int
    ) -> SearchResponse:
        """텍스트 기반 검색 (폴백)"""
        base_query = "SELECT * FROM memories WHERE content LIKE ?"
        params = [f"%{query}%"]

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
            return SearchResponse(results=[])

        search_results = []
        for row in raw_results:
            content_lower = row["content"].lower()
            query_lower = query.lower()
            query_words = query_lower.split()

            matched_words = sum(1 for word in query_words if word in content_lower)
            similarity_score = matched_words / len(query_words) if query_words else 0.5
            similarity_score = max(0.1, min(1.0, similarity_score))

            search_results.append(
                SearchResult(
                    id=row["id"],
                    content=row["content"],
                    similarity_score=similarity_score,
                    created_at=row["created_at"],
                    project_id=row["project_id"],
                    category=row["category"],
                    source=row["source"],
                    client=row["client"] if "client" in row.keys() else None,
                    tags=self._parse_tags(row),
                )
            )

        # Primary: similarity_score descending, secondary: created_at descending (stable sort)
        search_results.sort(
            key=lambda x: (x.similarity_score, x.created_at or ""), reverse=True
        )
        return SearchResponse(results=search_results, total=len(search_results))

    async def _apply_quality_scoring(
        self,
        result: SearchResponse,
        query: str,
        intent: "SearchIntent",
        min_quality_score: float,
        sort_by: str,
    ) -> SearchResponse:
        """품질 스코어링 적용 - SearchQualityScorer 활용"""
        if not self.quality_scorer or not result.results:
            return result

        try:
            results_as_dicts = [
                {
                    "id": r.id,
                    "content": r.content,
                    "similarity_score": r.similarity_score,
                    "created_at": r.created_at,
                    "project_id": r.project_id,
                    "category": r.category,
                    "source": r.source,
                    "client": r.client,
                    "tags": r.tags or [],
                }
                for r in result.results
            ]

            scored = self.quality_scorer.score_results(query, results_as_dicts)

            reranked = []
            for item in scored:
                quality = item.get("quality_score", 0.0)
                if quality < min_quality_score:
                    continue
                reranked.append(
                    SearchResult(
                        id=item["id"],
                        content=item["content"],
                        similarity_score=item.get(
                            "quality_score", item.get("similarity_score", 0.0)
                        ),
                        created_at=item.get("created_at", ""),
                        project_id=item.get("project_id"),
                        category=item.get("category", ""),
                        source=item.get("source", ""),
                        client=item.get("client"),
                        tags=item.get("tags"),
                    )
                )

            return SearchResponse(results=reranked, total=len(reranked))
        except Exception as e:
            logger.warning(f"Quality scoring failed, returning original results: {e}")
            return result

    def _generate_suggestions(
        self, query: str, project_id: Optional[str] = None
    ) -> List[str]:
        """빈 결과 또는 저품질 결과 시 검색 제안 생성"""
        suggestions = []

        if self.query_expander:
            try:
                terms = self.query_expander.suggest_terms(query)
                suggestions.extend(terms)
            except Exception as e:
                logger.debug(f"Failed to get query expansion suggestions: {e}")

        category_hints = ["bug", "decision", "task", "code_snippet", "incident"]
        if self.intent_analyzer:
            try:
                intent = self.intent_analyzer.analyze(query)
                if (
                    intent.expected_category
                    and intent.expected_category in category_hints
                ):
                    category_hints.remove(intent.expected_category)
                    category_hints.insert(0, intent.expected_category)
            except Exception as e:
                logger.debug(f"Failed to analyze intent for suggestions: {e}")

        if not suggestions:
            suggestions.append(f"{query} (다른 검색 모드를 시도해보세요)")

        return suggestions[:5]

    async def _expand_with_relations(
        self,
        result: SearchResponse,
        limit: int = 3,
        top_n: int = 3,
    ) -> Optional[List[SearchResult]]:
        """검색 결과 상위 N개의 관계 그래프를 순회하여 관련 메모리를 확장 로드"""
        try:
            from .relation import RelationService

            relation_service = RelationService(self.db)
            existing_ids = {r.id for r in result.results}

            # Step 1: Collect candidate IDs from relations of top results
            candidate_ids: Dict[str, float] = {}  # id -> strength
            for item in result.results[:top_n]:
                links = await relation_service.get_relations_for_memory(
                    memory_id=item.id,
                    direction="both",
                    limit=5,
                )
                for link in links:
                    linked_id = (
                        link.target_id if link.source_id == item.id else link.source_id
                    )
                    if linked_id not in existing_ids and linked_id not in candidate_ids:
                        candidate_ids[linked_id] = link.strength
                    if len(candidate_ids) >= limit:
                        break
                if len(candidate_ids) >= limit:
                    break

            if not candidate_ids:
                return None

            # Step 2: Batch lookup to eliminate N+1
            placeholders = ",".join("?" for _ in candidate_ids)
            rows = await self.db.fetchall(
                f"SELECT id, content, created_at, project_id, category, source, client, tags FROM memories WHERE id IN ({placeholders})",
                tuple(candidate_ids.keys()),
            )

            related_memories = []
            for row in rows:
                tags_raw = row["tags"]
                tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
                related_memories.append(
                    SearchResult(
                        id=row["id"],
                        content=row["content"],
                        similarity_score=candidate_ids.get(row["id"], 0.5),
                        created_at=row["created_at"] or "",
                        project_id=row["project_id"],
                        category=row["category"] or "",
                        source=row["source"] or "",
                        client=row["client"] if "client" in row.keys() else None,
                        tags=tags,
                    )
                )

            return related_memories[:limit] if related_memories else None
        except Exception as e:
            logger.warning(f"Relation expansion failed: {e}")
            return None

    def _calculate_recency_score(
        self, created_at: Union[str, datetime], oldest: Union[str, datetime], newest: Union[str, datetime]
    ) -> float:
        """최신성 점수 계산"""
        try:
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

            total_range = (newest - oldest).total_seconds()
            time_from_oldest = (created_at - oldest).total_seconds()

            if total_range == 0:
                return 1.0

            return max(0.0, min(1.0, time_from_oldest / total_range))
        except Exception as e:
            logger.debug(f"Failed to calculate relative recency: {e}")
            return 0.5

    # --- Temporal-Aware Search ---

    _TIME_RANGE_DELTAS: Dict[str, timedelta] = {
        "today": timedelta(days=1),
        "yesterday": timedelta(days=2),
        "this_week": timedelta(days=7),
        "last_week": timedelta(days=14),
        "this_month": timedelta(days=30),
        "last_month": timedelta(days=60),
        "this_quarter": timedelta(days=90),
    }

    def _resolve_time_range(
        self,
        time_range: Optional[str],
        date_from: Optional[str],
        date_to: Optional[str],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        """time_range 단축어 또는 date_from/date_to를 datetime 쌍으로 변환"""
        now = datetime.now(timezone.utc)

        if time_range and time_range in self._TIME_RANGE_DELTAS:
            delta = self._TIME_RANGE_DELTAS[time_range]
            return (now - delta, now)

        dt_from: Optional[datetime] = None
        dt_to: Optional[datetime] = None
        if date_from:
            try:
                dt_from = datetime.strptime(date_from, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                pass
        if date_to:
            try:
                dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
            except ValueError:
                pass

        return (dt_from, dt_to)

    @staticmethod
    def _parse_created_at(created_at_str: Optional[str]) -> Optional[datetime]:
        """created_at 문자열을 datetime 객체로 파싱"""
        if not created_at_str:
            return None
        try:
            # Handle ISO 8601 format (both timezone-aware and naive)
            dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, AttributeError):
            return None

    def _apply_temporal(
        self,
        response: SearchResponse,
        time_range: Optional[str],
        date_from: Optional[str],
        date_to: Optional[str],
        temporal_mode: str,
    ) -> SearchResponse:
        """시간 인식 검색 적용 (filter/boost/decay)

        Args:
            response: 기존 검색 결과
            time_range: 시간 범위 단축어
            date_from: 시작 날짜
            date_to: 종료 날짜
            temporal_mode: filter|boost|decay
        """
        now = datetime.now(timezone.utc)
        dt_from, dt_to = self._resolve_time_range(time_range, date_from, date_to)
        has_range = dt_from is not None or dt_to is not None

        if temporal_mode == "filter" and has_range:
            # Keep only results within range
            filtered = []
            for r in response.results:
                created = self._parse_created_at(r.created_at)
                if created is None:
                    continue
                if dt_from and created < dt_from:
                    continue
                if dt_to and created > dt_to:
                    continue
                filtered.append(r)
            response.results = filtered
            response.total = len(filtered)
            logger.debug(
                f"Temporal filter applied: {len(filtered)} results remain "
                f"(range: {dt_from} ~ {dt_to})"
            )

        elif temporal_mode == "boost" and has_range:
            # Boost scores for in-range results (keep out-of-range too)
            boost_factor = 1.5
            for r in response.results:
                created = self._parse_created_at(r.created_at)
                if created is None:
                    continue
                in_range = True
                if dt_from and created < dt_from:
                    in_range = False
                if dt_to and created > dt_to:
                    in_range = False
                if in_range and r.similarity_score is not None:
                    r.similarity_score = min(1.0, r.similarity_score * boost_factor)
            # Re-sort after boosting
            response.results.sort(key=lambda x: x.similarity_score or 0.0, reverse=True)
            logger.debug(
                f"Temporal boost applied: {boost_factor}x for range "
                f"{dt_from} ~ {dt_to}"
            )

        elif temporal_mode == "decay":
            # Time decay: score decreases with age
            decay_rate = 0.01  # 100 days → ~37%
            for r in response.results:
                created = self._parse_created_at(r.created_at)
                if created is None or r.similarity_score is None:
                    continue
                age_days = max(0.0, (now - created).total_seconds() / 86400.0)
                decay_factor = math.exp(-decay_rate * age_days)
                r.similarity_score = r.similarity_score * decay_factor
            # Re-sort after decay
            response.results.sort(key=lambda x: x.similarity_score or 0.0, reverse=True)
            logger.debug("Temporal decay applied to search results")

        return response

    def _boost_project_name_match(
        self, query: str, response: SearchResponse
    ) -> SearchResponse:
        """
        프로젝트명 정확 매칭 시 점수 부스팅

        Args:
            query: 검색 쿼리
            response: 검색 결과

        Returns:
            부스팅된 검색 결과
        """
        query_lower = query.lower()

        for result in response.results:
            if result.project_id:
                project_id_lower = result.project_id.lower()

                # Exact match
                if query_lower == project_id_lower:
                    result.similarity_score *= 2.0  # 100% boost
                    logger.debug(f"Exact project match boost: {result.project_id}")

                # Partial match
                elif query_lower in project_id_lower or project_id_lower in query_lower:
                    result.similarity_score *= 1.5  # 50% boost
                    logger.debug(f"Partial project match boost: {result.project_id}")

        # Re-sort by score (primary: similarity_score, secondary: created_at)
        response.results.sort(
            key=lambda x: (x.similarity_score, x.created_at or ""), reverse=True
        )

        return response

    def _parse_tags(self, row: "sqlite3.Row") -> Optional[List[str]]:
        """태그 파싱"""
        import json

        try:
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
                    return (
                        parsed if isinstance(parsed, list) and len(parsed) > 0 else None
                    )
                except json.JSONDecodeError:
                    return None
        except Exception as e:
            logger.debug(f"Failed to parse tags: {e}")
            return None
        return None

    async def search_with_context_optimization(
        self,
        query: str,
        project_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 25,
        optimize_context: bool = True,
    ) -> tuple:
        """
        맥락 최적화와 함께 검색 수행

        검색 의도를 분석하여 세션 맥락을 최적화된 방식으로 로드합니다.
        이를 통해 토큰 사용량을 절감하면서도 관련성 높은 정보를 제공합니다.

        Args:
            query: 검색 쿼리
            project_id: 프로젝트 ID
            category: 카테고리 필터
            limit: 결과 개수
            optimize_context: 맥락 최적화 활성화 (False면 기본 검색만 수행)

        Returns:
            (search_response, optimized_context)
            - search_response: 검색 결과
            - optimized_context: 최적화된 세션 맥락 (optimize_context=False이거나 세션이 없으면 None)

        Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
        """
        start_time = time.perf_counter()

        # 1. Perform base search
        search_response = await self.search(
            query=query,
            project_id=project_id,
            category=category,
            limit=limit,
            search_mode="smart",  # Enable intent-based auto-adjustment
        )

        # 2. Return search results only if context optimization is disabled or no project ID
        if not optimize_context or not project_id:
            logger.info(
                f"Context optimization skipped: "
                f"optimize_context={optimize_context}, project_id={project_id}"
            )
            return search_response, None

        # 3. Intent analysis (already done in search(), but perform explicitly again)
        intent = None
        if self.enable_quality_features and self.intent_analyzer and query:
            intent = self.intent_analyzer.analyze(query)
            logger.info(
                f"Intent analyzed for context optimization: "
                f"type={intent.intent_type}, urgency={intent.urgency:.2f}, "
                f"specificity={intent.specificity:.2f}"
            )
        else:
            # Generate default intent if no intent analyzer
            from .search_quality import SearchIntent

            intent = SearchIntent(
                intent_type="lookup",
                urgency=0.5,
                specificity=0.5,
                temporal_focus="any",
                expected_category=category,
                key_entities=[],
            )
            logger.debug("Using default intent for context optimization")

        # 4. Load context via ContextOptimizer
        optimized_context = None
        try:
            # Initialize SessionService and ContextOptimizer
            from .context_optimizer import ContextOptimizer
            from .session import SessionService

            session_service = SessionService(self.db)
            context_optimizer = ContextOptimizer(session_service)

            # Load context based on intent
            optimized_context = await context_optimizer.load_context_for_search(
                query=query, project_id=project_id, intent=intent
            )

            if optimized_context:
                logger.info(
                    f"Context loaded and optimized: "
                    f"session={optimized_context.session_id}, "
                    f"pins={len(optimized_context.pins) if optimized_context.pins else 0}"
                )
            else:
                logger.info(f"No active session found for project: {project_id}")

        except Exception as e:
            logger.error(f"Failed to load optimized context: {e}", exc_info=True)
            # Context load failure is non-fatal; return search results anyway
            optimized_context = None

        # 5. Log search duration
        search_time = time.perf_counter() - start_time
        logger.info(
            f"Search with context optimization completed in {search_time:.3f}s - "
            f"results: {len(search_response.results)}, "
            f"context_loaded: {optimized_context is not None}"
        )

        return search_response, optimized_context

    async def _collect_metrics(
        self,
        query: str,
        result: SearchResponse,
        start_time: float,
        project_id: Optional[str],
        category: Optional[str],
    ):
        """메트릭 수집"""
        if not self.metrics_collector:
            return

        try:
            response_time_ms = int((time.perf_counter() - start_time) * 1000)

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
                source="unified_search",
            )
        except Exception as e:
            logger.warning(f"Failed to collect metrics: {e}")
