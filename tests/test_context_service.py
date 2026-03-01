"""
ContextService 테스트
"""

import pytest
import tempfile
import os
from datetime import datetime

from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.memory import MemoryService
from app.core.services.context import ContextService, ContextNotFoundError
from app.core.schemas.responses import ContextResponse


@pytest.fixture
def temp_db():
    """임시 데이터베이스 생성"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
async def db(temp_db):
    """데이터베이스 인스턴스"""
    database = Database(temp_db)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def embedding_service():
    """임베딩 서비스 인스턴스"""
    return EmbeddingService()


@pytest.fixture
def memory_service(db, embedding_service):
    """메모리 서비스 인스턴스"""
    return MemoryService(db, embedding_service)


@pytest.fixture
def context_service(db, embedding_service):
    """컨텍스트 서비스 인스턴스"""
    return ContextService(db, embedding_service)


@pytest.mark.asyncio
async def test_get_context_basic(context_service, memory_service):
    """기본 맥락 조회 테스트"""
    # 테스트 메모리 생성
    memory1 = await memory_service.create(
        content="Implemented user authentication system",
        project_id="test-project",
        category="task",
        source="test",
    )

    await memory_service.create(
        content="Added JWT token validation",
        project_id="test-project",
        category="task",
        source="test",
    )

    await memory_service.create(
        content="Fixed login bug in authentication",
        project_id="test-project",
        category="bug",
        source="test",
    )

    # 맥락 조회
    context = await context_service.get_context(memory1.id, depth=2)

    # 검증
    assert isinstance(context, ContextResponse)
    assert context.primary_memory.id == memory1.id
    assert context.primary_memory.similarity_score == 1.0
    assert len(context.related_memories) >= 1  # 관련 메모리가 있어야 함
    assert len(context.timeline) >= 2  # 최소 주요 메모리 + 관련 메모리 1개

    # timeline이 시간순으로 정렬되어 있는지 확인
    timeline_memories = [context.primary_memory] + context.related_memories
    timeline_dict = {mem.id: mem.created_at for mem in timeline_memories}

    for i in range(len(context.timeline) - 1):
        current_time = datetime.fromisoformat(
            timeline_dict[context.timeline[i]].replace("Z", "+00:00")
        )
        next_time = datetime.fromisoformat(
            timeline_dict[context.timeline[i + 1]].replace("Z", "+00:00")
        )
        assert current_time <= next_time


@pytest.mark.asyncio
async def test_get_context_with_project_filter(context_service, memory_service):
    """프로젝트 필터가 있는 맥락 조회 테스트"""
    # 다른 프로젝트의 메모리 생성
    memory1 = await memory_service.create(
        content="Authentication implementation",
        project_id="project-a",
        category="task",
        source="test",
    )

    await memory_service.create(
        content="Authentication testing",
        project_id="project-b",
        category="task",
        source="test",
    )

    await memory_service.create(
        content="Authentication documentation",
        project_id="project-a",
        category="task",
        source="test",
    )

    # project-a로 필터링된 맥락 조회
    context = await context_service.get_context(
        memory1.id, depth=2, project_id="project-a"
    )

    # project-a의 메모리만 포함되어야 함
    all_project_ids = [context.primary_memory.project_id]
    all_project_ids.extend(
        [
            mem.project_id
            for mem in context.related_memories
            if hasattr(mem, "project_id")
        ]
    )

    for project_id in all_project_ids:
        if project_id is not None:
            assert project_id == "project-a"


@pytest.mark.asyncio
async def test_get_context_relationship_classification(context_service, memory_service):
    """관계 분류 테스트"""
    # 시간차를 두고 메모리 생성
    await memory_service.create(
        content="Started authentication work",
        project_id="test-project",
        category="task",
        source="test",
    )

    # 시간 차이는 데이터베이스 타임스탬프로 자동 생성됨
    memory2 = await memory_service.create(
        content="Completed authentication implementation",
        project_id="test-project",
        category="task",
        source="test",
    )

    await memory_service.create(
        content="Authentication system is working perfectly",
        project_id="test-project",
        category="task",
        source="test",
    )

    # 맥락 조회
    context = await context_service.get_context(memory2.id, depth=2)

    # 관계 분류 확인
    relationships = [mem.relationship for mem in context.related_memories]
    assert len(relationships) > 0
    assert all(rel in ["before", "after", "similar"] for rel in relationships)


@pytest.mark.asyncio
async def test_get_context_depth_expansion(context_service, memory_service):
    """깊이 확장 테스트"""
    # 연관된 메모리들 생성
    memories = []
    for i in range(5):
        memory = await memory_service.create(
            content=f"Authentication step {i + 1}: implementing feature {i + 1}",
            project_id="test-project",
            category="task",
            source="test",
        )
        memories.append(memory)

    # 깊이 1로 조회
    context_depth1 = await context_service.get_context(memories[2].id, depth=1)

    # 깊이 3으로 조회
    context_depth3 = await context_service.get_context(memories[2].id, depth=3)

    # 깊이가 클수록 더 많은 관련 메모리를 찾아야 함
    assert len(context_depth3.related_memories) >= len(context_depth1.related_memories)
    assert len(context_depth3.timeline) >= len(context_depth1.timeline)


@pytest.mark.asyncio
async def test_get_context_nonexistent_memory(context_service):
    """존재하지 않는 메모리 조회 테스트"""
    with pytest.raises(ContextNotFoundError):
        await context_service.get_context("nonexistent-id")


@pytest.mark.asyncio
async def test_get_context_similarity_threshold(context_service, memory_service):
    """유사도 임계값 테스트"""
    # 완전히 다른 내용의 메모리들 생성
    memory1 = await memory_service.create(
        content="User authentication implementation with JWT tokens",
        project_id="test-project",
        category="task",
        source="test",
    )

    await memory_service.create(
        content="Database schema migration for products table",
        project_id="test-project",
        category="task",
        source="test",
    )

    # 맥락 조회
    context = await context_service.get_context(memory1.id, depth=2)

    # 유사도가 낮은 메모리는 포함되지 않을 수 있음
    if context.related_memories:
        for related in context.related_memories:
            assert related.similarity_score >= context_service.similarity_threshold


@pytest.mark.asyncio
async def test_get_context_empty_database(context_service, memory_service):
    """빈 데이터베이스에서 맥락 조회 테스트"""
    # 메모리 하나만 생성
    memory = await memory_service.create(
        content="Single memory in database",
        project_id="test-project",
        category="task",
        source="test",
    )

    # 맥락 조회
    context = await context_service.get_context(memory.id, depth=2)

    # 주요 메모리만 있고 관련 메모리는 없어야 함
    assert context.primary_memory.id == memory.id
    assert len(context.related_memories) == 0
    assert len(context.timeline) == 1
    assert context.timeline[0] == memory.id
