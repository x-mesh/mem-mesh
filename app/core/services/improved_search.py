"""
Improved Search Service with Better Korean Support
향상된 한국어 지원 검색 서비스
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
import numpy as np

from .search import SearchService
from .query_expander import get_query_expander
from ..database.base import Database
from ..embeddings.service import EmbeddingService
from ..schemas.responses import SearchResponse, SearchResult

logger = logging.getLogger(__name__)


class ImprovedSearchService(SearchService):
    """개선된 검색 서비스 - 한국어 최적화"""

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
        search_mode: str = "smart"
    ) -> SearchResponse:
        """
        향상된 검색 - 한국어 최적화

        Args:
            query: 검색 쿼리
            project_id: 프로젝트 필터
            category: 카테고리 필터
            source: 소스 필터
            tag: 태그 필터
            limit: 결과 개수
            offset: 오프셋
            sort_by: 정렬 기준
            sort_direction: 정렬 방향
            recency_weight: 최신성 가중치
            search_mode: 검색 모드 (smart/hybrid/text/vector)

        Returns:
            SearchResponse: 검색 결과
        """
        original_query = query

        # 1. 언어 감지
        is_korean = self._contains_korean(query)
        is_english = self._contains_english(query)

        # 2. Query Expansion (한국어 우선)
        expanded_query = None
        if get_query_expander and search_mode not in ['exact', 'vector']:
            try:
                expander = get_query_expander()
                expanded_query = expander.expand_query(query)
                logger.info(f"Query expanded: '{query}' → '{expanded_query[:100]}...'")
            except Exception as e:
                logger.warning(f"Query expansion failed: {e}")

        # 3. 스마트 모드 결정
        if search_mode == "smart":
            if is_korean and not is_english:
                # 순수 한국어: 텍스트+확장 우선
                search_mode = "korean_optimized"
            elif is_english and not is_korean:
                # 순수 영어: 벡터 우선
                search_mode = "hybrid"
            else:
                # 혼합: 하이브리드
                search_mode = "mixed"

        logger.info(f"Search mode: {search_mode} for query: '{original_query}'")

        # 4. 검색 전략 실행
        if search_mode == "korean_optimized":
            return await self._search_korean_optimized(
                original_query, expanded_query,
                project_id, category, source, tag,
                limit, offset, sort_by, sort_direction, recency_weight
            )
        elif search_mode == "mixed":
            return await self._search_mixed(
                original_query, expanded_query,
                project_id, category, source, tag,
                limit, offset, sort_by, sort_direction, recency_weight
            )
        else:
            # 기본 하이브리드 검색
            return await super().search(
                query=expanded_query or query,
                project_id=project_id,
                category=category,
                source=source,
                tag=tag,
                limit=limit,
                offset=offset,
                sort_by=sort_by,
                sort_direction=sort_direction,
                recency_weight=recency_weight,
                search_mode="hybrid"
            )

    async def _search_korean_optimized(
        self,
        original_query: str,
        expanded_query: Optional[str],
        project_id: Optional[str],
        category: Optional[str],
        source: Optional[str],
        tag: Optional[str],
        limit: int,
        offset: int,
        sort_by: str,
        sort_direction: str,
        recency_weight: float
    ) -> SearchResponse:
        """한국어 최적화 검색"""

        # 1. 확장 쿼리로 텍스트 검색
        text_results = await super().search(
            query=expanded_query or original_query,
            project_id=project_id,
            category=category,
            source=source,
            tag=tag,
            limit=limit * 2,  # 더 많이 가져와서 필터링
            offset=offset,
            sort_by=sort_by,
            sort_direction=sort_direction,
            recency_weight=recency_weight,
            search_mode="text"
        )

        # 2. 원본 쿼리로 벡터 검색
        vector_results = await super().search(
            query=original_query,
            project_id=project_id,
            category=category,
            source=source,
            tag=tag,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_direction=sort_direction,
            recency_weight=recency_weight,
            search_mode="semantic"
        )

        # 3. 결과 병합 및 재정렬
        return self._merge_results(
            text_results, vector_results,
            text_weight=0.7, vector_weight=0.3,
            limit=limit
        )

    async def _search_mixed(
        self,
        original_query: str,
        expanded_query: Optional[str],
        project_id: Optional[str],
        category: Optional[str],
        source: Optional[str],
        tag: Optional[str],
        limit: int,
        offset: int,
        sort_by: str,
        sort_direction: str,
        recency_weight: float
    ) -> SearchResponse:
        """혼합 언어 검색"""

        # 1. 확장 쿼리로 하이브리드 검색
        results = await super().search(
            query=expanded_query or original_query,
            project_id=project_id,
            category=category,
            source=source,
            tag=tag,
            limit=limit * 2,
            offset=offset,
            sort_by=sort_by,
            sort_direction=sort_direction,
            recency_weight=recency_weight,
            search_mode="hybrid"
        )

        # 2. 스코어 부스팅
        for result in results.results:
            # 한국어/영어 매칭 보너스
            if self._contains_korean(result.content) and self._contains_korean(original_query):
                result.similarity_score *= 1.2
            if self._contains_english(result.content) and self._contains_english(original_query):
                result.similarity_score *= 1.1

        # 3. 재정렬
        results.results.sort(key=lambda x: x.similarity_score, reverse=True)
        results.results = results.results[:limit]

        return results

    def _merge_results(
        self,
        text_results: SearchResponse,
        vector_results: SearchResponse,
        text_weight: float = 0.5,
        vector_weight: float = 0.5,
        limit: int = 25
    ) -> SearchResponse:
        """검색 결과 병합"""

        # ID별 결과 저장
        merged = {}

        # 텍스트 검색 결과 추가
        for i, result in enumerate(text_results.results):
            score = (1.0 - i * 0.05) * text_weight  # 순위 기반 점수
            merged[result.id] = {
                'result': result,
                'score': score,
                'source': 'text'
            }

        # 벡터 검색 결과 추가/병합
        for i, result in enumerate(vector_results.results):
            score = result.similarity_score * vector_weight
            if result.id in merged:
                # 이미 있으면 점수 합산
                merged[result.id]['score'] += score
                merged[result.id]['source'] = 'both'
            else:
                merged[result.id] = {
                    'result': result,
                    'score': score,
                    'source': 'vector'
                }

        # 점수 기준 정렬
        sorted_items = sorted(
            merged.items(),
            key=lambda x: x[1]['score'],
            reverse=True
        )[:limit]

        # SearchResponse 생성
        results = []
        for item_id, data in sorted_items:
            result = data['result']
            result.similarity_score = data['score']
            results.append(result)

        response = SearchResponse(
            results=results,
            total=len(results)
        )

        # 메타데이터 추가
        response.metadata = {
            'text_count': len([x for x in sorted_items if x[1]['source'] in ['text', 'both']]),
            'vector_count': len([x for x in sorted_items if x[1]['source'] in ['vector', 'both']]),
            'both_count': len([x for x in sorted_items if x[1]['source'] == 'both'])
        }

        return response

    def _contains_korean(self, text: str) -> bool:
        """한국어 포함 여부 확인"""
        import re
        return bool(re.search('[가-힣]', text))

    def _contains_english(self, text: str) -> bool:
        """영어 포함 여부 확인"""
        import re
        return bool(re.search('[a-zA-Z]', text))


# 싱글톤 인스턴스
_improved_search_service = None


def get_improved_search_service(db: Database, embedding_service: EmbeddingService) -> ImprovedSearchService:
    """Get singleton ImprovedSearchService instance"""
    global _improved_search_service
    if _improved_search_service is None:
        _improved_search_service = ImprovedSearchService(db, embedding_service)
    return _improved_search_service