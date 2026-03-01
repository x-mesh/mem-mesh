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
        # 노이즈로 간주할 프로젝트 패턴
        self.noise_project_patterns = [
            r"^kiro-",  # kiro 프로젝트들
            r"^test-",  # 테스트 프로젝트
            r"^tmp-",  # 임시 프로젝트
            r"^temp-",  # 임시 프로젝트
            r"^demo-",  # 데모 프로젝트
        ]

        # 노이즈로 간주할 콘텐츠 패턴
        self.noise_content_patterns = [
            r"## Included Rules",  # 반복되는 규칙 텍스트
            r"I am providing you",  # 반복되는 프롬프트
            r"^\s*$",  # 빈 콘텐츠
            r"^test\s+test",  # 테스트 데이터
            r"^ok$",  # 단순 응답
            r"^yes$",  # 단순 응답
            r"^no$",  # 단순 응답
        ]

        # 유용한 프로젝트 (우선순위 높임)
        self.preferred_projects = [
            "mem-mesh",  # 모든 mem-mesh 관련 메모리 통합
            "mem-mesh-thread-summary-kr",
            "mem-mesh-conversations",
        ]

        # 최소 콘텐츠 길이 (config.py default=10과 일관성 유지, 합리적 중간값)
        self.min_content_length = 30

        # 최대 중복 허용 수
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
            # 1. 프로젝트 필터링
            if self._is_noise_project(result.project_id):
                noise_count += 1
                if aggressive:
                    continue
                # 점수 감소
                result.similarity_score *= 0.3

            # 2. 콘텐츠 패턴 필터링
            if self._is_noise_content(result.content):
                noise_count += 1
                if aggressive:
                    continue
                result.similarity_score *= 0.5

            # 3. 중복 콘텐츠 필터링
            content_hash = self._get_content_hash(result.content[:100])
            if content_hash in seen_content_hashes:
                seen_content_hashes[content_hash] += 1
                if seen_content_hashes[content_hash] > self.max_duplicates:
                    noise_count += 1
                    continue
                # 중복 항목 점수 감소
                result.similarity_score *= 0.8 ** seen_content_hashes[content_hash]
            else:
                seen_content_hashes[content_hash] = 1

            # 4. 최소 길이 체크
            if len(result.content) < self.min_content_length:
                noise_count += 1
                if aggressive:
                    continue
                result.similarity_score *= 0.7

            # 5. 프로젝트 힌트 부스팅
            if project_hint and result.project_id == project_hint:
                result.similarity_score *= 1.5

            # 6. 선호 프로젝트 부스팅
            if result.project_id in self.preferred_projects:
                result.similarity_score *= 1.3

            # 7. 쿼리 관련성 부스팅
            if self._check_query_relevance(query, result):
                result.similarity_score *= 1.2

            filtered.append(result)

        # 재정렬
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
        # 간단한 해시 (첫 100자 기준)
        return content[:100].strip().lower()

    def _check_query_relevance(self, query: str, result: SearchResult) -> bool:
        """쿼리 관련성 확인"""
        query_words = query.lower().split()
        content_lower = result.content.lower()

        # 모든 쿼리 단어가 콘텐츠에 있는지 확인
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

        # 컨텍스트 추출
        project_hint = None
        time_range = None
        aggressive = False

        if context:
            project_hint = context.get("project")
            time_range = context.get("time_range", "30d")
            aggressive = context.get("aggressive_filter", False)

        # 시간 필터링
        if time_range:
            response.results = self._filter_by_time(response.results, time_range)

        # 노이즈 필터링
        response.results = self.noise_filter.filter(
            response.results, query, project_hint, aggressive
        )

        # 결과 수 제한 (노이즈 감소)
        max_results = context.get("max_results", 10) if context else 10
        response.results = response.results[:max_results]

        # 총 개수 업데이트
        response.total = len(response.results)

        return response

    def _filter_by_time(
        self, results: List[SearchResult], time_range: str
    ) -> List[SearchResult]:
        """시간 기준 필터링"""

        # 현재 시간을 UTC로 설정
        now = datetime.now(timezone.utc)

        # 시간 범위 파싱 (예: '7d', '30d', 'today')
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
                # 문자열을 datetime으로 변환
                try:
                    if isinstance(result.created_at, str):
                        created = datetime.fromisoformat(
                            result.created_at.replace("Z", "+00:00")
                        )
                    else:
                        created = result.created_at

                    # 시간대 정보가 없는 경우 UTC로 가정
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)

                    if created >= cutoff:
                        filtered.append(result)
                        # 최신 데이터 부스팅
                        days_old = (now - created).days
                        if days_old < 7:
                            result.similarity_score *= 1.2
                        elif days_old < 30:
                            result.similarity_score *= 1.1
                except Exception as e:
                    logger.warning(f"Recency filter error: {e}")
                    # 날짜 파싱 실패 시 포함
                    filtered.append(result)
            else:
                # 날짜 없으면 포함
                filtered.append(result)

        return filtered or results  # 필터링 결과가 없으면 원본 반환
