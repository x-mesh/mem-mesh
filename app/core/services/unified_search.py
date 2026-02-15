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

import logging
import time
import urllib3
import asyncio
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from datetime import datetime

from ..database.base import Database
from ..embeddings.service import EmbeddingService
from ..schemas.responses import SearchResult, SearchResponse
from .cache_manager import get_cache_manager
from .scoring import ScoringPipeline, ScoringContext
from .noise_filter import SmartSearchFilter
from .query_expander import get_query_expander
from .score_normalizer import get_score_normalizer

if TYPE_CHECKING:
    from .metrics_collector import MetricsCollector
    from .search_quality import SearchIntentAnalyzer

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
        cache_context_ttl: Optional[int] = None
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
            context_ttl=cache_context_ttl
        )
        self.scoring_pipeline = ScoringPipeline()
        
        # Optional components
        self.noise_filter = SmartSearchFilter() if enable_noise_filter else None
        self.query_expander = get_query_expander() if get_query_expander else None
        self.intent_analyzer = None
        self.score_normalizer = get_score_normalizer(score_normalization_method) if enable_score_normalization else None
        
        # Load quality components if enabled
        if enable_quality_features:
            try:
                from .search_quality import SearchIntentAnalyzer
                self.intent_analyzer = SearchIntentAnalyzer()
                logger.info("Quality features enabled")
            except ImportError:
                logger.warning("SearchIntentAnalyzer not available, quality features disabled")
                self.enable_quality_features = False
        
        # RRF weights from config
        try:
            from ..config import get_settings
            _settings = get_settings()
            self._rrf_vector_weight = _settings.rrf_vector_weight
            self._rrf_text_weight = _settings.rrf_text_weight
        except Exception:
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
            # 한국어 → 영어
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
            
            # 영어 → 한국어
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
        min_quality_score: float = 0.3
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
            
        Returns:
            SearchResponse: 검색 결과
        """
        start_time = time.perf_counter()
        
        # URL 인코딩된 공백(+) 처리 및 정규화
        # FastAPI는 '+'를 자동으로 공백으로 변환하지 않으므로 수동 처리
        query = query.replace('+', ' ').strip() if query else ''
        original_query = query
        
        # 1. 의도 분석 (품질 기능 활성화 시)
        intent = None
        if self.enable_quality_features and self.intent_analyzer and query:
            intent = self.intent_analyzer.analyze(query)
            logger.info(
                f"Query intent: {intent.intent_type}, "
                f"urgency: {intent.urgency:.2f}, "
                f"specificity: {intent.specificity:.2f}"
            )
            
            # 의도 기반 파라미터 자동 조정
            if search_mode == "smart":
                search_mode, limit, category = self._auto_adjust_params(
                    intent, search_mode, limit, category
                )
        
        # 2. 쿼리 확장 (한국어 최적화 활성화 시)
        expanded_query = query
        if self.enable_korean_optimization and query and search_mode != "exact":
            expanded_query = self._expand_query(query)
            if expanded_query != query:
                logger.info(f"Query expanded: '{query}' → '{expanded_query[:100]}...'")
        
        # 3. 캐시 확인 (offset=0인 경우만)
        if offset == 0 and query:
            cached_results = await self.cache_manager.get_cached_search(
                query=expanded_query,
                project_id=project_id,
                category=category,
                limit=limit
            )
            if cached_results:
                logger.info(f"[Cache HIT] Returning cached results for query: '{query}'")
                return cached_results
        
        # 4. 필터 조건 구성
        filters = {}
        if project_id:
            filters['project_id'] = project_id
        if category:
            filters['category'] = category
        if source:
            filters['source'] = source
        if tag:
            filters['tag'] = tag
        
        # 빈 쿼리 여부 확인 (후처리 스킵 결정용)
        is_empty_query = not query.strip()
        
        # 5. 검색 모드에 따른 검색 수행
        if is_empty_query:
            # 빈 쿼리: 최근 메모리 반환 (후처리 없이 바로 반환)
            result = await self._get_recent_memories(filters, limit, offset, sort_by, sort_direction)
            # 빈 쿼리는 노이즈 필터링, 품질 스코어링, 점수 정규화 없이 바로 반환
            search_time = time.perf_counter() - start_time
            logger.info(
                f"Recent memories returned in {search_time:.3f}s - "
                f"results: {len(result.results)}"
            )
            return result
        elif search_mode == "exact":
            result = await self._exact_search(expanded_query, filters, limit)
        elif search_mode == "semantic":
            result = await self._semantic_search(expanded_query, filters, limit, recency_weight)
        elif search_mode == "fuzzy":
            result = await self._fuzzy_search(expanded_query, filters, limit)
        else:
            # hybrid 또는 smart (기본)
            result = await self._hybrid_search(expanded_query, filters, limit, recency_weight)
        
        # 6. 품질 스코어링 및 재정렬 (품질 기능 활성화 시)
        if self.enable_quality_features and result.results and intent:
            result = await self._apply_quality_scoring(
                result, original_query, intent, min_quality_score, sort_by
            )
        
        # 7. 노이즈 필터링 (활성화 시)
        if self.enable_noise_filter and self.noise_filter and result.results:
            context = {
                'project': project_id,
                'max_results': limit,
                'aggressive_filter': False
            }
            result = self.noise_filter.apply(result, original_query, context)
        
        # 8. 프로젝트명 매칭 부스팅 (정규화 전에 적용)
        if result.results and original_query:
            result = self._boost_project_name_match(original_query, result)
        
        # 9. 점수 정규화 (활성화 시)
        if self.enable_score_normalization and self.score_normalizer and result.results:
            # 모든 점수 추출
            scores = [r.similarity_score for r in result.results if r.similarity_score is not None]
            
            if scores:
                # 정규화 수행
                normalized_scores = self.score_normalizer.normalize(scores)
                
                # 정규화된 점수 적용
                for i, res in enumerate(result.results):
                    if res.similarity_score is not None and i < len(normalized_scores):
                        res.similarity_score = normalized_scores[i]
                
                logger.debug(f"Scores normalized: {len(scores)} scores")
        
        # 9. 캐시 저장 (offset=0인 경우만)
        if offset == 0 and query and result.results:
            await self.cache_manager.cache_search_results(
                query=expanded_query,
                results=result,
                project_id=project_id,
                category=category,
                limit=limit
            )
        
        # 9. 검색 시간 로깅
        search_time = time.perf_counter() - start_time
        logger.info(
            f"Search completed in {search_time:.3f}s - "
            f"mode: {search_mode}, "
            f"results: {len(result.results)}, "
            f"quality: {self.enable_quality_features}, "
            f"korean: {self.enable_korean_optimization}"
        )
        
        # 10. 의도 분석 결과 로깅
        if intent:
            logger.debug(
                f"Intent analysis: type={intent.intent_type}, "
                f"urgency={intent.urgency}, specificity={intent.specificity}"
            )
        
        # 11. 메트릭 수집
        await self._collect_metrics(original_query, result, start_time, project_id, category)
        
        logger.info(
            f"Search completed: query='{original_query[:50]}...', "
            f"results={len(result.results)}, time={search_time:.3f}s"
        )
        
        return result

    def _expand_query(self, query: str) -> str:
        """쿼리 확장 (한영 번역 + Query Expander)"""
        expanded_terms = set([query])
        
        # 1. Query Expander 사용 (있는 경우)
        if self.query_expander:
            try:
                expanded = self.query_expander.expand_query(query)
                if expanded != query:
                    expanded_terms.add(expanded)
            except Exception as e:
                logger.warning(f"Query expander failed: {e}")
        
        # 2. 한영 번역 추가 (한국어 쿼리인 경우에만)
        if self.enable_korean_optimization and self._is_korean(query):
            words = query.lower().split()
            for word in words:
                if word in self.korean_translations:
                    expanded_terms.update(self.korean_translations[word])
        
        # 3. 결합
        if len(expanded_terms) > 1:
            return " ".join(expanded_terms)
        return query

    def _auto_adjust_params(
        self,
        intent: Any,
        search_mode: str,
        limit: int,
        category: Optional[str]
    ) -> tuple:
        """의도 기반 파라미터 자동 조정"""
        # 검색 모드 조정
        if intent.intent_type == 'debug':
            search_mode = 'exact'
        elif intent.intent_type == 'explore':
            search_mode = 'semantic'
        elif intent.specificity > 0.7:
            search_mode = 'exact'
        else:
            search_mode = 'hybrid'
        
        # 결과 수 조정
        if intent.urgency > 0.8:
            limit = min(limit, 5)
        elif intent.specificity > 0.8:
            limit = min(limit, 3)
        elif intent.intent_type == 'explore':
            limit = max(limit, 10)
        
        # 카테고리 예측
        if not category and intent.expected_category:
            category = intent.expected_category
        
        return search_mode, limit, category

    async def _get_recent_memories(
        self,
        filters: Dict[str, Any],
        limit: int,
        offset: int,
        sort_by: str,
        sort_direction: str
    ) -> SearchResponse:
        """최근 메모리 조회"""
        raw_results = await self.db.get_recent_memories(
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_direction=sort_direction,
            filters=filters
        )
        
        total_count = await self.db.count_memories(filters=filters)
        
        if not raw_results:
            return SearchResponse(results=[], total=total_count)
        
        # SearchResult로 변환
        search_results = []
        oldest_time = min(row['created_at'] for row in raw_results)
        newest_time = max(row['created_at'] for row in raw_results)
        
        for row in raw_results:
            recency_score = self._calculate_recency_score(
                row['created_at'], oldest_time, newest_time
            )
            similarity_score = 0.7 + (recency_score * 0.3)
            
            search_results.append(SearchResult(
                id=row['id'],
                content=row['content'],
                similarity_score=similarity_score,
                created_at=row['created_at'],
                project_id=row['project_id'],
                category=row['category'],
                source=row['source'],
                tags=self._parse_tags(row)
            ))
        
        return SearchResponse(results=search_results, total=total_count)

    async def _hybrid_search(
        self,
        query: str,
        filters: Dict[str, Any],
        limit: int,
        recency_weight: float
    ) -> SearchResponse:
        """
        RRF 기반 하이브리드 검색 (벡터 + 텍스트 병렬 수행)
        """
        # 1. 임베딩 생성 (캐시 활용, 검색 쿼리이므로 is_query=True)
        query_embedding_list = await self.cache_manager.get_cached_embedding(query)
        if query_embedding_list is None:
            query_embedding_list = self.embedding_service.embed(query, is_query=True)
            await self.cache_manager.cache_embedding(query, query_embedding_list)
        
        query_embedding = self.embedding_service.to_bytes(query_embedding_list)
        
        # 2. 병렬 검색 수행 (Vector + Text)
        search_limit = limit * 2  # RRF를 위해 더 많은 후보군 확보
        
        # Vector Search Task
        vector_task = self.db.vector_search(
            embedding=query_embedding,
            limit=search_limit,
            filters=filters
        )
        
        # Text Search Task (Exact Match)
        text_task = self._exact_search(query, filters, search_limit)
        
        # Wait for both
        raw_vector_results, text_response = await asyncio.gather(vector_task, text_task)
        
        # 3. Vector 결과 처리 (Score 계산)
        vector_search_results = []
        if raw_vector_results:
            self.scoring_pipeline.set_recency_weight(recency_weight)
            for row in raw_vector_results:
                try:
                    distance = float(row['distance'])
                except (KeyError, TypeError):
                    distance = 1.0
                
                vector_score = max(0.0, min(1.0, 1.0 - (distance ** 2 / 2.0)))
                
                context = ScoringContext(
                    query=query,
                    content=row['content'],
                    vector_score=vector_score,
                    category=row['category'],
                    project_id=row['project_id'],
                    tags=self._parse_tags(row),
                    metadata={'recency_score': 0.5}
                )
                
                scoring_result = self.scoring_pipeline.calculate(context)
                if scoring_result.should_include:
                    vector_search_results.append(SearchResult(
                        id=row['id'],
                        content=row['content'],
                        similarity_score=scoring_result.final_score,
                        created_at=row['created_at'],
                        project_id=row['project_id'],
                        category=row['category'],
                        source=row['source'],
                        tags=self._parse_tags(row)
                    ))
        
        # 4. RRF 병합
        if not vector_search_results and not text_response.results:
            return SearchResponse(results=[])
            
        merged_results = self._apply_rrf(vector_search_results, text_response.results, limit)
        
        return SearchResponse(results=merged_results, total=len(merged_results))

    def _is_korean(self, text: str) -> bool:
        """쿼리에 한국어가 포함되어 있는지 확인"""
        for char in text:
            if '가' <= char <= '힣':
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
        
        # Vector Results 점수 합산
        for rank, item in enumerate(vector_results):
            if item.id not in content_map:
                content_map[item.id] = item
                original_scores[item.id] = item.similarity_score
            rrf_scores[item.id] = rrf_scores.get(item.id, 0) + vector_weight * (1.0 / (k + rank + 1))
            
        # Text Results 점수 합산
        for rank, item in enumerate(text_results):
            if item.id not in content_map:
                content_map[item.id] = item
                original_scores[item.id] = item.similarity_score
            rrf_scores[item.id] = rrf_scores.get(item.id, 0) + text_weight * (1.0 / (k + rank + 1))
            if item.id in original_scores:
                original_scores[item.id] = min(1.0, original_scores[item.id] + 0.1)
            
        # RRF 점수 기준 정렬
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
        
        final_results = []
        for doc_id in sorted_ids[:limit]:
            item = content_map[doc_id]
            item.similarity_score = original_scores.get(doc_id, 0.5)
            final_results.append(item)
            
        return final_results

    def _split_korean_compound(self, token: str) -> List[str]:
        """
        한국어 복합어를 가능한 서브토큰으로 분해.
        
        unicode61 토크나이저는 공백 없는 한국어 복합어를 하나의 토큰으로 처리하므로,
        2~3음절 단위로 분해하여 OR 검색이 가능하게 함.
        예: "토큰최적화" → ["토큰최적화", "토큰", "최적화", "토큰최", "적화"]
        """
        korean_chars = [c for c in token if '가' <= c <= '힣']
        if len(korean_chars) < 4:
            return [token]

        sub_tokens = {token}
        n = len(token)
        for size in (2, 3):
            for i in range(n - size + 1):
                chunk = token[i:i + size]
                if any('가' <= c <= '힣' for c in chunk) and len(chunk) >= 2:
                    sub_tokens.add(chunk)
        return list(sub_tokens)

    async def _exact_search(
        self,
        query: str,
        filters: Dict[str, Any],
        limit: int
    ) -> SearchResponse:
        """정확한 텍스트 매칭 검색"""
        # FTS Query 준비
        clean = query.replace('"', '""')
        tokens = clean.split()
        if not tokens:
            return SearchResponse(results=[])

        # 한국어 복합어 분해: 각 토큰을 서브토큰으로 확장
        if self.enable_korean_optimization:
            expanded_token_groups = []
            for t in tokens:
                subs = self._split_korean_compound(t)
                if len(subs) > 1:
                    expanded_token_groups.append("(" + " OR ".join(f'"{s}"' for s in subs) + ")")
                else:
                    expanded_token_groups.append(f'"{t}"')
            fts_query = " AND ".join(expanded_token_groups)
        else:
            fts_query = " AND ".join([f'"{t}"' for t in tokens])

        # FTS 쿼리 실행
        sql = """
            SELECT m.id, m.content, m.created_at, m.project_id, m.category, m.source, m.tags
            FROM memories_fts fts
            JOIN memories m ON fts.id = m.id
            WHERE fts.memories_fts MATCH ?
        """
        params = [fts_query]
        
        if filters:
            if filters.get('project_id'):
                sql += " AND m.project_id = ?"
                params.append(filters['project_id'])
            if filters.get('category'):
                sql += " AND m.category = ?"
                params.append(filters['category'])
                
        sql += " ORDER BY fts.rank LIMIT ?"
        params.append(limit)
        
        try:
            rows = await self.db.fetchall(sql, tuple(params))
            
            results = []
            # FTS rank 기반 점수 계산 (순위에 따라 0.9 ~ 0.7 범위)
            for i, row in enumerate(rows):
                # 텍스트 매칭은 높은 점수지만 1.0은 아님
                text_score = max(0.7, 0.9 - (i * 0.02))
                results.append(SearchResult(
                    id=row['id'],
                    content=row['content'],
                    similarity_score=text_score,
                    created_at=row['created_at'],
                    project_id=row['project_id'],
                    category=row['category'],
                    source=row['source'],
                    tags=self._parse_tags(row)
                ))
                
            return SearchResponse(results=results, total=len(results))
            
        except Exception as e:
            # FTS 실패 시 (테이블 없음 등) 빈 결과 반환하여 Vector Search만 수행되도록 함
            return SearchResponse(results=[])

    async def _semantic_search(
        self,
        query: str,
        filters: Dict[str, Any],
        limit: int,
        recency_weight: float
    ) -> SearchResponse:
        """순수 의미 기반 벡터 검색"""
        # 임베딩 생성 (검색 쿼리이므로 is_query=True)
        query_embedding_list = await self.cache_manager.get_cached_embedding(query)
        if query_embedding_list is None:
            query_embedding_list = self.embedding_service.embed(query, is_query=True)
            await self.cache_manager.cache_embedding(query, query_embedding_list)
        
        query_embedding = self.embedding_service.to_bytes(query_embedding_list)
        
        # 벡터 검색
        raw_results = await self.db.vector_search(
            embedding=query_embedding,
            limit=limit,
            filters=filters
        )
        
        if not raw_results:
            return SearchResponse(results=[])
        
        search_results = []
        for row in raw_results:
            try:
                distance = float(row['distance'])
            except (KeyError, TypeError):
                distance = 1.0
            
            similarity_score = max(0.0, min(1.0, 1.0 - (distance ** 2 / 2.0)))
            
            # 최신성 가중치 적용
            if recency_weight > 0.0:
                recency_score = 0.5  # 간단화
                similarity_score = (
                    similarity_score * (1.0 - recency_weight) +
                    recency_score * recency_weight
                )
            
            search_results.append(SearchResult(
                id=row['id'],
                content=row['content'],
                similarity_score=similarity_score,
                created_at=row['created_at'],
                project_id=row['project_id'],
                category=row['category'],
                source=row['source'],
                tags=self._parse_tags(row)
            ))
        
        # 1차: similarity_score 내림차순, 2차: created_at 내림차순 (안정적 정렬)
        search_results.sort(key=lambda x: (x.similarity_score, x.created_at or ''), reverse=True)
        return SearchResponse(results=search_results, total=len(search_results))

    async def _fuzzy_search(
        self,
        query: str,
        filters: Dict[str, Any],
        limit: int
    ) -> SearchResponse:
        """퍼지 검색 (오타 허용)"""
        from difflib import SequenceMatcher
        
        # 모든 메모리 가져오기
        base_query = "SELECT * FROM memories WHERE 1=1"
        params = []
        
        if filters:
            if filters.get('project_id'):
                base_query += " AND project_id = ?"
                params.append(filters['project_id'])
            if filters.get('category'):
                base_query += " AND category = ?"
                params.append(filters['category'])
        
        base_query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit * 10)
        
        raw_results = await self.db.fetchall(base_query, tuple(params))
        
        if not raw_results:
            return SearchResponse(results=[])
        
        # 퍼지 매칭
        query_words = query.lower().split()
        scored_results = []
        
        for row in raw_results:
            content_lower = row['content'].lower()
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
        
        # 정렬 및 제한 (1차: score 내림차순, 2차: created_at 내림차순)
        scored_results.sort(key=lambda x: (x[1], x[0]['created_at'] or ''), reverse=True)
        scored_results = scored_results[:limit]
        
        search_results = []
        for row, score in scored_results:
            search_results.append(SearchResult(
                id=row['id'],
                content=row['content'],
                similarity_score=score,
                created_at=row['created_at'],
                project_id=row['project_id'],
                category=row['category'],
                source=row['source'],
                tags=self._parse_tags(row)
            ))
        
        return SearchResponse(results=search_results, total=len(search_results))

    async def _text_search(
        self,
        query: str,
        filters: Dict[str, Any],
        limit: int
    ) -> SearchResponse:
        """텍스트 기반 검색 (폴백)"""
        base_query = "SELECT * FROM memories WHERE content LIKE ?"
        params = [f"%{query}%"]
        
        if filters:
            if filters.get('project_id'):
                base_query += " AND project_id = ?"
                params.append(filters['project_id'])
            if filters.get('category'):
                base_query += " AND category = ?"
                params.append(filters['category'])
        
        base_query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        raw_results = await self.db.fetchall(base_query, tuple(params))
        
        if not raw_results:
            return SearchResponse(results=[])
        
        search_results = []
        for row in raw_results:
            content_lower = row['content'].lower()
            query_lower = query.lower()
            query_words = query_lower.split()
            
            matched_words = sum(1 for word in query_words if word in content_lower)
            similarity_score = matched_words / len(query_words) if query_words else 0.5
            similarity_score = max(0.1, min(1.0, similarity_score))
            
            search_results.append(SearchResult(
                id=row['id'],
                content=row['content'],
                similarity_score=similarity_score,
                created_at=row['created_at'],
                project_id=row['project_id'],
                category=row['category'],
                source=row['source'],
                tags=self._parse_tags(row)
            ))
        
        # 1차: similarity_score 내림차순, 2차: created_at 내림차순 (안정적 정렬)
        search_results.sort(key=lambda x: (x.similarity_score, x.created_at or ''), reverse=True)
        return SearchResponse(results=search_results, total=len(search_results))

    async def _apply_quality_scoring(
        self,
        result: SearchResponse,
        query: str,
        intent: Any,
        min_quality_score: float,
        sort_by: str
    ) -> SearchResponse:
        """품질 스코어링 적용"""
        # 품질 스코어링 로직은 enhanced_search.py 참조
        # 여기서는 간단화된 버전 구현
        return result

    def _calculate_recency_score(
        self,
        created_at: Any,
        oldest: Any,
        newest: Any
    ) -> float:
        """최신성 점수 계산"""
        try:
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            if isinstance(oldest, str):
                oldest = datetime.fromisoformat(oldest.replace('Z', '+00:00'))
            if isinstance(newest, str):
                newest = datetime.fromisoformat(newest.replace('Z', '+00:00'))
            
            # timezone-aware와 timezone-naive datetime 혼합 방지
            # 모든 datetime을 naive로 통일 (tzinfo 제거)
            if hasattr(created_at, 'tzinfo') and created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
            if hasattr(oldest, 'tzinfo') and oldest.tzinfo is not None:
                oldest = oldest.replace(tzinfo=None)
            if hasattr(newest, 'tzinfo') and newest.tzinfo is not None:
                newest = newest.replace(tzinfo=None)
            
            if oldest == newest:
                return 1.0
            
            total_range = (newest - oldest).total_seconds()
            time_from_oldest = (created_at - oldest).total_seconds()
            
            if total_range == 0:
                return 1.0
            
            return max(0.0, min(1.0, time_from_oldest / total_range))
        except Exception:
            return 0.5

    def _boost_project_name_match(
        self,
        query: str,
        response: SearchResponse
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
                
                # 정확한 매칭
                if query_lower == project_id_lower:
                    result.similarity_score *= 2.0  # 100% 부스팅
                    logger.debug(f"Exact project match boost: {result.project_id}")
                
                # 부분 매칭
                elif query_lower in project_id_lower or project_id_lower in query_lower:
                    result.similarity_score *= 1.5  # 50% 부스팅
                    logger.debug(f"Partial project match boost: {result.project_id}")
        
        # 점수 순으로 재정렬 (1차: similarity_score, 2차: created_at)
        response.results.sort(key=lambda x: (x.similarity_score, x.created_at or ''), reverse=True)
        
        return response
    
    def _parse_tags(self, row: Any) -> Optional[List[str]]:
        """태그 파싱"""
        import json
        try:
            tags_value = row['tags'] if 'tags' in row.keys() else None
            if tags_value is None:
                return None
            if isinstance(tags_value, list):
                return tags_value
            if isinstance(tags_value, str):
                if not tags_value or tags_value == '[]':
                    return None
                try:
                    parsed = json.loads(tags_value)
                    return parsed if isinstance(parsed, list) and len(parsed) > 0 else None
                except json.JSONDecodeError:
                    return None
        except Exception:
            return None
        return None

    async def search_with_context_optimization(
        self,
        query: str,
        project_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 25,
        optimize_context: bool = True
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
        
        # 1. 기본 검색 수행
        search_response = await self.search(
            query=query,
            project_id=project_id,
            category=category,
            limit=limit,
            search_mode="smart"  # 의도 기반 자동 조정 활성화
        )
        
        # 2. 맥락 최적화가 비활성화되었거나 프로젝트 ID가 없으면 검색 결과만 반환
        if not optimize_context or not project_id:
            logger.info(
                f"Context optimization skipped: "
                f"optimize_context={optimize_context}, project_id={project_id}"
            )
            return search_response, None
        
        # 3. 의도 분석 (이미 search()에서 수행되었지만 명시적으로 다시 수행)
        intent = None
        if self.enable_quality_features and self.intent_analyzer and query:
            intent = self.intent_analyzer.analyze(query)
            logger.info(
                f"Intent analyzed for context optimization: "
                f"type={intent.intent_type}, urgency={intent.urgency:.2f}, "
                f"specificity={intent.specificity:.2f}"
            )
        else:
            # 의도 분석기가 없으면 기본 의도 생성
            from .search_quality import SearchIntent
            intent = SearchIntent(
                intent_type='lookup',
                urgency=0.5,
                specificity=0.5,
                temporal_focus='any',
                expected_category=category,
                key_entities=[]
            )
            logger.debug("Using default intent for context optimization")
        
        # 4. ContextOptimizer를 통한 맥락 로드
        optimized_context = None
        try:
            # SessionService와 ContextOptimizer 초기화
            from .session import SessionService
            from .context_optimizer import ContextOptimizer
            
            session_service = SessionService(self.db)
            context_optimizer = ContextOptimizer(session_service)
            
            # 의도 기반 맥락 로드
            optimized_context = await context_optimizer.load_context_for_search(
                query=query,
                project_id=project_id,
                intent=intent
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
            # 맥락 로드 실패는 치명적이지 않으므로 검색 결과는 반환
            optimized_context = None
        
        # 5. 검색 시간 로깅
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
        category: Optional[str]
    ):
        """메트릭 수집"""
        if not self.metrics_collector:
            return
        
        try:
            response_time_ms = int((time.perf_counter() - start_time) * 1000)
            
            avg_similarity = None
            top_similarity = None
            if result.results:
                scores = [r.similarity_score for r in result.results if r.similarity_score is not None]
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
                source="unified_search"
            )
        except Exception as e:
            logger.warning(f"Failed to collect metrics: {e}")
