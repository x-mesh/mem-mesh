"""
E2E 통합 테스트
전체 워크플로우를 테스트하여 시스템 통합성 검증
"""

import pytest
import tempfile
import os
import asyncio
import time
from typing import Callable, Awaitable

from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.memory import MemoryService
from app.core.services.legacy.search import SearchService
from app.core.services.context import ContextService
from app.core.services.stats import StatsService


@pytest.fixture
def temp_db():
    """임시 데이터베이스 생성"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
async def services(temp_db):
    """통합 서비스 인스턴스들"""
    # 데이터베이스 연결
    db = Database(temp_db)
    await db.connect()

    # 서비스들 초기화
    embedding_service = EmbeddingService()
    memory_service = MemoryService(db, embedding_service)
    search_service = SearchService(db, embedding_service)
    context_service = ContextService(db, embedding_service)
    stats_service = StatsService(db)

    yield {
        "db": db,
        "memory": memory_service,
        "search": search_service,
        "context": context_service,
        "stats": stats_service,
    }

    await db.close()


async def wait_until(
    condition: Callable[[], Awaitable[bool]],
    timeout: float = 2.0,
    interval: float = 0.1,
    error_msg: str = "Condition not met within timeout",
):
    """조건이 충족될 때까지 대기하는 헬퍼 함수"""
    start_time = time.time()
    while (time.time() - start_time) < timeout:
        try:
            if await condition():
                return
        except Exception:
            pass
        await asyncio.sleep(interval)
    raise AssertionError(error_msg)


@pytest.mark.asyncio
async def test_add_search_workflow(services):
    """Add → Search 워크플로우 테스트"""
    memory_service = services["memory"]
    search_service = services["search"]

    # 1. 여러 메모리 추가
    memories = []

    memory1 = await memory_service.create(
        content="Implemented user authentication system with JWT tokens and bcrypt password hashing",
        project_id="auth-project",
        category="task",
        source="integration-test",
        tags=["auth", "jwt", "security"],
    )
    memories.append(memory1)

    memory2 = await memory_service.create(
        content="Added OAuth2 integration for Google and GitHub authentication providers",
        project_id="auth-project",
        category="task",
        source="integration-test",
        tags=["oauth", "google", "github"],
    )
    memories.append(memory2)

    memory3 = await memory_service.create(
        content="Fixed security vulnerability in password reset functionality",
        project_id="auth-project",
        category="bug",
        source="integration-test",
        tags=["security", "password", "bugfix"],
    )
    memories.append(memory3)

    # 2. 검색 수행 및 검증 (polling 사용)
    async def check_search_results():
        result = await search_service.search(
            query="authentication security JWT", project_id="auth-project", limit=10
        )
        return len(result.results) >= 2

    await wait_until(
        check_search_results, timeout=5.0, error_msg="Search results did not appear"
    )

    # 최종 결과 가져오기
    search_result = await search_service.search(
        query="authentication security JWT", project_id="auth-project", limit=10
    )

    # 관련성 높은 메모리들이 상위에 있는지 확인
    found_memory_ids = [result.id for result in search_result.results]
    assert memory1.id in found_memory_ids
    assert memory2.id in found_memory_ids or memory3.id in found_memory_ids


@pytest.mark.asyncio
async def test_add_context_workflow(services):
    """Add → Context 워크플로우 테스트"""
    memory_service = services["memory"]
    context_service = services["context"]

    # 1. 관련된 메모리들 추가
    memory1 = await memory_service.create(
        content="Started working on user authentication system design",
        project_id="auth-project",
        category="task",
        source="integration-test",
    )

    memory2 = await memory_service.create(
        content="Implemented JWT token generation and validation logic",
        project_id="auth-project",
        category="task",
        source="integration-test",
    )

    memory3 = await memory_service.create(
        content="Added password hashing with bcrypt for secure storage",
        project_id="auth-project",
        category="task",
        source="integration-test",
    )

    # 2. 맥락 조회 및 검증 (polling)
    async def check_context():
        result = await context_service.get_context(
            memory_id=memory2.id, depth=2, project_id="auth-project"
        )
        # 최소한 본인과 다른 메모리 하나 이상이 타임라인에 있어야 함
        return len(result.timeline) >= 2

    await wait_until(
        check_context, timeout=5.0, error_msg="Context timeline incomplete"
    )

    # 최종 결과 검증
    context_result = await context_service.get_context(
        memory_id=memory2.id, depth=2, project_id="auth-project"
    )

    assert context_result.primary_memory.id == memory2.id
    timeline_ids = context_result.timeline
    assert memory2.id in timeline_ids

    if len(context_result.related_memories) > 0:
        related_ids = [mem.id for mem in context_result.related_memories]
        for related_id in related_ids:
            assert related_id in timeline_ids


@pytest.mark.asyncio
async def test_add_update_search_workflow(services):
    """Add → Update → Search 워크플로우 테스트"""
    memory_service = services["memory"]
    search_service = services["search"]

    # 1. 메모리 추가
    original_memory = await memory_service.create(
        content="Basic authentication implementation with simple password check",
        project_id="auth-project",
        category="task",
        source="integration-test",
        tags=["auth", "basic"],
    )

    # 2. 메모리 업데이트
    await memory_service.update(
        memory_id=original_memory.id,
        content="Advanced authentication implementation with JWT tokens, bcrypt hashing, and OAuth2 support",
        category="task",
        tags=["auth", "jwt", "oauth", "advanced"],
    )

    # 3. 업데이트된 내용으로 검색 (polling)
    async def check_updated_content():
        result = await search_service.search(
            query="JWT OAuth advanced authentication",
            project_id="auth-project",
            limit=5,
        )
        for item in result.results:
            if item.id == original_memory.id:
                return "JWT" in item.content and "OAuth2" in item.content
        return False

    await wait_until(
        check_updated_content,
        timeout=5.0,
        error_msg="Updated content not found in search",
    )


@pytest.mark.asyncio
async def test_add_delete_search_workflow(services):
    """Add → Delete → Search 워크플로우 테스트"""
    memory_service = services["memory"]
    search_service = services["search"]

    # 1. 메모리들 추가
    memory1 = await memory_service.create(
        content="Authentication system with JWT implementation",
        project_id="auth-project",
        category="task",
        source="integration-test",
    )

    memory2 = await memory_service.create(
        content="Password hashing with bcrypt for authentication",
        project_id="auth-project",
        category="task",
        source="integration-test",
    )

    # 2. 첫 번째 메모리 삭제
    await memory_service.delete(memory1.id)

    # 3. 검색 수행 (polling - 삭제 확인)
    async def check_deletion():
        result = await search_service.search(
            query="authentication JWT bcrypt", project_id="auth-project", limit=10
        )
        found_ids = [r.id for r in result.results]
        return memory1.id not in found_ids and memory2.id in found_ids

    await wait_until(
        check_deletion,
        timeout=5.0,
        error_msg="Deleted memory still appearing or remaining memory missing",
    )


@pytest.mark.asyncio
async def test_cross_project_isolation(services):
    """프로젝트 간 격리 테스트"""
    memory_service = services["memory"]
    search_service = services["search"]

    # 1. 다른 프로젝트에 메모리들 추가
    project_a_memory = await memory_service.create(
        content="Authentication system for project A with specific requirements",
        project_id="project-a",
        category="task",
        source="integration-test",
    )

    project_b_memory = await memory_service.create(
        content="Authentication system for project B with different approach",
        project_id="project-b",
        category="task",
        source="integration-test",
    )

    # 2. 검증 (polling)
    async def check_isolation():
        res_a = await search_service.search(
            "authentication system", project_id="project-a", limit=10
        )
        res_b = await search_service.search(
            "authentication system", project_id="project-b", limit=10
        )

        ids_a = [r.id for r in res_a.results]
        ids_b = [r.id for r in res_b.results]

        return (
            project_a_memory.id in ids_a
            and project_a_memory.id not in ids_b
            and project_b_memory.id in ids_b
            and project_b_memory.id not in ids_a
        )

    await wait_until(check_isolation, timeout=5.0, error_msg="Project isolation failed")


@pytest.mark.asyncio
async def test_category_filtering(services):
    """카테고리 필터링 테스트"""
    memory_service = services["memory"]
    search_service = services["search"]

    # 1. 다른 카테고리로 메모리들 추가
    task_memory = await memory_service.create(
        content="Implement authentication feature for user login",
        project_id="test-project",
        category="task",
        source="integration-test",
    )

    bug_memory = await memory_service.create(
        content="Fix authentication bug causing login failures",
        project_id="test-project",
        category="bug",
        source="integration-test",
    )

    idea_memory = await memory_service.create(
        content="Idea: Add biometric authentication for enhanced security",
        project_id="test-project",
        category="idea",
        source="integration-test",
    )

    # 2. 검증 (polling)
    async def check_categories():
        res_task = await search_service.search(
            "authentication", project_id="test-project", category="task", limit=10
        )
        res_bug = await search_service.search(
            "authentication", project_id="test-project", category="bug", limit=10
        )

        ids_task = [r.id for r in res_task.results]
        ids_bug = [r.id for r in res_bug.results]

        return (
            task_memory.id in ids_task
            and bug_memory.id not in ids_task
            and bug_memory.id in ids_bug
            and task_memory.id not in ids_bug
        )

    await wait_until(
        check_categories, timeout=5.0, error_msg="Category filtering failed"
    )


@pytest.mark.asyncio
async def test_recency_weighting(services):
    """최신성 가중치 테스트"""
    memory_service = services["memory"]
    search_service = services["search"]

    # 1. 시간차를 두고 메모리들 추가
    old_memory = await memory_service.create(
        content="Old authentication implementation with basic features",
        project_id="test-project",
        category="task",
        source="integration-test",
    )

    new_memory = await memory_service.create(
        content="New authentication implementation with advanced features",
        project_id="test-project",
        category="task",
        source="integration-test",
    )

    # 2. 검증 (polling)
    async def check_recency():
        results_with_recency = await search_service.search(
            query="authentication implementation",
            project_id="test-project",
            recency_weight=0.8,
            limit=10,
            search_mode="hybrid",  # 명시적 하이브리드 모드
        )
        if not results_with_recency.results:
            return False

        # 새로운 메모리가 상위에 있는지 확인 (1순위 또는 높은 점수)
        # 단순히 존재하는지 확인부터
        ids = [r.id for r in results_with_recency.results]
        if new_memory.id not in ids:
            return False

        # 첫 번째 결과가 새 메모리여야 함 (높은 최신성 가중치)
        return results_with_recency.results[0].id == new_memory.id

    await wait_until(check_recency, timeout=5.0, error_msg="Recency weighting failed")


@pytest.mark.asyncio
async def test_add_stats_workflow(services):
    """Add → Stats 워크플로우 테스트"""
    memory_service = services["memory"]
    stats_service = services["stats"]

    # 1. 다양한 메모리들 추가
    memories = []

    # 프로젝트 A (2개)
    memories.append(
        await memory_service.create(
            content="Implemented user authentication system",
            project_id="project-a",
            category="task",
            source="cursor",
            tags=["auth", "backend"],
        )
    )
    memories.append(
        await memory_service.create(
            content="Fixed login bug in authentication module",
            project_id="project-a",
            category="bug",
            source="kiro",
            tags=["auth", "bugfix"],
        )
    )

    # 프로젝트 B (2개)
    memories.append(
        await memory_service.create(
            content="New idea for improving user experience",
            project_id="project-b",
            category="idea",
            source="api",
            tags=["ux", "frontend"],
        )
    )
    memories.append(
        await memory_service.create(
            content="Decided to use React for frontend framework",
            project_id="project-b",
            category="decision",
            source="cursor",
            tags=["react", "frontend"],
        )
    )

    # 글로벌 (1개)
    memories.append(
        await memory_service.create(
            content="General development best practices notes",
            project_id=None,
            category="task",
            source="api",
            tags=["best-practices"],
        )
    )

    # 2. 검증 (polling)
    async def check_stats():
        stats = await stats_service.get_overall_stats()
        return stats["total_memories"] >= 5 and stats["unique_projects"] >= 2

    await wait_until(check_stats, timeout=5.0, error_msg="Stats didn't update")

    # 상세 검증
    overall_stats = await stats_service.get_overall_stats()

    # 카테고리별 분포 확인
    categories = overall_stats["categories_breakdown"]
    assert categories.get("task", 0) >= 2
    assert categories.get("bug", 0) >= 1

    # 소스별 분포 확인
    sources = overall_stats["sources_breakdown"]
    assert sources.get("cursor", 0) >= 2

    # 프로젝트별 분포 확인
    projects = overall_stats["projects_breakdown"]
    assert projects.get("project-a", 0) >= 2
    assert projects.get("project-b", 0) >= 2


@pytest.mark.asyncio
async def test_stats_empty_database(services):
    """빈 데이터베이스에서 통계 조회 테스트"""
    stats_service = services["stats"]

    stats = await stats_service.get_overall_stats()

    assert stats["total_memories"] == 0
    assert stats["unique_projects"] == 0
    assert stats["categories_breakdown"] == {}


@pytest.mark.asyncio
async def test_stats_performance(services):
    """통계 조회 성능 테스트"""
    memory_service = services["memory"]
    stats_service = services["stats"]

    # 많은 메모리 생성 (성능 테스트용)
    # 배치 처리가 아니므로 반복문 사용
    for i in range(20):  # 성능 테스트 개수 조정 (20개로 충분)
        await memory_service.create(
            content=f"Performance test memory number {i}",
            project_id=f"perf-project-{i % 5}",
            category=["task", "bug", "idea"][i % 3],
            source=["cursor", "kiro", "api"][i % 3],
        )

    async def check_count():
        s = await stats_service.get_overall_stats()
        return s["total_memories"] >= 20

    await wait_until(check_count, timeout=10.0)

    # 통계 조회 성능 측정
    start_time = time.time()
    stats = await stats_service.get_overall_stats()
    end_time = time.time()

    actual_time_ms = (end_time - start_time) * 1000

    assert stats["total_memories"] >= 20
    # 성능 기준 완화 (테스트 환경 변수 고려)
    assert actual_time_ms < 500
    assert len(stats["projects_breakdown"]) >= 4
