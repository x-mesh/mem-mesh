from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from app.core.services.memory_reconciler import MemoryReconcilerService
from app.web.common.dependencies import get_database, get_embedding_service
from app.web.dashboard.route_modules import curation, overview


@pytest.fixture
async def api(temp_db, monkeypatch):
    monkeypatch.setattr(
        curation,
        "resolve_service_llm",
        AsyncMock(
            return_value={
                "model": "test",
                "provider": "local",
                "base_url": "http://localhost:1234/v1",
                "api_key": "test",
            }
        ),
    )
    app = FastAPI()
    app.include_router(curation.router)
    app.include_router(overview.router)
    app.dependency_overrides[get_database] = lambda: temp_db
    app.dependency_overrides[get_embedding_service] = lambda: None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_policy_put_get_and_invalid_payload(api):
    payload = {"retain_evidence_content": False}
    saved = await api.put("/projects/test/policy", json=payload)
    assert saved.status_code == 200
    read = await api.get("/projects/test/policy")
    assert "allow_external_llm" not in read.json()
    assert read.json()["retain_evidence_content"] is False
    invalid = await api.put(
        "/projects/test/policy", json={"retain_evidence_content": []}
    )
    assert invalid.status_code == 422
    assert (await api.get("/projects/test/policy")).json() == read.json()


@pytest.mark.asyncio
async def test_run_create_scope_candidates_and_cancel(api, temp_db):
    from tests.test_memory_reconciler import _add_memory

    await _add_memory(temp_db, "m1", "Release requires review.")
    invalid = await api.post("/curation/reconciler/runs", json={"dry_run": True})
    assert invalid.status_code == 422
    response = await api.post(
        "/curation/reconciler/runs",
        json={"project_id": "reconciler-project", "dry_run": True},
    )
    assert response.status_code == 200
    run_id = response.json()["id"]
    service = MemoryReconcilerService(temp_db)
    await service._detect_run(run_id)
    path = f"/curation/reconciler/runs/{run_id}/candidates"
    assert (await api.get(path, params={"project_id": "other"})).status_code == 404
    candidates = await api.get(path, params={"project_id": "reconciler-project"})
    assert candidates.status_code == 200
    assert (await api.post(f"/curation/reconciler/runs/{run_id}/cancel")).json()[
        "status"
    ] == "cancelled"
    assert (await api.get("/curation/reconciler/runs/missing")).status_code == 404
    assert (
        await api.post(
            "/curation/reconciler/proposals/missing/decision",
            json={"decision": "approve", "expected_revision": 0},
        )
    ).status_code == 404
    assert (
        await api.post(
            "/curation/reconciler/results/missing/cancel", json={"expected_revision": 0}
        )
    ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configured,success",
    [(False, False), (True, True)],
)
async def test_judge_cli_uses_configured_llm_and_closes_database(
    monkeypatch, configured, success
):
    import scripts.evaluate_reconciler_judge as module

    db = SimpleNamespace(connect=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(module, "Database", Mock(return_value=db))
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(embedding_dim=4, relay_llm_timeout=5),
    )
    monkeypatch.setattr(
        module,
        "resolve_service_llm",
        AsyncMock(
            return_value={
                "api_key": "test" if configured else "",
                "model": "model",
                "provider": "openai",
                "base_url": "https://example.com/v1",
            }
        ),
    )
    build = Mock()
    monkeypatch.setattr(module, "build_relay_enricher", build)
    monkeypatch.setattr(module, "evaluate_cases", AsyncMock(return_value={"passed": 0}))
    suite = module.JudgeSuite(
        cases=[
            {
                "id": "one",
                "evidence": [
                    {"memory_id": "m1", "input_hash": "hash", "content": "fact"}
                ],
                "expected_actions": ["no_op"],
            }
        ]
    )
    if success:
        await module._run("unused", "test", suite)
        build.assert_called_once()
    else:
        with pytest.raises(ValueError):
            await module._run("unused", "test", suite)
        build.assert_not_called()
    db.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("error,status", [("conflict", 409), ("validation", 422)])
async def test_proposal_decision_maps_service_errors(api, monkeypatch, error, status):
    from app.core.errors import ReconcilerConflictError, ReconcilerValidationError

    exc = (
        ReconcilerConflictError("revision mismatch")
        if error == "conflict"
        else ReconcilerValidationError("held proposal")
    )
    monkeypatch.setattr(
        MemoryReconcilerService, "decide_proposal", AsyncMock(side_effect=exc)
    )
    response = await api.post(
        "/curation/reconciler/proposals/p1/decision",
        json={"decision": "approve", "expected_revision": 0},
    )
    assert response.status_code == status


@pytest.mark.asyncio
async def test_live_result_detail_and_revision_checked_cancel(api, temp_db):
    from tests.test_memory_reconciler import MergeProvider, _add_memory, _FakeEmbedding

    for mid in ("m1", "m2"):
        await _add_memory(temp_db, mid, "Release requires review.")
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    service = MemoryReconcilerService(
        temp_db,
        embedding_service=embedding,
        model="test",
        provider="local",
        llm_base_url="http://localhost:1234/v1",
        llm_configured=True,
    )
    response = await api.post(
        "/curation/reconciler/runs",
        json={"project_id": "reconciler-project", "dry_run": False},
    )
    assert response.status_code == 200
    await service._detect_run(response.json()["id"])
    judge = MergeProvider()
    judge.provider_name = "local"
    result = await service.process_next("worker", judge)
    assert "result_id" in result, result
    result_id = result["result_id"]
    path = f"/curation/reconciler/results/{result_id}"
    assert (await api.get(path, params={"project_id": "other"})).status_code == 404
    detail = await api.get(path, params={"project_id": "reconciler-project"})
    assert detail.status_code == 200
    assert len(detail.json()["sources"]) == 2
    assert (
        await api.post(path + "/cancel", json={"expected_revision": 0})
    ).status_code == 409
    assert (
        await api.post(path + "/cancel", json={"expected_revision": 1})
    ).status_code == 200
    assert (await api.get(path, params={"project_id": "reconciler-project"})).json()[
        "status"
    ] == "cancelled"
    assert (await temp_db.fetchone("SELECT COUNT(*) AS count FROM memories"))[
        "count"
    ] == 2
