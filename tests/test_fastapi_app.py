"""
FastAPI 애플리케이션 테스트
"""

import pytest
import tempfile
import os
import asyncio
from fastapi.testclient import TestClient

from app.web.app import app
from app.core.config import Settings
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.memory import MemoryService
from app.core.services.legacy.search import SearchService
from app.core.services.context import ContextService
from app.core.services.stats import StatsService
import app.web.app as main_module


@pytest.fixture
def temp_db():
    """임시 데이터베이스 생성"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def test_settings(temp_db, monkeypatch):
    """테스트용 설정"""
    monkeypatch.setenv("MEM_MESH_DATABASE_PATH", temp_db)
    return Settings()


@pytest.fixture
async def initialized_services(test_settings):
    """서비스들을 초기화하고 전역 변수에 설정"""
    # 데이터베이스 연결
    db = Database(test_settings.database_path)
    await db.connect()

    # 임베딩 서비스 초기화
    embedding_service = EmbeddingService()

    # 비즈니스 서비스들 초기화
    memory_service = MemoryService(db, embedding_service)
    search_service = SearchService(db, embedding_service)
    context_service = ContextService(db, embedding_service)
    stats_service = StatsService(db)

    # 전역 변수에 설정
    main_module.db = db
    main_module.embedding_service = embedding_service
    main_module.memory_service = memory_service
    main_module.search_service = search_service
    main_module.context_service = context_service
    main_module.stats_service = stats_service

    yield {
        "db": db,
        "embedding_service": embedding_service,
        "memory_service": memory_service,
        "search_service": search_service,
        "context_service": context_service,
        "stats_service": stats_service,
    }

    # 정리
    await db.close()
    main_module.db = None
    main_module.embedding_service = None
    main_module.memory_service = None
    main_module.search_service = None
    main_module.context_service = None
    main_module.stats_service = None


@pytest.fixture
def client(initialized_services):
    """테스트 클라이언트"""
    return TestClient(app)


def test_root_endpoint(client):
    """루트 엔드포인트 테스트"""
    response = client.get("/api")
    assert response.status_code == 200

    data = response.json()
    assert data["name"] == "mem-mesh"
    assert data["status"] == "running"


def test_health_check(client):
    """헬스 체크 테스트"""
    response = client.get("/api/health")
    assert response.status_code == 200


def test_add_memory_endpoint(client):
    """메모리 추가 엔드포인트 테스트"""
    memory_data = {
        "content": "Test memory content for FastAPI endpoint testing",
        "project_id": "test-project",
        "category": "task",
        "source": "api-test",
        "tags": ["test", "api"],
    }

    response = client.post("/api/memories", json=memory_data)
    if response.status_code != 200:
        print(f"Error response: {response.status_code}")
        print(f"Error content: {response.text}")
    assert response.status_code == 200

    data = response.json()
    assert "id" in data
    assert data["status"] == "saved"
    assert "created_at" in data


def test_search_memories_endpoint(client):
    """메모리 검색 엔드포인트 테스트"""
    # 먼저 메모리 추가
    memory_data = {
        "content": "Searchable test memory for endpoint testing",
        "project_id": "search-test",
        "category": "task",
        "tags": ["search", "test"],
    }

    add_response = client.post("/api/memories", json=memory_data)
    assert add_response.status_code == 200

    # 검색 수행
    response = client.get(
        "/api/memories/search?query=searchable&project_id=search-test"
    )
    assert response.status_code == 200

    data = response.json()
    assert "results" in data
    assert len(data["results"]) > 0


def test_get_memory_context_endpoint(client):
    """메모리 맥락 조회 엔드포인트 테스트"""
    # 먼저 메모리 추가
    memory_data = {
        "content": "Context test memory for endpoint testing",
        "project_id": "context-test",
        "category": "task",
    }

    add_response = client.post("/api/memories", json=memory_data)
    assert add_response.status_code == 200
    memory_id = add_response.json()["id"]

    # 맥락 조회
    response = client.get(f"/api/memories/{memory_id}/context?depth=2")
    assert response.status_code == 200

    data = response.json()
    assert "primary_memory" in data
    assert "related_memories" in data


def test_update_memory_endpoint(client):
    """메모리 업데이트 엔드포인트 테스트"""
    # 먼저 메모리 추가
    memory_data = {
        "content": "Original content for update testing",
        "project_id": "update-test",
        "category": "task",
    }

    add_response = client.post("/api/memories", json=memory_data)
    assert add_response.status_code == 200
    memory_id = add_response.json()["id"]

    # 메모리 업데이트
    update_data = {"content": "Updated content for endpoint testing", "category": "bug"}

    response = client.put(f"/api/memories/{memory_id}", json=update_data)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "updated"
    assert "id" in data


def test_delete_memory_endpoint(client):
    """메모리 삭제 엔드포인트 테스트"""
    # 먼저 메모리 추가
    memory_data = {
        "content": "Memory to be deleted for endpoint testing",
        "project_id": "delete-test",
        "category": "task",
    }

    add_response = client.post("/api/memories", json=memory_data)
    assert add_response.status_code == 200
    memory_id = add_response.json()["id"]

    # 메모리 삭제
    response = client.delete(f"/api/memories/{memory_id}")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "deleted"


def test_nonexistent_memory_context(client):
    """존재하지 않는 메모리 맥락 조회 테스트"""
    response = client.get("/api/memories/nonexistent-id/context")
    assert response.status_code == 404


def test_invalid_memory_data(client):
    """잘못된 메모리 데이터 테스트"""
    invalid_data = {
        "content": "x",  # 너무 짧음
        "category": "invalid-category",
    }

    response = client.post("/api/memories", json=invalid_data)
    assert response.status_code == 422  # Validation error


def test_get_memory_stats_endpoint(client):
    """메모리 통계 조회 엔드포인트 테스트"""
    # 먼저 몇 개의 메모리 추가
    for i in range(3):
        memory_data = {
            "content": f"Stats test memory {i} for endpoint testing",
            "project_id": "stats-test",
            "category": "task" if i % 2 == 0 else "bug",
        }
        response = client.post("/api/memories", json=memory_data)
        assert response.status_code == 200

    # 전체 통계 조회
    response = client.get("/api/memories/stats")
    assert response.status_code == 200

    data = response.json()
    assert "total_memories" in data
    assert data["total_memories"] >= 3

    # 프로젝트별 통계 조회
    response = client.get("/api/memories/stats?project_id=stats-test")
    assert response.status_code == 200

    data = response.json()
    assert data["total_memories"] >= 3
