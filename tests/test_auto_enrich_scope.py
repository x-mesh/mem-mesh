"""auto-enrich 전역 스코프(subscribed | all) 테스트.

배경: auto-enrich는 프로젝트별 opt-in(기본 OFF)이었다. 프로젝트가 168개인 노드에서
하나만 켜져 있으면 "auto-enrich가 안 된다"로 보인다. 전역 스코프를 두어 전부 켤 수
있게 하되, 프로젝트별 토글은 두 모드에서 각각 opt-in / opt-out으로 살아 있어야 한다.

핵심 불변식:
- scope=subscribed: 행이 없으면 OFF (기존 동작 그대로 — 기본값)
- scope=all: 행이 없으면 ON, 명시적으로 끈 프로젝트는 제외 (opt-out이 전역을 이긴다)
- all 모드 스윕은 프로젝트 수에 상한을 두고 라운드로빈으로 돌아 꼬리가 굶지 않는다
- all 모드 스윕은 구독 행을 만들지 않는다 (scope를 되돌렸을 때 암묵적 opt-in이 남으면 안 됨)
"""

import os
import tempfile

import pytest

from app.core.database.base import Database
from app.core.services.maintenance import MaintenanceService


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
async def service(temp_db):
    svc = MaintenanceService(temp_db)
    await svc.ensure_schema()
    return svc


async def _seed_projects(db, *project_ids):
    """각 프로젝트에 메모리 1건씩 (all 스코프는 memories에서 프로젝트를 훑는다)"""
    for i, pid in enumerate(project_ids):
        await db.add_memory(
            {
                "id": f"m-{pid}-{i}",
                "content": f"memory for {pid}" * 5,
                "content_hash": f"h-{pid}-{i}",
                "project_id": pid,
                "category": "task",
                "source": "test",
                "client": None,
                "embedding": b"\x00" * 16,
                "tags": None,
                "created_at": "2026-07-11T00:00:00Z",
                "updated_at": "2026-07-11T00:00:00Z",
                "content_bytes": 10,
            }
        )


class _LlmOk:
    """worker_llm_ok를 통과시키는 최소 스텁 (스코프 로직만 보려고)"""


@pytest.fixture
def llm_ok(monkeypatch):
    async def _ok(self, settings):
        return True

    monkeypatch.setattr(MaintenanceService, "worker_llm_ok", _ok)
    return _LlmOk()


class TestScopeSetting:
    @pytest.mark.asyncio
    async def test_default_is_subscribed(self, service):
        """기본값은 기존 동작 — 마이그레이션 없이 안전하게 배포되어야 한다"""
        assert await service.get_auto_enrich_scope() == "subscribed"

    @pytest.mark.asyncio
    async def test_set_and_get(self, service):
        assert await service.set_auto_enrich_scope("all") == "all"
        assert await service.get_auto_enrich_scope() == "all"
        await service.set_auto_enrich_scope("subscribed")
        assert await service.get_auto_enrich_scope() == "subscribed"

    @pytest.mark.asyncio
    async def test_unknown_scope_rejected(self, service):
        with pytest.raises(ValueError):
            await service.set_auto_enrich_scope("everything")

    @pytest.mark.asyncio
    async def test_corrupt_value_falls_back_to_default(self, service, temp_db):
        await temp_db.set_app_config("auto_enrich.scope", "garbage")
        assert await service.get_auto_enrich_scope() == "subscribed"


class TestActiveGate:
    """auto_enrich_active — 쓰기 시점 훅과 스윕이 공유하는 게이트"""

    @pytest.mark.asyncio
    async def test_subscribed_scope_requires_optin(self, service, llm_ok):
        assert await service.auto_enrich_active("proj-a", llm_ok) is False

        await service.set_auto_enrich("proj-a", enabled=True)
        assert await service.auto_enrich_active("proj-a", llm_ok) is True

    @pytest.mark.asyncio
    async def test_all_scope_enables_projects_without_a_row(self, service, llm_ok):
        await service.set_auto_enrich_scope("all")
        assert await service.auto_enrich_active("never-configured", llm_ok) is True

    @pytest.mark.asyncio
    async def test_explicit_optout_beats_all_scope(self, service, llm_ok):
        """명시적으로 끈 프로젝트를 전역 'all'이 덮어쓰면 안 된다"""
        await service.set_auto_enrich("excluded", enabled=False)
        await service.set_auto_enrich_scope("all")

        assert await service.auto_enrich_active("excluded", llm_ok) is False
        assert await service.auto_enrich_active("other", llm_ok) is True

    @pytest.mark.asyncio
    async def test_llm_gate_still_applies_in_all_scope(self, service, monkeypatch):
        """LLM 미설정이면 큐에 쌓기만 하고 아무도 안 빼간다 — 적재 자체를 막아야 함"""

        async def _no_llm(self, settings):
            return False

        monkeypatch.setattr(MaintenanceService, "worker_llm_ok", _no_llm)
        await service.set_auto_enrich_scope("all")
        assert await service.auto_enrich_active("any", object()) is False


class TestSweepTargets:
    @pytest.mark.asyncio
    async def test_subscribed_scope_returns_only_enabled_rows(self, service, temp_db):
        await _seed_projects(temp_db, "a", "b", "c")
        await service.set_auto_enrich("b", enabled=True)

        targets = await service.next_auto_enrich_targets()
        assert [t.project_id for t in targets] == ["b"]

    @pytest.mark.asyncio
    async def test_all_scope_returns_every_project_minus_optouts(
        self, service, temp_db
    ):
        await _seed_projects(temp_db, "a", "b", "c")
        await service.set_auto_enrich("b", enabled=False)  # opt-out
        await service.set_auto_enrich_scope("all")

        targets = await service.next_auto_enrich_targets()
        assert sorted(t.project_id for t in targets) == ["a", "c"]

    @pytest.mark.asyncio
    async def test_all_scope_writes_no_subscription_rows(self, service, temp_db):
        """scope를 되돌렸을 때 암묵적 opt-in이 남아 있으면 안 된다"""
        await _seed_projects(temp_db, "a", "b", "c")
        await service.set_auto_enrich_scope("all")

        await service.next_auto_enrich_targets(limit=2)

        await service.set_auto_enrich_scope("subscribed")
        assert await service.next_auto_enrich_targets() == []

    @pytest.mark.asyncio
    async def test_round_robin_advances_and_wraps(self, service, temp_db):
        """상한이 걸린 스윕이 앞쪽만 반복해서 꼬리를 굶기면 안 된다"""
        await _seed_projects(temp_db, "a", "b", "c", "d", "e")
        await service.set_auto_enrich_scope("all")

        first = [t.project_id for t in await service.next_auto_enrich_targets(limit=2)]
        second = [t.project_id for t in await service.next_auto_enrich_targets(limit=2)]
        third = [t.project_id for t in await service.next_auto_enrich_targets(limit=2)]

        assert first == ["a", "b"]
        assert second == ["c", "d"]
        # 마지막 하나 + 앞으로 되감기
        assert third == ["e", "a"]

    @pytest.mark.asyncio
    async def test_limit_above_project_count_returns_all(self, service, temp_db):
        await _seed_projects(temp_db, "a", "b")
        await service.set_auto_enrich_scope("all")

        targets = await service.next_auto_enrich_targets(limit=50)
        assert sorted(t.project_id for t in targets) == ["a", "b"]


class TestWorkerSettingsApi:
    """설정 페이지가 쓰는 /api/settings/worker"""

    @pytest.fixture
    def client(self, temp_db):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.web.common.dependencies import get_database
        from app.web.dashboard.route_modules import settings_llm

        app = FastAPI()
        app.include_router(settings_llm.router, prefix="/api")
        app.dependency_overrides[get_database] = lambda: temp_db
        return TestClient(app)

    def test_get_exposes_scope_and_choices(self, client):
        body = client.get("/api/settings/worker").json()
        assert body["auto_enrich_scope"] == "subscribed"
        assert set(body["auto_enrich_scopes"]) == {"subscribed", "all"}

    def test_put_updates_scope(self, client):
        body = client.put(
            "/api/settings/worker", json={"auto_enrich_scope": "all"}
        ).json()
        assert body["auto_enrich_scope"] == "all"
        assert client.get("/api/settings/worker").json()["auto_enrich_scope"] == "all"

    def test_put_rejects_unknown_scope(self, client):
        r = client.put("/api/settings/worker", json={"auto_enrich_scope": "nope"})
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_saving_worker_tasks_preserves_unexposed_reconcile(
        self, client, temp_db
    ):
        """A node with reconcile on must not lose it when the page saves.

        The dashboard no longer renders a reconcile checkbox, so its save states
        a task list that can never contain reconcile. Replacing the stored list
        wholesale would silently disable both the worker task and write-time
        detection on any node that had it enabled.
        """
        await temp_db.set_app_config("relay.worker_tasks", "outbox,item,reconcile")
        await temp_db.set_app_config("reconcile.enabled", "true")

        resp = client.put(
            "/api/settings/worker", json={"worker_tasks": ["outbox", "aggregate"]}
        )
        assert resp.status_code == 200

        stored = await temp_db.get_app_config("relay.worker_tasks")
        tasks = stored.split(",")
        assert "reconcile" in tasks, "an unexposed task must survive a save"
        # What the page did submit still applies.
        assert "aggregate" in tasks
        assert "item" not in tasks
        assert await temp_db.get_app_config("reconcile.enabled") == "true"

    @pytest.mark.asyncio
    async def test_node_without_reconcile_stays_without_it(self, client, temp_db):
        """Carrying tasks over must not resurrect one that was never enabled."""
        await temp_db.set_app_config("relay.worker_tasks", "outbox,item")

        resp = client.put("/api/settings/worker", json={"worker_tasks": ["outbox"]})
        assert resp.status_code == 200

        stored = await temp_db.get_app_config("relay.worker_tasks")
        assert stored.split(",") == ["outbox"]
        assert await temp_db.get_app_config("reconcile.enabled") == "false"
