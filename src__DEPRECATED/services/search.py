"""
Search Service for mem-mesh
하이브리드 검색을 수행하는 서비스
"""

import logging
from typing import Optional
from datetime import datetime

from ..database.base import Database
from ..embeddings.service import EmbeddingService
from ..schemas.responses import SearchResult, SearchResponse

logger = logging.getLogger(__name__)


class SearchService:
    """하이브리드 검색 서비스"""
    
    def __init__(self, db: Database, embedding_service: EmbeddingService):
        self.db = db
        self.embedding_service = embedding_service
        self.similarity_threshold = 0.5
        logger.info("SearchService initialized")
    
    async def search(
        self,
        query: str,
        project_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 5,
        recency_weight: float = 0.0
    ) -> SearchResponse:
        """
        하이브리드 검색 수행
        
        Args:
            query: 검색 쿼리 (빈 문자열인 경우 모든 메모리 반환)
            project_id: 프로젝트 필터
            category: 카테고리 필터
            limit: 결과 개수 제한
            recency_weight: 최신성 가중치 (0.0 ~ 1.0)
            
        Returns:
            SearchResponse: 검색 결과
        """
        logger.info(f"Searching for query: '{query}' with filters - project_id: {project_id}, category: {category}")
        
        try:
            # SQL 필터 조건 구성
            filters = {}
            if project_id:
                filters['project_id'] = project_id
            if category:
                filters['category'] = category
            
            # 빈 쿼리인 경우 최근 메모리 반환
            if not query.strip():
                raw_results = await self.db.get_recent_memories(
                    limit=limit,
                    filters=filters
                )
                
                if not raw_results:
                    logger.info("No recent memories found")
                    return SearchResponse(results=[])
                
                # 결과를 SearchResult 형태로 변환 (최신성 기반 점수)
                search_results = []
                if raw_results:
                    # 최신성 기반 점수 계산을 위한 시간 범위 구하기
                    oldest_time = min(row['created_at'] for row in raw_results)
                    newest_time = max(row['created_at'] for row in raw_results)
                    
                    for row in raw_results:
                        try:
                            # 최신성 기반 점수 계산 (0.7 ~ 1.0 범위)
                            recency_score = self._calculate_recency_score(
                                row['created_at'], oldest_time, newest_time
                            )
                            # 최신성 점수를 0.7 ~ 1.0 범위로 조정
                            similarity_score = 0.7 + (recency_score * 0.3)
                            
                            search_result = SearchResult(
                                id=row['id'],
                                content=row['content'],
                                similarity_score=similarity_score,
                                created_at=row['created_at'],
                                project_id=row['project_id'],
                                category=row['category'],
                                source=row['source']
                            )
                            search_results.append(search_result)
                        except Exception as e:
                            logger.warning(f"Failed to process recent memory result: {e}")
                            continue
                
                logger.info(f"Found {len(search_results)} recent memories")
                return SearchResponse(results=search_results)
            
            # 완전 텍스트 기반 검색 사용 (sqlite-vec 지원 없음)
            logger.info("Using vector search with sqlite-vec")
            return await self._vector_search(query, filters, limit, recency_weight)
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            # 검색 실패 시 빈 결과 반환
            return SearchResponse(results=[])
    
    def _calculate_recency_score(
        self, 
        created_at, 
        oldest, 
        newest
    ) -> float:
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
            # 문자열인 경우 datetime으로 변환
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            if isinstance(oldest, str):
                oldest = datetime.fromisoformat(oldest.replace('Z', '+00:00'))
            if isinstance(newest, str):
                newest = datetime.fromisoformat(newest.replace('Z', '+00:00'))
            
            if oldest == newest:
                return 1.0
            
            # 시간 차이를 초 단위로 계산
            total_range = (newest - oldest).total_seconds()
            time_from_oldest = (created_at - oldest).total_seconds()
            
            if total_range == 0:
                return 1.0
            
            # 0.0 ~ 1.0 범위로 정규화
            recency_score = time_from_oldest / total_range
            return max(0.0, min(1.0, recency_score))
            
        except Exception as e:
            logger.warning(f"Failed to calculate recency score: {e}")
            return 0.5  # 기본값
    
    async def _vector_search(
        self,
        query: str,
        filters: Optional[dict] = None,
        limit: int = 5,
        recency_weight: float = 0.0
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
            # 쿼리를 embedding으로 변환
            query_embedding_list = self.embedding_service.embed(query)
            query_embedding = self.embedding_service.to_bytes(query_embedding_list)
            
            # Vector 검색 수행
            raw_results = await self.db.vector_search(
                embedding=query_embedding,
                limit=limit,
                filters=filters
            )
            
            if not raw_results:
                logger.info("No vector search results found, falling back to text search")
                return await self._text_based_search(query, filters, limit)
            
            # 결과를 SearchResult 형태로 변환
            search_results = []
            for row in raw_results:
                try:
                    # Vector 검색에서는 distance가 제공됨 (낮을수록 유사)
                    # distance를 similarity_score로 변환 (높을수록 유사)
                    if 'distance' in row.keys():
                        # distance를 0~1 범위의 similarity로 변환
                        # distance가 0에 가까울수록 similarity는 1에 가까워짐
                        distance = float(row['distance'])
                        # 일반적으로 cosine distance는 0~2 범위이므로 적절히 변환
                        similarity_score = max(0.0, min(1.0, 1.0 - (distance / 2.0)))
                    else:
                        # distance 정보가 없으면 기본값
                        similarity_score = 0.8
                    
                    # 최신성 가중치 적용
                    if recency_weight > 0.0:
                        # 최신성 점수 계산
                        recency_score = self._calculate_recency_score(
                            row['created_at'], 
                            min(r['created_at'] for r in raw_results),
                            max(r['created_at'] for r in raw_results)
                        )
                        # 가중 평균으로 최종 점수 계산
                        similarity_score = (
                            similarity_score * (1.0 - recency_weight) + 
                            recency_score * recency_weight
                        )
                    
                    search_result = SearchResult(
                        id=row['id'],
                        content=row['content'],
                        similarity_score=similarity_score,
                        created_at=row['created_at'],
                        project_id=row['project_id'],
                        category=row['category'],
                        source=row['source']
                    )
                    search_results.append(search_result)
                except Exception as e:
                    logger.warning(f"Failed to process vector search result: {e}")
                    continue
            
            # 점수순으로 정렬
            search_results.sort(key=lambda x: x.similarity_score, reverse=True)
            
            logger.info(f"Found {len(search_results)} vector search results")
            return SearchResponse(results=search_results)
            
        except Exception as e:
            logger.error(f"Vector search failed: {e}, falling back to text search")
            return await self._text_based_search(query, filters, limit)
    
    async def _text_based_search(
        self,
        query: str,
        filters: Optional[dict] = None,
        limit: int = 5
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
            # SQL LIKE 검색 수행
            base_query = "SELECT * FROM memories WHERE content LIKE ?"
            params = [f"%{query}%"]
            
            # 필터 조건 추가
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
                logger.info("No text search results found")
                return SearchResponse(results=[])
            
            # 결과를 SearchResult 형태로 변환
            search_results = []
            for row in raw_results:
                try:
                    # 더 정교한 텍스트 매칭 점수 계산
                    content_lower = row['content'].lower()
                    query_lower = query.lower()
                    query_words = query_lower.split()
                    
                    if not query_words:
                        similarity_score = 0.5
                    else:
                        # 1. 정확한 단어 매칭 점수
                        matched_words = sum(1 for word in query_words if word in content_lower)
                        word_match_score = matched_words / len(query_words)
                        
                        # 2. 부분 문자열 매칭 점수
                        substring_matches = sum(1 for word in query_words 
                                              if any(word in content_word for content_word in content_lower.split()))
                        substring_score = substring_matches / len(query_words)
                        
                        # 3. 전체 쿼리가 포함되어 있는지 확인
                        full_query_match = 0.3 if query_lower in content_lower else 0.0
                        
                        # 4. 가중 평균으로 최종 점수 계산
                        similarity_score = (
                            word_match_score * 0.6 +      # 정확한 단어 매칭 60%
                            substring_score * 0.2 +       # 부분 매칭 20%
                            full_query_match * 0.2        # 전체 쿼리 매칭 20%
                        )
                        
                        # 점수를 0.1 ~ 1.0 범위로 조정 (0.0은 너무 낮음)
                        similarity_score = max(0.1, min(1.0, similarity_score))
                    
                    search_result = SearchResult(
                        id=row['id'],
                        content=row['content'],
                        similarity_score=similarity_score,
                        created_at=row['created_at'],
                        project_id=row['project_id'],
                        category=row['category'],
                        source=row['source']
                    )
                    search_results.append(search_result)
                except Exception as e:
                    logger.warning(f"Failed to process text search result: {e}")
                    continue
            
            # 점수순으로 정렬
            search_results.sort(key=lambda x: x.similarity_score, reverse=True)
            
            logger.info(f"Found {len(search_results)} text search results")
            return SearchResponse(results=search_results)
            
        except Exception as e:
            logger.error(f"Text search failed: {e}")
            return SearchResponse(results=[])