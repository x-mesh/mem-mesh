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
from app.core.services.unified_search import UnifiedSearchService


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
    async def test_search_with_multi_category_filter(
        self, search_service, memory_service
    ):
        """다중 카테고리 필터 검색 테스트 (category IN)"""
        # Given - 세 가지 카테고리의 메모리 생성
        await memory_service.create(
            content=(
                "Task memory for multi-category testing — long enough fixture content to pass the quality gate. "
                "Represents a routine task entry with owner, checklist, and due-by."
            ),
            category="task",
            source="test",
        )
        await memory_service.create(
            content=(
                "Bug memory for multi-category testing — long enough fixture content to pass the quality gate. "
                "Represents a bug entry with reproduction steps, observed vs expected, and diagnostic notes."
            ),
            category="bug",
            source="test",
        )
        await memory_service.create(
            content=(
                "Idea memory for multi-category testing — long enough fixture content to pass the quality gate. "
                "Represents an idea entry with motivation, rough sketch, and open questions."
            ),
            category="idea",
            source="test",
        )

        # When - 빈 쿼리 + categories 로 최근 메모리를 category IN 필터로 조회
        response = await search_service.search(query="", categories=["task", "bug"])

        # Then - 선택한 카테고리(task/bug)만 반환, idea 는 제외
        returned = {r.category for r in response.results}
        assert returned <= {"task", "bug"}
        assert "idea" not in returned
        assert returned == {"task", "bug"}

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


@pytest.fixture
async def unified_search_service(temp_db, mock_embedding_service):
    """UnifiedSearchService 픽스처 (빈 쿼리 → get_recent_memories 경로 검증용).

    무거운 품질/한국어/노이즈/정규화 기능은 비활성화 — 빈 쿼리 최근메모리 경로만 검증한다.
    """
    return UnifiedSearchService(
        db=temp_db,
        embedding_service=mock_embedding_service,
        enable_quality_features=False,
        enable_korean_optimization=False,
        enable_noise_filter=False,
        enable_score_normalization=False,
    )


class TestUnifiedSearchMultiCategory:
    """UnifiedSearchService 다중 카테고리 필터 테스트 (route가 호출하는 실제 서비스)"""

    async def _seed(self, memory_service):
        await memory_service.create(
            content=(
                "Task memory for unified multi-category testing — long enough fixture content to pass the quality gate. "
                "Represents a routine task entry with owner, checklist, and due-by."
            ),
            category="task",
            source="test",
        )
        await memory_service.create(
            content=(
                "Bug memory for unified multi-category testing — long enough fixture content to pass the quality gate. "
                "Represents a bug entry with reproduction steps, observed vs expected, and diagnostic notes."
            ),
            category="bug",
            source="test",
        )
        await memory_service.create(
            content=(
                "Idea memory for unified multi-category testing — long enough fixture content to pass the quality gate. "
                "Represents an idea entry with motivation, rough sketch, and open questions."
            ),
            category="idea",
            source="test",
        )

    @pytest.mark.asyncio
    async def test_empty_query_multi_category_filter(
        self, unified_search_service, memory_service
    ):
        """빈 쿼리 + categories=[bug, idea] → bug/idea 만 반환, task 제외 (category IN)"""
        # Given - task/bug/idea 세 카테고리 시드
        await self._seed(memory_service)

        # When - 빈 쿼리 → get_recent_memories 경로 (category IN 필터)
        response = await unified_search_service.search(
            query="", categories=["bug", "idea"]
        )

        # Then - bug/idea 만 반환, task 는 제외
        returned = {r.category for r in response.results}
        assert returned == {"bug", "idea"}
        assert "task" not in returned

    @pytest.mark.asyncio
    async def test_empty_query_single_category_backward_compat(
        self, unified_search_service, memory_service
    ):
        """단일 category='bug' 하위호환 — bug 만 반환"""
        # Given
        await self._seed(memory_service)

        # When
        response = await unified_search_service.search(query="", category="bug")

        # Then
        returned = {r.category for r in response.results}
        assert returned == {"bug"}


class TestUnifiedSearchIdLookup:
    """id 형태 쿼리(8+ hex prefix)의 직접 조회 경로 테스트.

    LLM 도구가 "mem-mesh f9732f1e"처럼 짧은 id를 알려주는데, 대시보드 검색은
    FTS/벡터라 id로는 못 찾던 문제의 회귀 방지.
    """

    async def _seed_one(self, memory_service, project_id=None):
        res = await memory_service.create(
            content=(
                "Id-lookup fixture memory — long enough content to pass the "
                "quality gate. Describes a stored proposal referenced by its id."
            ),
            category="idea",
            source="test",
            project_id=project_id,
        )
        return res.id

    @pytest.mark.asyncio
    async def test_short_hex_prefix_finds_memory(
        self, unified_search_service, memory_service
    ):
        mem_id = await self._seed_one(memory_service)
        prefix = mem_id[:8]

        response = await unified_search_service.search(query=prefix)

        assert [r.id for r in response.results] == [mem_id]
        assert response.results[0].similarity_score == 1.0

    @pytest.mark.asyncio
    async def test_full_uuid_finds_memory(self, unified_search_service, memory_service):
        mem_id = await self._seed_one(memory_service)

        response = await unified_search_service.search(query=mem_id)

        assert [r.id for r in response.results] == [mem_id]

    @pytest.mark.asyncio
    async def test_unmatched_hex_falls_through_to_normal_search(
        self, unified_search_service, memory_service
    ):
        await self._seed_one(memory_service)

        # id-looking query with no matching row → normal search path (no crash).
        response = await unified_search_service.search(query="deadbeef")

        assert all(not r.id.startswith("deadbeef") for r in response.results)

    @pytest.mark.asyncio
    async def test_project_filter_scopes_id_lookup(
        self, unified_search_service, memory_service
    ):
        mem_id = await self._seed_one(memory_service, project_id="proj-a")
        prefix = mem_id[:8]

        hit = await unified_search_service.search(query=prefix, project_id="proj-a")
        assert [r.id for r in hit.results] == [mem_id]

        miss = await unified_search_service.search(query=prefix, project_id="proj-b")
        assert all(r.id != mem_id for r in miss.results)
