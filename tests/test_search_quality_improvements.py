"""
검색 품질 개선사항 테스트
Tests for search quality improvements
"""

from datetime import datetime, timedelta

import pytest

from app.core.schemas.responses import SearchResponse, SearchResult
from app.core.services.noise_filter import NoiseFilter, SmartSearchFilter


class TestNoiseFilter:
    """노이즈 필터 테스트"""

    def test_noise_project_filtering(self):
        """노이즈 프로젝트 필터링 테스트"""
        filter_service = NoiseFilter()

        results = [
            SearchResult(
                id="1",
                content="Valid content that is long enough to pass the minimum content length filter threshold",
                similarity_score=0.9,
                created_at=datetime.now().isoformat(),
                project_id="mem-mesh",
                category="task",
                source="test",
            ),
            SearchResult(
                id="2",
                content="Test content that is also long enough to pass the minimum content length filter threshold",
                similarity_score=0.8,
                created_at=datetime.now().isoformat(),
                project_id="test-project",
                category="task",
                source="test",
            ),
            SearchResult(
                id="3",
                content="Kiro content that is also long enough to pass the minimum content length filter threshold",
                similarity_score=0.7,
                created_at=datetime.now().isoformat(),
                project_id="kiro-test",
                category="task",
                source="test",
            ),
        ]

        # 비공격적 필터링
        filtered = filter_service.filter(results, "test query", aggressive=False)
        assert len(filtered) == 3  # 모두 포함되지만 점수 조정됨
        assert filtered[0].project_id == "mem-mesh"  # 선호 프로젝트가 최상위

        # 공격적 필터링
        filtered_aggressive = filter_service.filter(
            results, "test query", aggressive=True
        )
        assert len(filtered_aggressive) == 1  # 노이즈 프로젝트 제외
        assert filtered_aggressive[0].project_id == "mem-mesh"

    def test_noise_content_filtering(self):
        """노이즈 콘텐츠 필터링 테스트"""
        filter_service = NoiseFilter()

        results = [
            SearchResult(
                id="1",
                content="This is a meaningful content with enough length to pass the filter",
                similarity_score=0.9,
                created_at=datetime.now().isoformat(),
                project_id="mem-mesh",
                category="task",
                source="test",
            ),
            SearchResult(
                id="2",
                content="ok",
                similarity_score=0.8,
                created_at=datetime.now().isoformat(),
                project_id="mem-mesh",
                category="task",
                source="test",
            ),
            SearchResult(
                id="3",
                content="## Included Rules - This is a repeated rule text",
                similarity_score=0.7,
                created_at=datetime.now().isoformat(),
                project_id="mem-mesh",
                category="task",
                source="test",
            ),
        ]

        # 공격적 필터링
        filtered = filter_service.filter(results, "test query", aggressive=True)
        assert len(filtered) == 1  # 노이즈 콘텐츠 제외
        assert "meaningful content" in filtered[0].content

    def test_duplicate_content_filtering(self):
        """중복 콘텐츠 필터링 테스트"""
        filter_service = NoiseFilter()

        # 동일한 콘텐츠 5개
        results = [
            SearchResult(
                id=str(i),
                content="This is duplicate content that appears multiple times in search results",
                similarity_score=0.9 - (i * 0.1),
                created_at=datetime.now().isoformat(),
                project_id="mem-mesh",
                category="task",
                source="test",
            )
            for i in range(5)
        ]

        filtered = filter_service.filter(results, "test query", aggressive=False)
        # max_duplicates=3이므로 최대 3개까지만 허용
        assert len(filtered) <= 3

    def test_preferred_project_boosting(self):
        """선호 프로젝트 부스팅 테스트"""
        filter_service = NoiseFilter()

        results = [
            SearchResult(
                id="1",
                content="Content from other project with higher initial score",
                similarity_score=0.9,
                created_at=datetime.now().isoformat(),
                project_id="other-project",
                category="task",
                source="test",
            ),
            SearchResult(
                id="2",
                content="Content from mem-mesh project with lower initial score",
                similarity_score=0.7,
                created_at=datetime.now().isoformat(),
                project_id="mem-mesh",
                category="task",
                source="test",
            ),
        ]

        filtered = filter_service.filter(results, "test query", aggressive=False)
        # mem-mesh 프로젝트가 부스팅되어 최상위로
        assert filtered[0].project_id == "mem-mesh"
        assert filtered[0].similarity_score > results[0].similarity_score


class TestSmartSearchFilter:
    """스마트 검색 필터 테스트"""

    def test_time_range_filtering(self):
        """시간 범위 필터링 테스트"""
        filter_service = SmartSearchFilter()

        now = datetime.now()
        results = [
            SearchResult(
                id="1",
                content="Recent content",
                similarity_score=0.8,
                created_at=now.isoformat(),
                project_id="mem-mesh",
                category="task",
                source="test",
            ),
            SearchResult(
                id="2",
                content="Old content",
                similarity_score=0.9,
                created_at=(now - timedelta(days=60)).isoformat(),
                project_id="mem-mesh",
                category="task",
                source="test",
            ),
        ]

        response = SearchResponse(results=results, total=2)

        # 30일 필터
        context = {"time_range": "30d"}
        filtered_response = filter_service.apply(response, "test query", context)

        assert len(filtered_response.results) == 1
        assert filtered_response.results[0].id == "1"

    def test_context_aware_filtering(self):
        """컨텍스트 인식 필터링 테스트"""
        filter_service = SmartSearchFilter()

        results = [
            SearchResult(
                id=str(i),
                content=f"Content {i} with enough length to pass minimum requirements",
                similarity_score=0.9 - (i * 0.1),
                created_at=datetime.now().isoformat(),
                project_id="mem-mesh" if i % 2 == 0 else "other-project",
                category="task",
                source="test",
            )
            for i in range(10)
        ]

        response = SearchResponse(results=results, total=10)

        # 프로젝트 힌트와 결과 수 제한
        context = {"project": "mem-mesh", "max_results": 3, "aggressive_filter": False}

        filtered_response = filter_service.apply(response, "test query", context)

        # 최대 3개로 제한
        assert len(filtered_response.results) <= 3
        # mem-mesh 프로젝트가 우선순위
        assert filtered_response.results[0].project_id == "mem-mesh"


class TestMCPSearchIntegration:
    """MCP 검색 통합 테스트"""

    @pytest.mark.asyncio
    async def test_mcp_search_with_noise_filter(self):
        """MCP 검색에 노이즈 필터 적용 테스트"""
        # 이 테스트는 실제 MCP 도구와 통합하여 실행
        # 여기서는 구조만 정의
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
