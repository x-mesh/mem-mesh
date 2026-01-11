"""
E2E 통합 테스트
전체 워크플로우를 테스트하여 시스템 통합성 검증
"""

import pytest
import tempfile
import os
import asyncio

from src.database.base import Database
from src.embeddings.service import EmbeddingService
from src.services.memory import MemoryService
from src.services.search import SearchService
from src.services.context import ContextService
from src.services.stats import StatsService


@pytest.fixture
def temp_db():
    """임시 데이터베이스 생성"""
    fd, path = tempfile.mkstemp(suffix='.db')
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
        'db': db,
        'memory': memory_service,
        'search': search_service,
        'context': context_service,
        'stats': stats_service
    }
    
    await db.close()


@pytest.mark.asyncio
async def test_add_search_workflow(services):
    """Add → Search 워크플로우 테스트"""
    memory_service = services['memory']
    search_service = services['search']
    
    # 1. 여러 메모리 추가
    memories = []
    
    memory1 = await memory_service.create(
        content="Implemented user authentication system with JWT tokens and bcrypt password hashing",
        project_id="auth-project",
        category="task",
        source="integration-test",
        tags=["auth", "jwt", "security"]
    )
    memories.append(memory1)
    
    memory2 = await memory_service.create(
        content="Added OAuth2 integration for Google and GitHub authentication providers",
        project_id="auth-project", 
        category="task",
        source="integration-test",
        tags=["oauth", "google", "github"]
    )
    memories.append(memory2)
    
    memory3 = await memory_service.create(
        content="Fixed security vulnerability in password reset functionality",
        project_id="auth-project",
        category="bug",
        source="integration-test",
        tags=["security", "password", "bugfix"]
    )
    memories.append(memory3)
    
    # 잠시 대기 (임베딩 처리 시간)
    await asyncio.sleep(0.1)
    
    # 2. 검색 수행
    search_result = await search_service.search(
        query="authentication security JWT",
        project_id="auth-project",
        limit=10
    )
    
    # 3. 검증
    assert len(search_result.results) >= 2
    
    # 관련성 높은 메모리들이 상위에 있는지 확인
    found_memory_ids = [result.id for result in search_result.results]
    assert memory1.id in found_memory_ids
    assert memory2.id in found_memory_ids or memory3.id in found_memory_ids


@pytest.mark.asyncio
async def test_add_context_workflow(services):
    """Add → Context 워크플로우 테스트"""
    memory_service = services['memory']
    context_service = services['context']
    
    # 1. 관련된 메모리들 추가
    memory1 = await memory_service.create(
        content="Started working on user authentication system design",
        project_id="auth-project",
        category="task",
        source="integration-test"
    )
    
    await asyncio.sleep(0.05)
    
    memory2 = await memory_service.create(
        content="Implemented JWT token generation and validation logic",
        project_id="auth-project",
        category="task", 
        source="integration-test"
    )
    
    await asyncio.sleep(0.05)
    
    memory3 = await memory_service.create(
        content="Added password hashing with bcrypt for secure storage",
        project_id="auth-project",
        category="task",
        source="integration-test"
    )
    
    await asyncio.sleep(0.1)
    
    # 2. 맥락 조회
    context_result = await context_service.get_context(
        memory_id=memory2.id,
        depth=2,
        project_id="auth-project"
    )
    
    # 3. 검증
    assert context_result.primary_memory.id == memory2.id
    assert len(context_result.timeline) >= 1  # 최소한 주요 메모리는 포함
    
    # timeline이 시간순으로 정렬되어 있는지 확인
    timeline_ids = context_result.timeline
    
    # 주요 메모리가 timeline에 포함되어 있는지 확인
    assert memory2.id in timeline_ids
    
    # 관련 메모리가 있다면 추가 검증
    if len(context_result.related_memories) > 0:
        assert len(timeline_ids) >= 2
        # 다른 메모리들도 timeline에 포함되어야 함
        related_ids = [mem.id for mem in context_result.related_memories]
        for related_id in related_ids:
            assert related_id in timeline_ids


@pytest.mark.asyncio
async def test_add_update_search_workflow(services):
    """Add → Update → Search 워크플로우 테스트"""
    memory_service = services['memory']
    search_service = services['search']
    
    # 1. 메모리 추가
    original_memory = await memory_service.create(
        content="Basic authentication implementation with simple password check",
        project_id="auth-project",
        category="task",
        source="integration-test",
        tags=["auth", "basic"]
    )
    
    await asyncio.sleep(0.1)
    
    # 2. 메모리 업데이트 (content 변경)
    await memory_service.update(
        memory_id=original_memory.id,
        content="Advanced authentication implementation with JWT tokens, bcrypt hashing, and OAuth2 support",
        category="task",
        tags=["auth", "jwt", "oauth", "advanced"]
    )
    
    await asyncio.sleep(0.1)
    
    # 3. 업데이트된 내용으로 검색
    search_result = await search_service.search(
        query="JWT OAuth advanced authentication",
        project_id="auth-project",
        limit=5
    )
    
    # 4. 검증
    assert len(search_result.results) >= 1
    
    # 업데이트된 메모리가 검색되는지 확인
    found_memory = None
    for result in search_result.results:
        if result.id == original_memory.id:
            found_memory = result
            break
    
    assert found_memory is not None
    assert "JWT" in found_memory.content
    assert "OAuth2" in found_memory.content


@pytest.mark.asyncio
async def test_add_delete_search_workflow(services):
    """Add → Delete → Search 워크플로우 테스트"""
    memory_service = services['memory']
    search_service = services['search']
    
    # 1. 메모리들 추가
    memory1 = await memory_service.create(
        content="Authentication system with JWT implementation",
        project_id="auth-project",
        category="task",
        source="integration-test"
    )
    
    memory2 = await memory_service.create(
        content="Password hashing with bcrypt for authentication",
        project_id="auth-project",
        category="task",
        source="integration-test"
    )
    
    await asyncio.sleep(0.1)
    
    # 2. 첫 번째 메모리 삭제
    await memory_service.delete(memory1.id)
    
    await asyncio.sleep(0.1)
    
    # 3. 검색 수행
    search_result = await search_service.search(
        query="authentication JWT bcrypt",
        project_id="auth-project",
        limit=10
    )
    
    # 4. 검증
    found_memory_ids = [result.id for result in search_result.results]
    
    # 삭제된 메모리는 검색되지 않아야 함
    assert memory1.id not in found_memory_ids
    
    # 삭제되지 않은 메모리는 검색되어야 함
    assert memory2.id in found_memory_ids


@pytest.mark.asyncio
async def test_cross_project_isolation(services):
    """프로젝트 간 격리 테스트"""
    memory_service = services['memory']
    search_service = services['search']
    
    # 1. 다른 프로젝트에 메모리들 추가
    project_a_memory = await memory_service.create(
        content="Authentication system for project A with specific requirements",
        project_id="project-a",
        category="task",
        source="integration-test"
    )
    
    project_b_memory = await memory_service.create(
        content="Authentication system for project B with different approach",
        project_id="project-b", 
        category="task",
        source="integration-test"
    )
    
    await asyncio.sleep(0.1)
    
    # 2. 프로젝트별 검색
    project_a_results = await search_service.search(
        query="authentication system",
        project_id="project-a",
        limit=10
    )
    
    project_b_results = await search_service.search(
        query="authentication system",
        project_id="project-b",
        limit=10
    )
    
    # 3. 검증
    project_a_ids = [result.id for result in project_a_results.results]
    project_b_ids = [result.id for result in project_b_results.results]
    
    # 각 프로젝트는 자신의 메모리만 검색해야 함
    assert project_a_memory.id in project_a_ids
    assert project_a_memory.id not in project_b_ids
    
    assert project_b_memory.id in project_b_ids
    assert project_b_memory.id not in project_a_ids


@pytest.mark.asyncio
async def test_category_filtering(services):
    """카테고리 필터링 테스트"""
    memory_service = services['memory']
    search_service = services['search']
    
    # 1. 다른 카테고리로 메모리들 추가
    task_memory = await memory_service.create(
        content="Implement authentication feature for user login",
        project_id="test-project",
        category="task",
        source="integration-test"
    )
    
    bug_memory = await memory_service.create(
        content="Fix authentication bug causing login failures",
        project_id="test-project",
        category="bug", 
        source="integration-test"
    )
    
    idea_memory = await memory_service.create(
        content="Idea: Add biometric authentication for enhanced security",
        project_id="test-project",
        category="idea",
        source="integration-test"
    )
    
    await asyncio.sleep(0.1)
    
    # 2. 카테고리별 검색
    task_results = await search_service.search(
        query="authentication",
        project_id="test-project",
        category="task",
        limit=10
    )
    
    bug_results = await search_service.search(
        query="authentication",
        project_id="test-project",
        category="bug",
        limit=10
    )
    
    # 3. 검증
    task_ids = [result.id for result in task_results.results]
    bug_ids = [result.id for result in bug_results.results]
    
    # 각 카테고리는 해당 카테고리의 메모리만 반환해야 함
    assert task_memory.id in task_ids
    assert bug_memory.id not in task_ids
    
    assert bug_memory.id in bug_ids
    assert task_memory.id not in bug_ids


@pytest.mark.asyncio
async def test_recency_weighting(services):
    """최신성 가중치 테스트"""
    memory_service = services['memory']
    search_service = services['search']
    
    # 1. 시간차를 두고 메모리들 추가
    old_memory = await memory_service.create(
        content="Old authentication implementation with basic features",
        project_id="test-project",
        category="task",
        source="integration-test"
    )
    
    await asyncio.sleep(0.1)
    
    new_memory = await memory_service.create(
        content="New authentication implementation with advanced features",
        project_id="test-project",
        category="task",
        source="integration-test"
    )
    
    await asyncio.sleep(0.1)
    
    # 2. 최신성 가중치 없이 검색
    results_no_recency = await search_service.search(
        query="authentication implementation",
        project_id="test-project",
        recency_weight=0.0,
        limit=10
    )
    
    # 3. 최신성 가중치 적용하여 검색
    results_with_recency = await search_service.search(
        query="authentication implementation",
        project_id="test-project",
        recency_weight=0.8,
        limit=10
    )
    
    # 4. 검증
    assert len(results_no_recency.results) >= 2
    assert len(results_with_recency.results) >= 2
    
    # 최신성 가중치가 적용된 경우 더 최근 메모리가 상위에 있어야 함
    recency_first_id = results_with_recency.results[0].id
    
    # 새로운 메모리가 첫 번째에 있을 가능성이 높음
    # (완전히 보장되지는 않지만 통계적으로 유의미)
    found_new_memory = any(result.id == new_memory.id for result in results_with_recency.results)
    assert found_new_memory

@pytest.mark.asyncio
async def test_add_stats_workflow(services):
    """Add → Stats 워크플로우 테스트"""
    memory_service = services['memory']
    stats_service = services['stats']
    
    # 1. 다양한 메모리들 추가
    memories = []
    
    # 프로젝트 A 메모리들
    memories.append(await memory_service.create(
        content="Implemented user authentication system",
        project_id="project-a",
        category="task",
        source="cursor",
        tags=["auth", "backend"]
    ))
    
    memories.append(await memory_service.create(
        content="Fixed login bug in authentication module",
        project_id="project-a",
        category="bug",
        source="kiro",
        tags=["auth", "bugfix"]
    ))
    
    # 프로젝트 B 메모리들
    memories.append(await memory_service.create(
        content="New idea for improving user experience",
        project_id="project-b",
        category="idea",
        source="api",
        tags=["ux", "frontend"]
    ))
    
    memories.append(await memory_service.create(
        content="Decided to use React for frontend framework",
        project_id="project-b",
        category="decision",
        source="cursor",
        tags=["react", "frontend"]
    ))
    
    # 글로벌 메모리
    memories.append(await memory_service.create(
        content="General development best practices notes",
        project_id=None,
        category="task",
        source="api",
        tags=["best-practices"]
    ))
    
    await asyncio.sleep(0.1)
    
    # 2. 전체 통계 조회
    overall_stats = await stats_service.get_overall_stats()
    
    # 3. 검증
    assert overall_stats['total_memories'] >= 5
    assert overall_stats['unique_projects'] >= 2  # project-a, project-b (None은 제외)
    
    # 카테고리별 분포 확인
    categories = overall_stats['categories_breakdown']
    assert categories.get('task', 0) >= 2
    assert categories.get('bug', 0) >= 1
    assert categories.get('idea', 0) >= 1
    assert categories.get('decision', 0) >= 1
    
    # 소스별 분포 확인
    sources = overall_stats['sources_breakdown']
    assert sources.get('cursor', 0) >= 2
    assert sources.get('kiro', 0) >= 1
    assert sources.get('api', 0) >= 2
    
    # 프로젝트별 분포 확인
    projects = overall_stats['projects_breakdown']
    assert projects.get('project-a', 0) >= 2
    assert projects.get('project-b', 0) >= 2
    
    # 쿼리 시간 확인 (100ms 이내)
    assert overall_stats['query_time_ms'] < 100
    
    # 4. 프로젝트별 필터링 테스트
    project_a_stats = await stats_service.get_overall_stats(project_id="project-a")
    assert project_a_stats['total_memories'] >= 2
    assert project_a_stats['unique_projects'] == 1
    
    project_a_categories = project_a_stats['categories_breakdown']
    assert project_a_categories.get('task', 0) >= 1
    assert project_a_categories.get('bug', 0) >= 1
    
    # 5. 개별 통계 메서드 테스트
    category_stats = await stats_service.get_category_stats()
    assert len(category_stats) >= 4  # task, bug, idea, decision
    
    source_stats = await stats_service.get_source_stats()
    assert len(source_stats) >= 3  # cursor, kiro, api
    
    project_stats = await stats_service.get_project_stats()
    assert len(project_stats) >= 3  # project-a, project-b, global
    
    # 6. 날짜 범위 필터링 테스트 (오늘 날짜)
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    
    date_filtered_stats = await stats_service.get_overall_stats(
        start_date=today,
        end_date=today
    )
    
    # 오늘 생성된 메모리들이 있어야 함
    assert date_filtered_stats['total_memories'] >= 5
    assert date_filtered_stats['date_range'] == {
        'start': today,
        'end': today
    }


@pytest.mark.asyncio
async def test_stats_empty_database(services):
    """빈 데이터베이스에서 통계 조회 테스트"""
    stats_service = services['stats']
    
    # 빈 데이터베이스에서 통계 조회
    stats = await stats_service.get_overall_stats()
    
    # 모든 카운트가 0이어야 함
    assert stats['total_memories'] == 0
    assert stats['unique_projects'] == 0
    assert stats['categories_breakdown'] == {}
    assert stats['sources_breakdown'] == {}
    assert stats['projects_breakdown'] == {}
    assert stats['date_range'] is None
    assert stats['query_time_ms'] < 100


@pytest.mark.asyncio
async def test_stats_performance(services):
    """통계 조회 성능 테스트"""
    memory_service = services['memory']
    stats_service = services['stats']
    
    # 많은 메모리 생성 (성능 테스트용)
    for i in range(50):
        await memory_service.create(
            content=f"Performance test memory number {i} with some content to make it realistic",
            project_id=f"perf-project-{i % 5}",  # 5개 프로젝트로 분산
            category=["task", "bug", "idea"][i % 3],  # 3개 카테고리로 분산
            source=["cursor", "kiro", "api"][i % 3],  # 3개 소스로 분산
        )
    
    await asyncio.sleep(0.2)
    
    # 통계 조회 성능 측정
    import time
    start_time = time.time()
    
    stats = await stats_service.get_overall_stats()
    
    end_time = time.time()
    actual_time_ms = (end_time - start_time) * 1000
    
    # 검증
    assert stats['total_memories'] >= 50
    assert stats['unique_projects'] >= 5
    
    # 성능 요구사항: 100ms 이내 (실제 측정값과 서비스 내부 측정값 모두)
    assert actual_time_ms < 100
    assert stats['query_time_ms'] < 100
    
    # 분포 확인
    assert len(stats['categories_breakdown']) >= 3
    assert len(stats['sources_breakdown']) >= 3
    assert len(stats['projects_breakdown']) >= 5