"""
Simple Improved Search - 간단하지만 효과적인 개선
"""

import logging
from typing import Optional, List
import re

from ..database.base import Database
from ..embeddings.service import EmbeddingService
from ..schemas.responses import SearchResponse, SearchResult

logger = logging.getLogger(__name__)


class SimpleImprovedSearch:
    """간단한 개선 검색"""

    def __init__(self, db: Database, embedding_service: EmbeddingService):
        self.db = db
        self.embedding_service = embedding_service

    async def search(
        self,
        query: str,
        limit: int = 10,
        project_filter: Optional[str] = None
    ) -> SearchResponse:
        """
        간단한 개선 검색

        전략:
        1. 한국어 단어를 영어로 변환
        2. 두 언어로 모두 검색
        3. 결과 병합
        """

        # 간단한 한영 사전
        translations = {
            "토큰": "token",
            "최적화": "optimization",
            "검색": "search",
            "품질": "quality",
            "캐싱": "caching cache",
            "임베딩": "embedding",
            "배치": "batch",
            "의도": "intent",
            "분석": "analysis analyze"
        }

        # 쿼리 확장
        expanded_terms = [query]
        words = query.split()

        for word in words:
            if word in translations:
                expanded_terms.extend(translations[word].split())

        # 영어 단어도 한국어로 변환
        for eng, kor in [("token", "토큰"), ("search", "검색"), ("cache", "캐시")]:
            if eng in query.lower():
                expanded_terms.append(kor)

        expanded_query = " ".join(expanded_terms)
        logger.info(f"Query expanded: '{query}' → '{expanded_query}'")

        # 데이터베이스에서 직접 검색
        all_results = []

        try:
            # 텍스트 검색 (LIKE 쿼리)
            for term in expanded_terms[:5]:  # 최대 5개 용어만
                sql = """
                    SELECT id, content, category, project_id, tags,
                           created_at, updated_at, source, embedding
                    FROM memories
                    WHERE content LIKE ?
                """
                params = [f"%{term}%"]

                if project_filter:
                    sql += " AND project_id = ?"
                    params.append(project_filter)

                sql += " LIMIT 20"

                cursor = await self.db.execute(sql, tuple(params))
                rows = cursor.fetchall()

                for row in rows:
                    # 중복 제거를 위해 ID를 키로 사용
                    result_dict = {
                        'id': row[0],
                        'content': row[1],
                        'category': row[2],
                        'project_id': row[3],
                        'tags': row[4].split(',') if row[4] else [],
                        'created_at': row[5],
                        'updated_at': row[6],
                        'source': row[7],
                        'term_match': term,
                        'embedding': row[8]
                    }

                    # ID 기준 중복 제거
                    if not any(r.get('id') == result_dict['id'] for r in all_results):
                        all_results.append(result_dict)

            # 벡터 유사도 계산 및 정렬
            if all_results and self.embedding_service:
                query_embedding = self.embedding_service.embed(query)

                for result in all_results:
                    if result['embedding']:
                        try:
                            mem_embedding = self.embedding_service.from_bytes(result['embedding'])

                            # 코사인 유사도
                            import numpy as np
                            similarity = np.dot(query_embedding, mem_embedding) / (
                                np.linalg.norm(query_embedding) * np.linalg.norm(mem_embedding)
                            )

                            # 프로젝트 보너스
                            if project_filter and result['project_id'] == project_filter:
                                similarity *= 1.2

                            # 카테고리 보너스
                            if 'optimization' in query.lower() and result['category'] == 'decision':
                                similarity *= 1.1
                            if 'search' in query.lower() and result['category'] == 'code_snippet':
                                similarity *= 1.1

                            result['score'] = similarity
                        except Exception as e:
                            result['score'] = 0.0
                    else:
                        result['score'] = 0.0

            # 점수 기준 정렬
            all_results.sort(key=lambda x: x.get('score', 0), reverse=True)

            # SearchResult 객체로 변환
            results = []
            for r in all_results[:limit]:
                results.append(SearchResult(
                    id=r['id'],
                    content=r['content'],
                    category=r['category'],
                    project_id=r['project_id'],
                    tags=r['tags'],
                    created_at=r['created_at'],
                    updated_at=r['updated_at'],
                    similarity_score=r.get('score', 0.0),
                    source=r['source']
                ))

            return SearchResponse(
                results=results,
                total=len(results)
            )

        except Exception as e:
            logger.error(f"Search error: {e}")
            return SearchResponse(results=[], total=0)