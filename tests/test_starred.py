"""별표(star) 서비스 + REST 토글 테스트.

별표는 durable marker다 — 표시/필터 전용이고 라이프사이클이 없다:
- 없는 id 토글 → MemoryNotFoundError (조용한 성공 금지)
- 같은 상태 재요청 → 멱등 성공
- content update() 후에도 별표 유지 (targeted UPDATE라 지워지면 안 됨)
- 별표는 updated_at을 건드리지 않는다 (최신순 정렬이 클릭만으로 흔들리면 안 됨)
"""

import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database.base import Database
from app.core.errors import MemoryNotFoundError
from app.core.services.memory import MemoryService
from app.web.common.dependencies import get_memory_service
from app.web.dashboard.route_modules import memories as memories_route

# 100자 이상: quality gate 통과용 본문
LONG = (
    "This memory exercises the durable star flag and is padded well beyond the "
    "100-character quality-gate minimum so that create() accepts it in tests."
)


@pytest.fixture
async def temp_db():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    db = Database(db_path)
    await db.connect()
    yield db
    await db.close()

    for ext in ["", "-wal", "-shm"]:
        p = db_path + ext
        if os.path.exists(p):
            os.unlink(p)


@pytest.fixture
async def memory_service(temp_db, mock_embedding_service):
    return MemoryService(temp_db, mock_embedding_service)


class TestSetStarred:
    """MemoryService.set_starred"""

    @pytest.mark.asyncio
    async def test_new_memory_is_not_starred(self, memory_service):
        resp = await memory_service.create(content=LONG, source="test")
        saved = await memory_service.get(resp.id)
        assert saved.is_starred is False

    @pytest.mark.asyncio
    async def test_star_then_unstar_roundtrip(self, memory_service):
        resp = await memory_service.create(content=LONG, source="test")

        result = await memory_service.set_starred(resp.id, True)
        assert result == {"memory_id": resp.id, "is_starred": True}
        assert (await memory_service.get(resp.id)).is_starred is True

        result = await memory_service.set_starred(resp.id, False)
        assert result == {"memory_id": resp.id, "is_starred": False}
        assert (await memory_service.get(resp.id)).is_starred is False

    @pytest.mark.asyncio
    async def test_missing_memory_raises(self, memory_service):
        """F1: 없는 id는 조용히 성공하면 안 된다"""
        with pytest.raises(MemoryNotFoundError):
            await memory_service.set_starred("no-such-id", True)

    @pytest.mark.asyncio
    async def test_star_is_idempotent(self, memory_service):
        """F2: 이미 starred인 항목을 다시 star → 에러 아닌 멱등 성공"""
        resp = await memory_service.create(content=LONG, source="test")

        await memory_service.set_starred(resp.id, True)
        await memory_service.set_starred(resp.id, True)
        assert (await memory_service.get(resp.id)).is_starred is True

        # unstar도 동일
        await memory_service.set_starred(resp.id, False)
        await memory_service.set_starred(resp.id, False)
        assert (await memory_service.get(resp.id)).is_starred is False

    @pytest.mark.asyncio
    async def test_star_survives_content_update(self, memory_service):
        """F3: content 수정이 별표를 지우면 안 된다"""
        resp = await memory_service.create(content=LONG, source="test")
        await memory_service.set_starred(resp.id, True)

        await memory_service.update(
            memory_id=resp.id, content=LONG + " (edited content, still long enough)"
        )

        saved = await memory_service.get(resp.id)
        assert saved.is_starred is True
        assert "edited content" in saved.content

    @pytest.mark.asyncio
    async def test_star_does_not_bump_updated_at(self, memory_service):
        """별표는 콘텐츠 변경이 아니다 — 최신순 정렬이 클릭만으로 흔들리면 안 됨"""
        resp = await memory_service.create(content=LONG, source="test")
        before = (await memory_service.get(resp.id)).updated_at

        await memory_service.set_starred(resp.id, True)

        assert (await memory_service.get(resp.id)).updated_at == before

    @pytest.mark.asyncio
    async def test_star_isolated_per_memory(self, memory_service):
        """한 메모리의 별표가 다른 메모리에 번지면 안 된다"""
        a = await memory_service.create(content=LONG, source="test")
        b = await memory_service.create(content=LONG + " second one", source="test")

        await memory_service.set_starred(a.id, True)

        assert (await memory_service.get(a.id)).is_starred is True
        assert (await memory_service.get(b.id)).is_starred is False


class TestStarRestRoutes:
    """REST 토글: POST/DELETE /api/memories/{id}/star"""

    @pytest.fixture
    def client(self, memory_service):
        app = FastAPI()
        app.include_router(memories_route.router, prefix="/api")
        app.dependency_overrides[get_memory_service] = lambda: memory_service
        return TestClient(app)

    @pytest.mark.asyncio
    async def test_post_stars_and_delete_unstars(self, client, memory_service):
        resp = await memory_service.create(content=LONG, source="test")

        r = client.post(f"/api/memories/{resp.id}/star")
        assert r.status_code == 200
        assert r.json() == {"memory_id": resp.id, "is_starred": True}
        assert (await memory_service.get(resp.id)).is_starred is True

        r = client.delete(f"/api/memories/{resp.id}/star")
        assert r.status_code == 200
        assert r.json() == {"memory_id": resp.id, "is_starred": False}
        assert (await memory_service.get(resp.id)).is_starred is False

    def test_star_missing_memory_404(self, client):
        """F1: 없는 id → 404 (200 + 조용한 무시 금지)"""
        r = client.post("/api/memories/does-not-exist/star")
        assert r.status_code == 404

        r = client.delete("/api/memories/does-not-exist/star")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_star_route_is_idempotent(self, client, memory_service):
        """F2: 같은 상태 재요청도 200"""
        resp = await memory_service.create(content=LONG, source="test")

        assert client.post(f"/api/memories/{resp.id}/star").status_code == 200
        assert client.post(f"/api/memories/{resp.id}/star").status_code == 200
        assert (await memory_service.get(resp.id)).is_starred is True

    @pytest.mark.asyncio
    async def test_get_memory_exposes_is_starred(self, client, memory_service):
        resp = await memory_service.create(content=LONG, source="test")

        body = client.get(f"/api/memories/{resp.id}").json()
        assert body["is_starred"] is False

        client.post(f"/api/memories/{resp.id}/star")
        body = client.get(f"/api/memories/{resp.id}").json()
        assert body["is_starred"] is True

    @pytest.mark.asyncio
    async def test_star_route_does_not_shadow_delete_memory(
        self, client, memory_service
    ):
        """라우트 순서: DELETE /{id}/star가 DELETE /{id}(메모리 삭제)를 가리면 안 된다"""
        resp = await memory_service.create(content=LONG, source="test")

        # /star 서브패스는 별표만 해제 — 메모리는 살아 있어야 함
        client.delete(f"/api/memories/{resp.id}/star")
        assert await memory_service.get(resp.id) is not None

        # 진짜 삭제는 여전히 동작
        assert client.delete(f"/api/memories/{resp.id}").status_code == 200
        assert await memory_service.get(resp.id) is None
