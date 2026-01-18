"""
최종 개선된 검색 서비스
Final Improved Search Service with better Korean handling
"""

import logging
from typing import Optional, List, Dict
import numpy as np

from ..database.base import Database
from ..embeddings.service import EmbeddingService
from ..schemas.responses import SearchResponse, SearchResult

logger = logging.getLogger(__name__)


class FinalImprovedSearch:
    """최종 개선된 검색 서비스"""

    def __init__(self, db: Database, embedding_service: EmbeddingService):
        self.db = db
        self.embedding_service = embedding_service

        # 확장된 한영 사전
        self.translations = {
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
        }

    async def search(
        self,
        query: str,
        limit: int = 10,
        project_filter: Optional[str] = None
    ) -> SearchResponse:
        """
        최종 개선된 검색

        전략:
        1. 쿼리 확장 (한영 변환 + 유사어)
        2. 텍스트 매칭 (content, category, tags)
        3. 벡터 유사도 계산
        4. 스코어 부스팅 (프로젝트, 키워드 매칭)
        5. 하이브리드 스코어링
        """

        # 1. 쿼리 확장
        expanded_terms = self._expand_query(query)
        logger.info(f"Query expanded: '{query}' → {expanded_terms}")

        # 2. 텍스트 기반 검색
        text_results = self._text_search(expanded_terms, project_filter)

        # 3. 벡터 기반 검색
        vector_results = self._vector_search(query, project_filter, limit * 2)

        # 4. 결과 병합 및 스코어링
        final_results = self._merge_and_score(
            text_results,
            vector_results,
            query,
            expanded_terms,
            project_filter
        )

        # 5. 상위 N개 반환
        final_results = final_results[:limit]

        return SearchResponse(
            results=final_results,
            total=len(final_results)
        )

    def _expand_query(self, query: str) -> List[str]:
        """쿼리 확장"""
        terms = set([query.lower()])
        words = query.lower().split()

        # 각 단어에 대해 번역 추가
        for word in words:
            if word in self.translations:
                terms.update(self.translations[word])

            # 부분 매칭도 시도
            for key, values in self.translations.items():
                if word in key or key in word:
                    terms.update(values)

        return list(terms)

    def _text_search(self, terms: List[str], project_filter: Optional[str]) -> Dict[str, dict]:
        """텍스트 기반 검색"""
        results = {}
        conn = self.db.connection

        for term in terms[:10]:  # 최대 10개 용어
            # content, category, tags 모두 검색
            sql = """
                SELECT id, content, category, project_id, tags,
                       created_at, updated_at, source, embedding
                FROM memories
                WHERE (
                    LOWER(content) LIKE LOWER(?) OR
                    LOWER(category) LIKE LOWER(?) OR
                    LOWER(tags) LIKE LOWER(?)
                )
            """
            params = [f"%{term}%", f"%{term}%", f"%{term}%"]

            if project_filter:
                sql += " AND project_id = ?"
                params.append(project_filter)

            sql += " LIMIT 50"

            cursor = conn.execute(sql, tuple(params))
            rows = cursor.fetchall()

            for row in rows:
                mem_id = row[0]
                if mem_id not in results:
                    results[mem_id] = {
                        'id': mem_id,
                        'content': row[1],
                        'category': row[2],
                        'project_id': row[3],
                        'tags': row[4].split(',') if row[4] else [],
                        'created_at': row[5],
                        'updated_at': row[6],
                        'source': row[7],
                        'embedding': row[8],
                        'text_matches': [term],
                        'text_score': 1.0
                    }
                else:
                    results[mem_id]['text_matches'].append(term)
                    results[mem_id]['text_score'] += 0.5

        return results

    def _vector_search(self, query: str, project_filter: Optional[str], limit: int) -> Dict[str, dict]:
        """벡터 기반 검색"""
        results = {}
        conn = self.db.connection

        # 쿼리 임베딩
        query_embedding = self.embedding_service.embed(query)

        # 모든 메모리 가져오기
        sql = """
            SELECT id, content, category, project_id, tags,
                   created_at, updated_at, source, embedding
            FROM memories
            WHERE embedding IS NOT NULL
        """
        params = []

        if project_filter:
            sql += " AND project_id = ?"
            params.append(project_filter)

        cursor = conn.execute(sql, tuple(params))
        rows = cursor.fetchall()

        # 유사도 계산
        scored_results = []
        for row in rows:
            try:
                mem_embedding = self.embedding_service.from_bytes(row[8])
                similarity = np.dot(query_embedding, mem_embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(mem_embedding)
                )

                scored_results.append({
                    'id': row[0],
                    'content': row[1],
                    'category': row[2],
                    'project_id': row[3],
                    'tags': row[4].split(',') if row[4] else [],
                    'created_at': row[5],
                    'updated_at': row[6],
                    'source': row[7],
                    'embedding': row[8],
                    'vector_score': similarity
                })
            except Exception as e:
                continue

        # 상위 N개만 선택
        scored_results.sort(key=lambda x: x['vector_score'], reverse=True)
        for result in scored_results[:limit]:
            results[result['id']] = result

        return results

    def _merge_and_score(
        self,
        text_results: Dict[str, dict],
        vector_results: Dict[str, dict],
        original_query: str,
        expanded_terms: List[str],
        project_filter: Optional[str]
    ) -> List[SearchResult]:
        """결과 병합 및 최종 스코어링"""

        # 모든 결과 병합
        all_results = {}

        # 텍스트 결과 추가
        for mem_id, result in text_results.items():
            all_results[mem_id] = result

        # 벡터 결과 병합
        for mem_id, result in vector_results.items():
            if mem_id in all_results:
                all_results[mem_id]['vector_score'] = result.get('vector_score', 0)
            else:
                all_results[mem_id] = result
                all_results[mem_id]['text_score'] = 0

        # 최종 스코어 계산
        final_results = []
        for mem_id, result in all_results.items():
            # 기본 스코어
            text_score = result.get('text_score', 0)
            vector_score = result.get('vector_score', 0)

            # 하이브리드 스코어 (텍스트 매칭이 있으면 가중치 높임)
            if text_score > 0:
                final_score = (text_score * 0.7) + (vector_score * 0.3)
            else:
                final_score = vector_score * 0.5

            # 프로젝트 부스팅
            if project_filter and result['project_id'] == project_filter:
                final_score *= 1.5

            # 카테고리 부스팅
            content_lower = result['content'].lower()
            category = result['category']

            for term in expanded_terms:
                if term in content_lower:
                    final_score += 0.2
                if term in category.lower():
                    final_score += 0.1

            # SearchResult 객체 생성
            final_results.append(SearchResult(
                id=result['id'],
                content=result['content'],
                category=result['category'],
                project_id=result['project_id'],
                tags=result.get('tags', []),
                created_at=result['created_at'],
                updated_at=result['updated_at'],
                similarity_score=final_score,
                source=result.get('source')
            ))

        # 점수 기준 정렬
        final_results.sort(key=lambda x: x.similarity_score, reverse=True)

        return final_results