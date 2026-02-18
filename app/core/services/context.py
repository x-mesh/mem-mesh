"""
Context Service for mem-mesh
메모리 맥락 조회를 담당하는 서비스
"""

import json
import logging
from typing import Optional, List
from datetime import datetime, timezone

from ..database.base import Database
from ..embeddings.service import EmbeddingService
from ..schemas.requests import ContextParams
from ..schemas.responses import ContextResponse, RelatedMemory, SearchResult

logger = logging.getLogger(__name__)


class ContextNotFoundError(Exception):
    """맥락을 찾을 수 없을 때 발생하는 예외"""

    # Exception subclass - no additional implementation needed


class ContextService:
    """메모리 맥락 조회 서비스"""

    def __init__(self, db: Database, embedding_service: EmbeddingService):
        self.db = db
        self.embedding_service = embedding_service
        self.similarity_threshold = 0.3  # Context에서는 더 낮은 임계값 사용
        logger.info("ContextService initialized")

    async def get_context(
        self, memory_id: str, depth: int = 2, project_id: Optional[str] = None
    ) -> ContextResponse:
        """
        메모리 맥락 조회

        Args:
            memory_id: 주요 메모리 ID
            depth: 검색 깊이 (1-5)
            project_id: 프로젝트 필터

        Returns:
            ContextResponse: 맥락 조회 결과
        """
        logger.info(f"Getting context for memory_id: {memory_id}, depth: {depth}")

        # 1. 주요 메모리 로드
        primary_memory = await self._get_primary_memory(memory_id)
        if not primary_memory:
            raise ContextNotFoundError(f"Memory not found: {memory_id}")

        # 2. 관련 메모리 검색
        related_memories = await self._find_related_memories(
            primary_memory, depth, project_id
        )

        # 3. 시간순 정렬된 timeline 생성
        timeline = await self._create_timeline(primary_memory, related_memories)

        return ContextResponse(
            primary_memory=primary_memory,
            related_memories=related_memories,
            timeline=timeline,
        )

    async def _get_primary_memory(self, memory_id: str) -> Optional[SearchResult]:
        """주요 메모리 조회"""
        try:
            cursor = self.db.connection.cursor()
            cursor.execute(
                """
                SELECT id, content, created_at, project_id, category, source
                FROM memories 
                WHERE id = ?
            """,
                (memory_id,),
            )

            row = cursor.fetchone()
            if not row:
                return None

            return SearchResult(
                id=row[0],
                content=row[1],
                similarity_score=1.0,  # 주요 메모리는 완전 일치
                created_at=row[2],
                project_id=row[3],
                category=row[4],
                source=row[5],
            )
        except Exception as e:
            logger.error(f"Error getting primary memory: {e}")
            raise ContextNotFoundError(f"Failed to get memory: {memory_id}")

    async def _find_related_memories(
        self, primary_memory: SearchResult, depth: int, project_id: Optional[str]
    ) -> List[RelatedMemory]:
        """관련 메모리 검색"""
        try:
            # 텍스트 기반 검색 사용 (sqlite-vec 지원 없음)
            related_memories = await self._text_search(
                primary_memory, depth, project_id
            )

            # depth에 따른 확장 검색
            if depth > 1 and related_memories:
                related_memories = await self._expand_search(
                    related_memories, depth - 1, project_id or primary_memory.project_id
                )

            # 유사도 순으로 정렬하고 제한
            related_memories.sort(key=lambda x: x.similarity_score, reverse=True)
            return related_memories[: depth * 3]  # depth당 최대 3개

        except Exception as e:
            logger.error(f"Error finding related memories: {e}")
            return []

    async def _vector_search(
        self, primary_memory: SearchResult, depth: int, project_id: Optional[str]
    ) -> List[RelatedMemory]:
        """벡터 기반 검색"""
        try:
            # 주요 메모리의 임베딩 생성
            query_embedding = self.embedding_service.embed(primary_memory.content)
            query_bytes = self.embedding_service.to_bytes(query_embedding)

            # SQL 쿼리 구성
            where_conditions = ["id != ?"]  # 자기 자신 제외
            params = [primary_memory.id]

            if project_id:
                where_conditions.append("project_id = ?")
                params.append(project_id)
            elif primary_memory.project_id:
                where_conditions.append("project_id = ?")
                params.append(primary_memory.project_id)

            where_clause = " AND ".join(where_conditions)

            # 벡터 유사도 검색
            cursor = self.db.connection.cursor()
            cursor.execute(
                f"""
                SELECT 
                    id, content, created_at, project_id, category, source,
                    vec_distance_cosine(embedding, ?) as distance
                FROM memories 
                WHERE {where_clause}
                    AND vec_distance_cosine(embedding, ?) < ?
                ORDER BY distance ASC
                LIMIT ?
            """,
                params
                + [
                    query_bytes,
                    query_bytes,
                    1.0 - self.similarity_threshold,
                    depth * 5,
                ],
            )

            rows = cursor.fetchall()

            # RelatedMemory 객체로 변환 및 관계 분류
            related_memories = []
            primary_created_at = datetime.fromisoformat(
                primary_memory.created_at.replace("Z", "+00:00")
            )

            for row in rows:
                similarity_score = 1.0 - row[6]  # distance를 similarity로 변환
                created_at = datetime.fromisoformat(row[2].replace("Z", "+00:00"))

                # 관계 분류
                relationship = self._classify_relationship(
                    primary_created_at, created_at, similarity_score
                )

                related_memory = RelatedMemory(
                    id=row[0],
                    content=row[1],
                    similarity_score=similarity_score,
                    relationship=relationship,
                    created_at=row[2],
                    category=row[4],
                    project_id=row[3],
                )
                related_memories.append(related_memory)

            return related_memories

        except Exception as e:
            logger.warning(f"Vector search failed, falling back to text search: {e}")
            return []

    async def _text_search(
        self, primary_memory: SearchResult, depth: int, project_id: Optional[str]
    ) -> List[RelatedMemory]:
        """텍스트 기반 fallback 검색"""
        try:
            # 주요 메모리에서 키워드 추출 (간단한 방법)
            keywords = self._extract_keywords(primary_memory.content)
            if not keywords:
                return []

            # SQL 쿼리 구성
            where_conditions = ["id != ?"]  # 자기 자신 제외
            params = [primary_memory.id]

            if project_id:
                where_conditions.append("project_id = ?")
                params.append(project_id)
            elif primary_memory.project_id:
                where_conditions.append("project_id = ?")
                params.append(primary_memory.project_id)

            # 키워드 기반 검색 조건 추가
            keyword_conditions = []
            for keyword in keywords[:5]:  # 상위 5개 키워드만 사용
                keyword_conditions.append("content LIKE ?")
                params.append(f"%{keyword}%")

            if keyword_conditions:
                where_conditions.append(f"({' OR '.join(keyword_conditions)})")

            where_clause = " AND ".join(where_conditions)

            # 텍스트 검색 실행
            cursor = self.db.connection.cursor()
            cursor.execute(
                f"""
                SELECT id, content, created_at, project_id, category, source
                FROM memories 
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
            """,
                params + [depth * 5],
            )

            rows = cursor.fetchall()

            # RelatedMemory 객체로 변환
            related_memories = []
            primary_created_at = datetime.fromisoformat(
                primary_memory.created_at.replace("Z", "+00:00")
            )

            for row in rows:
                created_at = datetime.fromisoformat(row[2].replace("Z", "+00:00"))

                # 간단한 텍스트 유사도 계산
                similarity_score = self._calculate_text_similarity(
                    primary_memory.content, row[1]
                )

                # 관계 분류
                relationship = self._classify_relationship(
                    primary_created_at, created_at, similarity_score
                )

                related_memory = RelatedMemory(
                    id=row[0],
                    content=row[1],
                    similarity_score=similarity_score,
                    relationship=relationship,
                    created_at=row[2],
                    category=row[4],
                    project_id=row[3],
                )
                related_memories.append(related_memory)

            return related_memories

        except Exception as e:
            logger.error(f"Text search failed: {e}")
            return []

    def _extract_keywords(self, content: str) -> List[str]:
        """텍스트에서 키워드 추출"""
        import re

        # 간단한 키워드 추출 (단어 길이 3자 이상, 알파벳만)
        words = re.findall(r"\b[a-zA-Z]{3,}\b", content.lower())

        # 일반적인 단어 제외
        stop_words = {
            "the",
            "and",
            "for",
            "are",
            "but",
            "not",
            "you",
            "all",
            "can",
            "had",
            "her",
            "was",
            "one",
            "our",
            "out",
            "day",
            "get",
            "has",
            "him",
            "his",
            "how",
            "man",
            "new",
            "now",
            "old",
            "see",
            "two",
            "way",
            "who",
            "boy",
            "did",
            "its",
            "let",
            "put",
            "say",
            "she",
            "too",
            "use",
        }

        keywords = [word for word in words if word not in stop_words]

        # 빈도순으로 정렬 (간단한 방법)
        from collections import Counter

        word_counts = Counter(keywords)

        return [word for word, count in word_counts.most_common(10)]

    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """간단한 텍스트 유사도 계산"""
        words1 = set(self._extract_keywords(text1))
        words2 = set(self._extract_keywords(text2))

        if not words1 or not words2:
            return 0.0

        # Jaccard 유사도
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))

        return intersection / union if union > 0 else 0.0

    def _classify_relationship(
        self, primary_time: datetime, related_time: datetime, similarity_score: float
    ) -> str:
        """관계 분류 (before/after/similar)"""
        time_diff = (primary_time - related_time).total_seconds()

        # 높은 유사도면 'similar'
        if similarity_score > 0.8:
            return "similar"

        # 시간 차이로 before/after 결정
        if time_diff > 3600:  # 1시간 이상 차이
            return "before" if related_time < primary_time else "after"
        else:
            return "similar"  # 시간이 비슷하면 similar

    async def _expand_search(
        self,
        initial_memories: List[RelatedMemory],
        remaining_depth: int,
        project_id: Optional[str],
    ) -> List[RelatedMemory]:
        """깊이 기반 확장 검색"""
        if remaining_depth <= 0 or not initial_memories:
            return initial_memories

        expanded_memories = initial_memories.copy()
        processed_ids = {mem.id for mem in initial_memories}

        # 각 관련 메모리에 대해 추가 검색
        for memory in initial_memories[:3]:  # 상위 3개만 확장
            try:
                # 텍스트 기반 검색 사용 (sqlite-vec 지원 없음)
                additional_memories = await self._text_search_for_expansion(
                    memory, project_id, processed_ids
                )

                for additional_memory in additional_memories:
                    if additional_memory.id not in processed_ids:
                        expanded_memories.append(additional_memory)
                        processed_ids.add(additional_memory.id)

            except Exception as e:
                logger.warning(f"Error in expand search for memory {memory.id}: {e}")
                continue

        return expanded_memories

    async def _create_timeline(
        self, primary_memory: SearchResult, related_memories: List[RelatedMemory]
    ) -> List[str]:
        """시간순 timeline 생성"""
        # 모든 메모리를 시간순으로 정렬
        all_memories = []

        # 주요 메모리 추가
        primary_time = datetime.fromisoformat(
            primary_memory.created_at.replace("Z", "+00:00")
        )
        all_memories.append((primary_time, primary_memory.id))

        # 관련 메모리들 추가
        for memory in related_memories:
            memory_time = datetime.fromisoformat(
                memory.created_at.replace("Z", "+00:00")
            )
            all_memories.append((memory_time, memory.id))

        # 시간순 정렬
        all_memories.sort(key=lambda x: x[0])

        # ID만 추출하여 반환
        return [memory_id for _, memory_id in all_memories]

    async def _vector_search_for_expansion(
        self, memory: RelatedMemory, project_id: Optional[str], processed_ids: set
    ) -> List[RelatedMemory]:
        """확장 검색을 위한 벡터 검색"""
        try:
            query_embedding = self.embedding_service.embed(memory.content)
            query_bytes = self.embedding_service.to_bytes(query_embedding)

            where_conditions = []
            params = []

            # 이미 처리된 메모리들 제외
            placeholders = ",".join("?" * len(processed_ids))
            where_conditions.append(f"id NOT IN ({placeholders})")
            params.extend(list(processed_ids))

            if project_id:
                where_conditions.append("project_id = ?")
                params.append(project_id)

            where_clause = " AND ".join(where_conditions)

            cursor = self.db.connection.cursor()
            cursor.execute(
                f"""
                SELECT 
                    id, content, created_at, project_id, category, source,
                    vec_distance_cosine(embedding, ?) as distance
                FROM memories 
                WHERE {where_clause}
                    AND vec_distance_cosine(embedding, ?) < ?
                ORDER BY distance ASC
                LIMIT ?
            """,
                params + [query_bytes, query_bytes, 1.0 - self.similarity_threshold, 2],
            )

            rows = cursor.fetchall()

            additional_memories = []
            for row in rows:
                similarity_score = (1.0 - row[6]) * 0.8  # 간접 연결이므로 점수 감소
                created_at = datetime.fromisoformat(row[2].replace("Z", "+00:00"))
                memory_time = datetime.fromisoformat(
                    memory.created_at.replace("Z", "+00:00")
                )

                relationship = self._classify_relationship(
                    memory_time, created_at, similarity_score
                )

                expanded_memory = RelatedMemory(
                    id=row[0],
                    content=row[1],
                    similarity_score=similarity_score,
                    relationship=relationship,
                    created_at=row[2],
                    category=row[4],
                    project_id=row[3],
                )
                additional_memories.append(expanded_memory)

            return additional_memories

        except Exception as e:
            logger.warning(f"Vector expansion search failed: {e}")
            return []

    async def _text_search_for_expansion(
        self, memory: RelatedMemory, project_id: Optional[str], processed_ids: set
    ) -> List[RelatedMemory]:
        """확장 검색을 위한 텍스트 검색"""
        try:
            keywords = self._extract_keywords(memory.content)
            if not keywords:
                return []

            where_conditions = []
            params = []

            # 이미 처리된 메모리들 제외
            placeholders = ",".join("?" * len(processed_ids))
            where_conditions.append(f"id NOT IN ({placeholders})")
            params.extend(list(processed_ids))

            if project_id:
                where_conditions.append("project_id = ?")
                params.append(project_id)

            # 키워드 기반 검색 조건 추가
            keyword_conditions = []
            for keyword in keywords[:3]:  # 상위 3개 키워드만 사용
                keyword_conditions.append("content LIKE ?")
                params.append(f"%{keyword}%")

            if keyword_conditions:
                where_conditions.append(f"({' OR '.join(keyword_conditions)})")

            where_clause = " AND ".join(where_conditions)

            cursor = self.db.connection.cursor()
            cursor.execute(
                f"""
                SELECT id, content, created_at, project_id, category, source
                FROM memories 
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
            """,
                params + [2],
            )

            rows = cursor.fetchall()

            additional_memories = []
            for row in rows:
                created_at = datetime.fromisoformat(row[2].replace("Z", "+00:00"))
                memory_time = datetime.fromisoformat(
                    memory.created_at.replace("Z", "+00:00")
                )

                # 간단한 텍스트 유사도 계산 후 점수 감소
                similarity_score = (
                    self._calculate_text_similarity(memory.content, row[1]) * 0.8
                )

                relationship = self._classify_relationship(
                    memory_time, created_at, similarity_score
                )

                expanded_memory = RelatedMemory(
                    id=row[0],
                    content=row[1],
                    similarity_score=similarity_score,
                    relationship=relationship,
                    created_at=row[2],
                    category=row[4],
                    project_id=row[3],
                )
                additional_memories.append(expanded_memory)

            return additional_memories

        except Exception as e:
            logger.warning(f"Text expansion search failed: {e}")
            return []
