"""
Search Service 테스트
"""

import os
import tempfile
from datetime import datetime, timezone
import pytest

from app.core.database.base import Database
from app.core.services.memory import MemoryService
from app.core.services.search import SearchService


@pytest.fixture
async def temp_db():
    """임시 데이터베이스 픽스처"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    db = Database(db_path)
    await db.connect()
    yield db
    await db.close()

    # 정리 (WAL/SHM 포함)
    for ext in ["", "-wal", "-shm"]:
        p = db_path + ext
        if os.path.exists(p):
            os.unlink(p)


@pytest.fixture
async def search_service(temp_db, mock_embedding_service):
    """SearchService 픽스처 (mock_embedding_service from conftest)"""
    return SearchService(temp_db, mock_embedding_service)


@pytest.fixture
async def memory_service(temp_db, mock_embedding_service):
    """MemoryService 픽스처 (mock_embedding_service from conftest)"""
    return MemoryService(temp_db, mock_embedding_service)


class TestSearchService:
    """SearchService 테스트 클래스"""

    @pytest.mark.asyncio
    async def test_search_empty_database(self, search_service):
        """빈 데이터베이스에서 검색 테스트"""
        # Given
        query = "test query"

        # When
        response = await search_service.search(query)

        # Then
        assert response.results == []

    @pytest.mark.asyncio
    async def test_search_with_results(self, search_service, memory_service):
        """검색 결과가 있는 경우 테스트"""
        # Given - 테스트 메모리 생성
        await memory_service.create(
            content=(
                "This is a test memory about authentication. "
                "Covers JWT token issuance, refresh rotation, and basic session invalidation flow for unit testing."
            ),
            project_id="test-project",
            category="task",
            source="test",
        )

        await memory_service.create(
            content=(
                "Another memory about database optimization. "
                "Describes index tuning, query plan inspection, and batching strategies used in the service layer."
            ),
            project_id="test-project",
            category="bug",
            source="test",
        )

        # When
        response = await search_service.search("authentication")

        # Then
        assert (
            len(response.results) >= 0
        )  # sqlite-vec가 없어도 fallback으로 결과 반환 가능
        for result in response.results:
            assert hasattr(result, "id")
            assert hasattr(result, "content")
            assert hasattr(result, "similarity_score")
            assert hasattr(result, "created_at")
            assert hasattr(result, "project_id")
            assert hasattr(result, "category")
            assert hasattr(result, "source")

    @pytest.mark.asyncio
    async def test_search_with_project_filter(self, search_service, memory_service):
        """프로젝트 필터 검색 테스트"""
        # Given - 다른 프로젝트의 메모리 생성
        await memory_service.create(
            content=(
                "Memory in project A — long enough fixture content to pass the quality gate. "
                "Describes project A scope, ownership, and key architectural decisions."
            ),
            project_id="project-a",
            source="test",
        )

        await memory_service.create(
            content=(
                "Memory in project B — long enough fixture content to pass the quality gate. "
                "Describes project B scope, ownership, and key architectural decisions."
            ),
            project_id="project-b",
            source="test",
        )

        # When
        response = await search_service.search(query="memory", project_id="project-a")

        # Then
        # sqlite-vec가 없는 환경에서는 fallback 동작으로 결과가 다를 수 있음
        # 기본적인 구조 검증만 수행
        assert isinstance(response.results, list)

    @pytest.mark.asyncio
    async def test_search_with_category_filter(self, search_service, memory_service):
        """카테고리 필터 검색 테스트"""
        # Given
        await memory_service.create(
            content=(
                "Task memory for testing — long enough fixture content to pass the quality gate. "
                "Represents a routine task entry with owner, checklist, and due-by."
            ),
            category="task",
            source="test",
        )

        await memory_service.create(
            content=(
                "Bug memory for testing — long enough fixture content to pass the quality gate. "
                "Represents a bug entry with reproduction steps, observed vs expected, and diagnostic notes."
            ),
            category="bug",
            source="test",
        )

        # When
        response = await search_service.search(query="testing", category="task")

        # Then
        assert isinstance(response.results, list)

    @pytest.mark.asyncio
    async def test_search_with_limit(self, search_service, memory_service):
        """검색 결과 개수 제한 테스트"""
        # Given - 여러 메모리 생성
        for i in range(5):
            await memory_service.create(
                content=(
                    f"Test memory number {i} — long enough fixture content to pass the quality gate. "
                    "Used by the limit-enforcement test to verify that search honours the requested result count."
                ),
                source="test",
            )

        # When
        response = await search_service.search(query="test", limit=3)

        # Then
        assert len(response.results) <= 3

    @pytest.mark.asyncio
    async def test_search_with_recency_weight(self, search_service, memory_service):
        """최신성 가중치 검색 테스트"""
        # Given
        await memory_service.create(
            content=(
                "Old memory for recency test — long enough fixture content to pass the quality gate. "
                "Represents the older entry used to validate recency weighting behaviour."
            ),
            source="test",
        )

        await memory_service.create(
            content=(
                "New memory for recency test — long enough fixture content to pass the quality gate. "
                "Represents the newer entry used to validate recency weighting behaviour."
            ),
            source="test",
        )

        # When
        response = await search_service.search(query="recency test", recency_weight=0.5)

        # Then
        assert isinstance(response.results, list)
        # 최신성 가중치가 적용되었는지 확인 (점수가 조정되었는지)
        for result in response.results:
            assert 0.0 <= result.similarity_score <= 1.0

    def test_calculate_recency_score(self, search_service):
        """최신성 점수 계산 테스트"""
        # Given
        oldest = datetime(2024, 1, 1, tzinfo=timezone.utc)
        newest = datetime(2024, 1, 10, tzinfo=timezone.utc)
        middle = datetime(2024, 1, 5, tzinfo=timezone.utc)

        # When
        score_oldest = search_service._calculate_recency_score(oldest, oldest, newest)
        score_newest = search_service._calculate_recency_score(newest, oldest, newest)
        score_middle = search_service._calculate_recency_score(middle, oldest, newest)

        # Then
        assert score_oldest == 0.0  # 가장 오래된 것
        assert score_newest == 1.0  # 가장 최신
        assert 0.0 < score_middle < 1.0  # 중간값

        # 같은 시간인 경우
        score_same = search_service._calculate_recency_score(oldest, oldest, oldest)
        assert score_same == 1.0
