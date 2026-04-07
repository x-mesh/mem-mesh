"""
노이즈 필터링 서비스
Noise filtering for search results
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from ..schemas.responses import SearchResponse, SearchResult

logger = logging.getLogger(__name__)


class NoiseFilter:
    """검색 결과 노이즈 필터"""

    def __init__(self):
        # Project patterns considered as noise
        self.noise_project_patterns = [
            r"^kiro-",  # kiro projects
            r"^test-",  # test projects
            r"^tmp-",  # temporary projects
            r"^temp-",  # temporary projects
            r"^demo-",  # demo projects
        ]

        # Content patterns considered as noise
        self.noise_content_patterns = [
            r"## Included Rules",  # Repeated rules text
            r"I am providing you",  # Repeated prompt text
            r"^\s*$",  # Empty content
            r"^test\s+test",  # Test data
            r"^ok$",  # Simple response
            r"^yes$",  # Simple response
            r"^no$",  # Simple response
        ]

        # Useful projects (raise priority)
        self.preferred_projects = [
            "mem-mesh",  # Consolidate all mem-mesh related memories
            "mem-mesh-thread-summary-kr",
            "mem-mesh-conversations",
        ]

        # Minimum content length (consistent with config.py default=10, reasonable middle value)
        self.min_content_length = 30

        # Maximum allowed duplicates
        self.max_duplicates = 3

    def filter(
        self,
        results: List[SearchResult],
        query: str,
        project_hint: Optional[str] = None,
        aggressive: bool = False,
    ) -> List[SearchResult]:
        """
        노이즈 필터링

        Args:
            results: 검색 결과
            query: 원본 쿼리
            project_hint: 프로젝트 힌트
            aggressive: 공격적 필터링 여부

        Returns:
            필터링된 결과
        """
        if not results:
            return results

        filtered = []
        seen_content_hashes = {}
        noise_count = 0

        for result in results:
            # 1. Project filtering
            if self._is_noise_project(result.project_id):
                noise_count += 1
                if aggressive:
                    continue
                # Reduce score
                result.similarity_score *= 0.3

            # 2. Content pattern filtering
            if self._is_noise_content(result.content):
                noise_count += 1
                if aggressive:
                    continue
                result.similarity_score *= 0.5

            # 3. Duplicate content filtering
            content_hash = self._get_content_hash(result.content[:100])
            if content_hash in seen_content_hashes:
                seen_content_hashes[content_hash] += 1
                if seen_content_hashes[content_hash] > self.max_duplicates:
                    noise_count += 1
                    continue
                # Reduce score for duplicate items
                result.similarity_score *= 0.8 ** seen_content_hashes[content_hash]
            else:
                seen_content_hashes[content_hash] = 1

            # 4. Minimum length check
            if len(result.content) < self.min_content_length:
                noise_count += 1
                if aggressive:
                    continue
                result.similarity_score *= 0.7

            # 5. Project hint boosting
            if project_hint and result.project_id == project_hint:
                result.similarity_score *= 1.5

            # 6. Preferred project boosting
            if result.project_id in self.preferred_projects:
                result.similarity_score *= 1.3

            # 7. Query relevance boosting
            if self._check_query_relevance(query, result):
                result.similarity_score *= 1.2

            filtered.append(result)

        # Re-sort
        filtered.sort(key=lambda x: x.similarity_score, reverse=True)

        if noise_count > 0:
            logger.info(
                f"Filtered {noise_count} noise results from {len(results)} total"
            )

        return filtered

    def _is_noise_project(self, project_id: Optional[str]) -> bool:
        """노이즈 프로젝트 확인"""
        if not project_id:
            return False

        for pattern in self.noise_project_patterns:
            if re.match(pattern, project_id):
                return True
        return False

    def _is_noise_content(self, content: str) -> bool:
        """노이즈 콘텐츠 확인"""
        for pattern in self.noise_content_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        return False

    def _get_content_hash(self, content: str) -> str:
        """콘텐츠 해시 생성"""
        # Simple hash (based on first 100 chars)
        return content[:100].strip().lower()

    def _check_query_relevance(self, query: str, result: SearchResult) -> bool:
        """쿼리 관련성 확인"""
        query_words = query.lower().split()
        content_lower = result.content.lower()

        # Check if all query words are in content
        matches = sum(1 for word in query_words if word in content_lower)
        return matches >= len(query_words) * 0.7


class SmartSearchFilter:
    """스마트 검색 필터 (컨텍스트 인식)"""

    def __init__(self):
        self.noise_filter = NoiseFilter()

    def apply(
        self, response: SearchResponse, query: str, context: Optional[dict] = None
    ) -> SearchResponse:
        """
        스마트 필터 적용

        Args:
            response: 검색 응답
            query: 원본 쿼리
            context: 컨텍스트 정보 (project, time_range 등)

        Returns:
            필터링된 응답
        """
        if not response.results:
            return response

        # Extract context
        project_hint = None
        time_range = None
        aggressive = False

        if context:
            project_hint = context.get("project")
            time_range = context.get("time_range", "30d")
            aggressive = context.get("aggressive_filter", False)

        # Time filtering
        if time_range:
            response.results = self._filter_by_time(response.results, time_range)

        # Noise filtering
        response.results = self.noise_filter.filter(
            response.results, query, project_hint, aggressive
        )

        # Limit result count (reduce noise)
        max_results = context.get("max_results", 10) if context else 10
        response.results = response.results[:max_results]

        # Update total count
        response.total = len(response.results)

        return response

    def _filter_by_time(
        self, results: List[SearchResult], time_range: str
    ) -> List[SearchResult]:
        """시간 기준 필터링"""

        # Set current time to UTC
        now = datetime.now(timezone.utc)

        # Parse time range (e.g. '7d', '30d', 'today')
        if time_range == "today":
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif time_range.endswith("d"):
            days = int(time_range[:-1])
            cutoff = now - timedelta(days=days)
        else:
            return results

        filtered = []
        for result in results:
            if result.created_at:
                # Convert string to datetime
                try:
                    if isinstance(result.created_at, str):
                        created = datetime.fromisoformat(
                            result.created_at.replace("Z", "+00:00")
                        )
                    else:
                        created = result.created_at

                    # Assume UTC if no timezone info
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)

                    if created >= cutoff:
                        filtered.append(result)
                        # Boost recent data
                        days_old = (now - created).days
                        if days_old < 7:
                            result.similarity_score *= 1.2
                        elif days_old < 30:
                            result.similarity_score *= 1.1
                except Exception as e:
                    logger.warning(f"Recency filter error: {e}")
                    # Include on date parse failure
                    filtered.append(result)
            else:
                # Include if no date
                filtered.append(result)

        return filtered or results  # Return original if filtering yields no results
