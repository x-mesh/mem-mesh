"""Memory Reconciler tests with temporary SQLite and mocked providers."""

import asyncio
import json
import struct
from datetime import datetime, timezone

import pytest

from app.core.services.memory_reconciler import (
    MemoryReconcilerService,
    ReconcilerConflictError,
    ReconcilerValidationError,
    is_external_llm_endpoint,
)


async def _add_memory(
    db,
    memory_id,
    content,
    *,
    project_id="reconciler-project",
    source="session",
    category="task",
    created_at="2026-10-19T10:00:00+00:00",
    protected=False,
):
    await db.add_memory(
        {
            "id": memory_id,
            "content": content,
            "content_hash": f"hash-{memory_id}",
            "project_id": project_id,
            "category": category,
            "status": "canonical",
            "source": source,
            "client": "test",
            "embedding": b"\x00" * 16,
            "tags": json.dumps(["reconciler"]),
            "anchors": json.dumps({"file_paths": ["app/core/reconciler.py"]}),
            "created_at": created_at,
            "updated_at": created_at,
            "reconciler_protected": protected,
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "new_time", ["2026-10-19T10:00:00+00:00", "2025-10-19T10:00:01+00:00"]
)
async def test_detector_splits_same_anchor_across_temporal_window(temp_db, new_time):
    for memory_id, timestamp in [
        ("old", "2024-10-19T10:00:00+00:00"),
        ("new", new_time),
    ]:
        await _add_memory(
            temp_db, memory_id, "Identical release facts.", created_at=timestamp
        )
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")
    candidates = await service.list_candidates(run["id"], "reconciler-project")
    assert candidates["total"] == 2
    assert run["budget"]["max_temporal_window_days"] == 365


@pytest.mark.asyncio
async def test_detector_accepts_exact_temporal_boundary_with_timezone(temp_db):
    await _add_memory(
        temp_db, "m1", "Identical release facts.", created_at="2025-10-19T10:00:00Z"
    )
    await _add_memory(
        temp_db,
        "m2",
        "Identical release facts.",
        created_at="2026-10-19T19:00:00+09:00",
    )
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")
    candidates = await service.list_candidates(run["id"], "reconciler-project")
    assert candidates["total"] == 1


@pytest.mark.asyncio
async def test_detector_rejects_unknown_creation_time(temp_db):
    await _add_memory(temp_db, "m1", "Identical release facts.", created_at="unknown")
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project", defer_detection=True)
    provider = MergeProvider()
    result = await service.process_next("worker-1", provider)
    assert "invalid memory creation time" in result["error"]
    assert (await service.get_run(run["id"]))["status"] == "failed"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_protected_memory_is_excluded_before_candidate_snapshot(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    await _add_memory(
        temp_db,
        "protected",
        "The same task has a third supported form that must stay private.",
        protected=True,
    )
    service = MemoryReconcilerService(temp_db)

    run = await service.create_run("reconciler-project")
    inputs = await temp_db.fetchall(
        "SELECT memory_id FROM reconciler_inputs WHERE run_id = ?", (run["id"],)
    )
    candidates = await service.list_candidates(run["id"], "reconciler-project")

    assert {row["memory_id"] for row in inputs} == {"m1", "m2"}
    assert candidates["candidates"][0]["memory_ids"] == ["m1", "m2"]


@pytest.mark.asyncio
async def test_protection_change_holds_queued_candidate_before_llm(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    await service.create_run("reconciler-project", dry_run=False)
    await temp_db.execute(
        "UPDATE memories SET reconciler_protected = 1 WHERE id = ?", ("m1",)
    )
    provider = MergeProvider()

    result = await service.process_next("worker-1", provider)

    assert result["status"] == "needs_review"
    assert "protected" in result["error"]
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_protecting_active_source_invalidates_derived_read(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    applied = await service.process_next("worker-1", MergeProvider())
    await temp_db.execute(
        "UPDATE memories SET reconciler_protected = 1 WHERE id = ?", ("m1",)
    )

    results = await service.effective_read.search(
        "supported", {"project_id": "reconciler-project"}, limit=5
    )
    stored = await temp_db.fetchone(
        "SELECT status FROM curated_results WHERE id = ?", (applied["result_id"],)
    )

    assert stored["status"] == "stale"
    assert {item.id for item in results.results} == {"m1", "m2"}


class MergeProvider:
    base_url = "http://127.0.0.1:8000/v1"

    def __init__(self, payload=None):
        self.payload = payload
        self.calls = 0

    async def reconcile_group(self, evidence):
        self.calls += 1
        if self.payload is not None:
            result = dict(self.payload)
            if (
                result.get("action") in {"merge", "supersede"}
                and "claims" not in result
            ):
                result["claims"] = [
                    {
                        "claim_id": "claim-1",
                        "text": result.get("body") or "The supported claim.",
                        "source_refs": [
                            {
                                "memory_id": item["memory_id"],
                                "input_hash": item["input_hash"],
                            }
                            for item in evidence
                        ],
                    }
                ]
            return result
        return {
            "action": "merge",
            "representative_memory_id": evidence[-1]["memory_id"],
            "body": "The reconciled body keeps the supported claim.",
            "claims": [
                {
                    "claim_id": "claim-1",
                    "text": "The supported claim.",
                    "source_refs": [
                        {
                            "memory_id": item["memory_id"],
                            "input_hash": item["input_hash"],
                        }
                        for item in evidence
                    ],
                }
            ],
        }


@pytest.mark.parametrize(
    "base_url,external",
    [
        ("", True),
        ("https://api.example.com/v1", True),
        ("http://jw-server:8000/v1", True),
        ("http://localhost:8000/v1", False),
        ("http://127.0.0.1:8000/v1", False),
        ("http://[::1]:8000/v1", False),
    ],
)
def test_external_llm_endpoint_classification(base_url, external):
    assert is_external_llm_endpoint(base_url) is external


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, False])
async def test_external_llm_uses_configured_provider_without_project_opt_in(
    temp_db, dry_run
):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db,
        llm_base_url="https://api.example.com/v1",
        embedding_service=_FakeEmbedding(temp_db.embedding_dim),
        llm_configured=True,
    )
    run = await service.create_run("reconciler-project", dry_run=dry_run)
    provider = MergeProvider()
    provider.base_url = "https://api.example.com/v1"
    result = await service.process_next("worker-1", provider)

    assert run["candidate_counts"]["pending_judgment"] == 1
    assert result["status"] == ("preview" if dry_run else "active")
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_run_requires_configured_llm_when_route_marks_it_unavailable(temp_db):
    from app.web.dashboard.route_modules.curation import get_reconciler_service

    service = await get_reconciler_service(
        temp_db, _FakeEmbedding(temp_db.embedding_dim)
    )

    with pytest.raises(ReconcilerValidationError, match="LLM is not configured"):
        await service.create_run("reconciler-project")


@pytest.mark.asyncio
async def test_unconfigured_llm_blocks_run_but_not_proposal_reads(temp_db):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.web.common.dependencies import get_database, get_embedding_service
    from app.web.dashboard.route_modules.curation import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_database] = lambda: temp_db
    app.dependency_overrides[get_embedding_service] = lambda: _FakeEmbedding(
        temp_db.embedding_dim
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        started = await client.post(
            "/api/curation/reconciler/runs",
            json={"project_id": "reconciler-project", "dry_run": True},
        )
        proposals = await client.get(
            "/api/curation/reconciler/proposals",
            params={"project_id": "reconciler-project"},
        )

    assert started.status_code == 422
    assert "LLM is not configured" in started.json()["detail"]
    assert proposals.status_code == 200
    assert proposals.json()["proposals"] == []


@pytest.mark.asyncio
async def test_worker_holds_candidate_when_judge_model_differs_from_run(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db, model="recorded-model")
    await service.create_run("reconciler-project")
    provider = MergeProvider()
    provider.model = "different-model"

    result = await service.process_next("worker-1", provider)

    assert result["status"] == "needs_review"
    assert "run model changed" in result["error"]
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_legacy_external_llm_flag_does_not_block_judgment(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    await service.set_policy("reconciler-project", {"allow_external_llm": True})
    await service.create_run("reconciler-project")
    await service.set_policy("reconciler-project", {"allow_external_llm": False})
    provider = MergeProvider()
    provider.base_url = "https://api.example.com/v1"

    result = await service.process_next("worker-1", provider)

    assert result["status"] == "preview"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_changed_processing_policy_holds_before_first_judge_call(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")
    await service.set_policy("reconciler-project", {"auto_derived_relations": True})
    provider = MergeProvider()
    result = await service.process_next("worker-1", provider)
    assert result["status"] == "needs_review"
    assert "policy changed" in result["error"]
    assert provider.calls == 0
    assert (await service.get_run(run["id"]))["stats"].get("llm_calls", 0) == 0


@pytest.mark.asyncio
async def test_policy_change_between_judge_and_repair_blocks_second_call(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    await service.create_run("reconciler-project")

    class ChangingProvider(MergeProvider):
        async def reconcile_group(self, evidence):
            self.calls += 1
            await service.set_policy(
                "reconciler-project", {"auto_derived_relations": True}
            )
            return {"action": "merge", "representative_memory_id": "outside"}

    provider = ChangingProvider()
    result = await service.process_next("worker-1", provider)
    assert result["status"] == "needs_review"
    assert "policy changed" in result["error"]
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_policy_change_during_embedding_prevents_auto_activation(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)

    class ChangingEmbedding(_FakeEmbedding):
        async def aembed(self, text):
            await service.set_policy(
                "reconciler-project", {"auto_derived_relations": True}
            )
            return await super().aembed(text)

    service.embedding_service = ChangingEmbedding(temp_db.embedding_dim)
    await service.create_run("reconciler-project", dry_run=False)
    result = await service.process_next("worker-1", MergeProvider())
    assert result["status"] == "needs_review"
    assert "policy changed" in result["error"]
    assert (
        await temp_db.fetchone("SELECT id FROM curated_results WHERE status = 'active'")
        is None
    )
    assert (
        await temp_db.fetchone(
            "SELECT id FROM reconciler_receipts WHERE operation = 'activation'"
        )
        is None
    )


@pytest.mark.asyncio
async def test_worker_does_not_judge_changed_canonical_input(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    await service.create_run("reconciler-project")
    await temp_db.execute(
        "UPDATE memories SET content = ?, content_hash = ? WHERE id = ?",
        ("A changed canonical source.", "changed-m1", "m1"),
    )
    provider = MergeProvider()

    result = await service.process_next("worker-1", provider)

    assert result["status"] == "needs_review"
    assert "canonical input hash changed" in result["error"]
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_worker_holds_source_with_stale_anchor_before_judgment(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    await temp_db.execute(
        "UPDATE memories SET stale_status = ? WHERE id = ?", ("stale", "m1")
    )
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project", dry_run=False)
    provider = MergeProvider()

    result = await service.process_next("worker-1", provider)

    assert result["status"] == "needs_review"
    assert "source anchor is stale" in result["error"]
    assert provider.calls == 0
    assert (await service.get_run(run["id"]))["status"] == "completed"
    assert not await temp_db.fetchone(
        "SELECT id FROM curated_results WHERE status = 'active'"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("other_project", [False, True])
async def test_legacy_reconcile_uses_common_llm_without_project_opt_in(
    temp_db, other_project
):
    class LegacyProvider:
        base_url = "https://api.example.com/v1"

        def __init__(self):
            self.calls = 0

        async def reconcile(self, new_content, old_content):
            self.calls += 1
            return {"verdict": "keep_both"}

    await _add_memory(
        temp_db,
        "m1",
        "The same task has an older supported form.",
        created_at="2026-10-01T10:00:00+00:00",
    )
    await _add_memory(
        temp_db,
        "m2",
        "The same task has a newer supported form.",
        created_at="2026-10-19T10:00:00+00:00",
    )
    await temp_db.execute(
        "INSERT INTO reconcile_queue(id, new_memory_id, old_memory_id, similarity, new_content_hash, old_content_hash, status, next_attempt_at, created_at, updated_at) VALUES (?, ?, ?, 0.9, ?, ?, 'pending', 0, ?, ?)",
        (
            "legacy-1",
            "m2",
            "m1",
            "hash-m2",
            "hash-m1",
            "2026-10-20T00:00:00+00:00",
            "2026-10-20T00:00:00+00:00",
        ),
    )
    if other_project:
        await temp_db.execute(
            "UPDATE memories SET project_id = 'other' WHERE id = 'm1'"
        )
    service = MemoryReconcilerService(temp_db)
    provider = LegacyProvider()

    result = await service.process_next("worker-1", provider)
    row = await temp_db.fetchone(
        "SELECT status, last_error FROM reconcile_queue WHERE id = 'legacy-1'"
    )

    if other_project:
        assert provider.calls == 0
        assert result["processed"] is False
        assert row["status"] == "dead_letter"
        assert "project scope" in row["last_error"]
    else:
        assert provider.calls == 1
        assert result["processed"] is True
        assert row["status"] == "done"


@pytest.mark.asyncio
async def test_local_llm_run_needs_no_external_opt_in(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db, llm_base_url="http://[::1]:8000/v1")

    run = await service.create_run("reconciler-project")
    result = await service.process_next("worker-1", MergeProvider())

    assert run["dry_run"] == 1
    assert result["status"] == "preview"


@pytest.mark.asyncio
async def test_dashboard_retention_policy_does_not_gate_external_run_start(temp_db):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.web.dashboard.route_modules.curation import (
        get_reconciler_service as get_curation_reconciler,
    )
    from app.web.dashboard.route_modules.curation import router as curation_router
    from app.web.dashboard.route_modules.overview import (
        get_reconciler_service as get_policy_reconciler,
    )
    from app.web.dashboard.route_modules.overview import router as overview_router

    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, llm_base_url="https://api.example.com/v1"
    )
    app = FastAPI()
    app.include_router(curation_router, prefix="/api")
    app.include_router(overview_router, prefix="/api")
    app.dependency_overrides[get_curation_reconciler] = lambda: service
    app.dependency_overrides[get_policy_reconciler] = lambda: service

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        blocked = await client.post(
            "/api/curation/reconciler/runs",
            json={"project_id": "reconciler-project", "dry_run": True},
        )
        policy = await client.get("/api/projects/reconciler-project/policy")
        saved = await client.put(
            "/api/projects/reconciler-project/policy",
            json={"allow_external_llm": True, "retain_evidence_content": False},
        )
        allowed = await client.post(
            "/api/curation/reconciler/runs",
            json={"project_id": "reconciler-project", "dry_run": True},
        )

    assert blocked.status_code == 200
    assert "allow_external_llm" not in policy.json()
    assert "allow_external_llm" not in saved.json()
    assert saved.json()["retain_evidence_content"] is False
    assert (await service.get_policy("reconciler-project"))[
        "retain_evidence_content"
    ] is False
    assert allowed.status_code == 200


class _FakeEmbedding:
    model_name = "fake-reconciler-model"
    is_ready = True

    def __init__(self, dimension):
        self.dimension = dimension
        self.calls = []

    async def aembed(self, text):
        self.calls.append(text)
        return [0.25] * self.dimension

    @staticmethod
    def to_bytes(vector):
        import struct

        return struct.pack(f"{len(vector)}f", *vector)


@pytest.mark.asyncio
async def test_activation_without_embedding_service_does_not_reuse_source_vector(
    temp_db,
):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    await service.create_run("reconciler-project", dry_run=False)

    result = await service.process_next("worker-1", MergeProvider())

    assert result["processed"] is False
    assert "embedding service" in result["error"]
    assert not await temp_db.fetchone(
        "SELECT id FROM curated_results WHERE status = 'active'"
    )


@pytest.mark.asyncio
async def test_curated_vector_comes_from_synthesized_body(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    service = MemoryReconcilerService(temp_db, embedding_service=embedding)
    await service.create_run("reconciler-project", dry_run=False)

    result = await service.process_next("worker-1", MergeProvider())

    assert result["status"] == "active"
    assert embedding.calls == ["The reconciled body keeps the supported claim."]
    stored = await temp_db.fetchone(
        "SELECT embedding FROM curated_results_vec_fallback WHERE result_id = ?",
        (result["result_id"],),
    )
    assert bytes(stored["embedding"]) == embedding.to_bytes(
        [0.25] * temp_db.embedding_dim
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_index_entry", [False, True])
async def test_curated_semantic_search_uses_vec0_without_lexical_overlap(
    temp_db, stale_index_entry
):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    service = MemoryReconcilerService(temp_db, embedding_service=embedding)
    await service.create_run("reconciler-project", dry_run=False)
    applied = await service.process_next("worker-1", MergeProvider())
    if stale_index_entry:
        await temp_db.execute(
            "INSERT INTO curated_results_vec_active(result_id, embedding) VALUES (?, ?)",
            ("stale-result", json.dumps([0.25] * temp_db.embedding_dim)),
        )

    results = await service.effective_read.search_curated(
        "unrelated query vocabulary", filters={"project_id": "reconciler-project"}
    )

    assert [item.id for item in results] == [applied["result_id"]]
    assert results[0].similarity_score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_unversioned_active_curated_vector_requires_reindex(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    service = MemoryReconcilerService(temp_db, embedding_service=embedding)
    await service.create_run("reconciler-project", dry_run=False)
    assert (await service.process_next("worker-1", MergeProvider()))[
        "status"
    ] == "active"
    await temp_db.execute(
        "DELETE FROM embedding_metadata WHERE key IN ('reconciler_embedding_model', 'reconciler_embedding_dimension')"
    )

    with pytest.raises(ReconcilerValidationError, match="require reindex"):
        await service._write_indexes(
            "curated-probe", "New synthesized body", "reconciler-project"
        )

    assert await temp_db.get_embedding_metadata("reconciler_embedding_model") is None


@pytest.mark.asyncio
async def test_run_snapshots_without_mutating_canonical_rows(temp_db):
    await _add_memory(temp_db, "m1", "The same decision has a first supported form.")
    await _add_memory(temp_db, "m2", "The same decision has a second supported form.")
    before = [
        dict(row)
        for row in await temp_db.fetchall(
            "SELECT id, content, status, category, source, tags, anchors FROM memories ORDER BY id"
        )
    ]

    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")

    after = [
        dict(row)
        for row in await temp_db.fetchall(
            "SELECT id, content, status, category, source, tags, anchors FROM memories ORDER BY id"
        )
    ]
    assert run["candidate_counts"]["pending_judgment"] == 1
    assert before == after
    assert await temp_db.fetchone("SELECT COUNT(*) AS count FROM reconciler_inputs")


@pytest.mark.asyncio
async def test_run_scopes_candidates_by_anchor_and_created_time(temp_db):
    from app.core.schemas.reconciler import ReconcilerRunRequest

    await _add_memory(
        temp_db, "m1", "The same task has a first supported form.", source="import"
    )
    await _add_memory(
        temp_db, "m2", "The same task has a second supported form.", source="import"
    )
    await _add_memory(
        temp_db, "m3", "The same task has a third supported form.", source="import"
    )
    await _add_memory(
        temp_db,
        "m4",
        "The same task has an older supported form.",
        source="import",
        created_at="2026-09-01T10:00:00+00:00",
    )
    await temp_db.execute(
        "UPDATE memories SET anchors = ? WHERE id = ?",
        (json.dumps({"file_paths": ["ui/other.py"]}), "m3"),
    )
    request = ReconcilerRunRequest.model_validate(
        {
            "project_id": "reconciler-project",
            "dry_run": True,
            "anchored_path": "app/core/",
            "created_after": "2026-10-01T00:00:00+00:00",
            "created_before": "2026-10-20T00:00:00+00:00",
        }
    )
    service = MemoryReconcilerService(temp_db)

    run = await service.create_run(
        request.project_id,
        dry_run=request.dry_run,
        anchored_path=request.anchored_path,
        created_after=request.created_after,
        created_before=request.created_before,
    )

    assert run["stats"]["snapshot_count"] == 2
    assert run["stats"]["scope"]["anchored_path"] == "app/core"
    assert run["candidate_counts"] == {"pending_judgment": 1}
    candidate = await temp_db.fetchone(
        "SELECT memory_ids_json FROM reconciler_candidates WHERE run_id = ?",
        (run["id"],),
    )
    assert json.loads(candidate["memory_ids_json"]) == ["m1", "m2"]

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.web.dashboard.route_modules.curation import get_reconciler_service, router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_reconciler_service] = lambda: service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/curation/reconciler/runs", json=request.model_dump(mode="json")
        )
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["stats"]["snapshot_count"] == 0
    detected = await service.process_next("worker-1", MergeProvider())
    assert detected["run_id"] == response.json()["id"]
    assert (await service.get_run(detected["run_id"]))["stats"]["snapshot_count"] == 2
    assert response.json()["stats"]["scope"]["anchored_path"] == "app/core"


@pytest.mark.asyncio
async def test_detection_queue_keeps_overflow_retryable_and_skips_cancelled_run(
    temp_db, monkeypatch
):
    import app.core.services.memory_reconciler as reconciler_module

    monkeypatch.setattr(reconciler_module, "MAX_QUEUED_DETECTIONS", 1)
    await _add_memory(temp_db, "m1", "A standalone stored fact.", source="import")
    service = MemoryReconcilerService(temp_db)
    first = await service.create_run("reconciler-project", defer_detection=True)
    second = await service.create_run("reconciler-project", defer_detection=True)

    assert first["status"] == "queued"
    assert second["status"] == "retryable"
    assert first["stats"]["snapshot_count"] == 0
    await service.cancel_run(first["id"])
    detected = await service.process_next("worker-1", MergeProvider())

    assert detected["run_id"] == second["id"]
    assert (await service.get_run(first["id"]))["status"] == "cancelled"
    assert (await service.get_run(second["id"]))["stats"]["snapshot_count"] == 1


@pytest.mark.asyncio
async def test_candidate_is_reclaimed_as_soon_as_its_lease_expires(
    temp_db, monkeypatch
):
    import app.core.services.memory_reconciler as reconciler_module

    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db, lease_seconds=120)
    await service.create_run("reconciler-project")
    clock = 1000
    monkeypatch.setattr(reconciler_module, "_epoch", lambda: clock)
    first = await service._claim_candidate("worker-1")
    assert first is not None
    clock = 1119
    assert await service._claim_candidate("worker-2") is None
    clock = 1121
    second = await service._claim_candidate("worker-2")
    assert second is not None
    assert second["id"] == first["id"]
    row = await temp_db.fetchone(
        "SELECT lease_owner, lease_until FROM reconciler_candidates WHERE id = ?",
        (first["id"],),
    )
    assert row["lease_owner"] == "worker-2"
    assert row["lease_until"] == 1241


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["merge", "no_op", "error"])
async def test_late_judge_cannot_publish_after_candidate_lease_is_reclaimed(
    temp_db, monkeypatch, outcome
):
    import time

    import app.core.services.memory_reconciler as reconciler_module

    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db,
        embedding_service=_FakeEmbedding(temp_db.embedding_dim),
        lease_seconds=120,
    )
    await service.create_run("reconciler-project", dry_run=False)
    clock = time.time()
    monkeypatch.setattr(reconciler_module, "_epoch", lambda: clock)

    class LateProvider(MergeProvider):
        async def reconcile_group(self, evidence):
            nonlocal clock
            clock += 121
            assert await service._claim_candidate("worker-2") is not None
            if outcome == "error":
                raise TimeoutError("late provider failure")
            payload = await super().reconcile_group(evidence)
            payload["action"] = outcome
            return payload

    result = await service.process_next("worker-1", LateProvider())

    assert result["processed"] is False
    assert result["status"] == "lease_lost"
    row = await temp_db.fetchone(
        "SELECT status, lease_owner FROM reconciler_candidates"
    )
    assert dict(row) == {"status": "processing", "lease_owner": "worker-2"}
    assert await temp_db.fetchone("SELECT id FROM reconciler_proposals") is None
    assert await temp_db.fetchone("SELECT id FROM curated_results") is None


@pytest.mark.asyncio
async def test_expired_detection_lease_is_reclaimed(temp_db):
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project", defer_detection=True)
    claimed = await service._claim_detection_run("worker-1")
    assert claimed["id"] == run["id"]
    await temp_db.execute(
        "UPDATE reconciler_runs SET updated_at = ? WHERE id = ?",
        ("2020-01-01T00:00:00+00:00", run["id"]),
    )

    result = await service.process_next("worker-2", MergeProvider())

    assert result["run_id"] == run["id"]
    assert (await service.get_run(run["id"]))["status"] == "completed"


@pytest.mark.asyncio
async def test_deferred_detection_rejects_policy_change(temp_db):
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project", defer_detection=True)
    await service.set_policy("reconciler-project", {"auto_derived_relations": True})

    result = await service.process_next("worker-1", MergeProvider())

    assert result["run_id"] == run["id"]
    assert result["processed"] is False
    stored = await service.get_run(run["id"])
    assert stored["status"] == "failed"
    assert "policy changed" in stored["error"]
    assert stored["stats"]["snapshot_count"] == 0


@pytest.mark.asyncio
async def test_deferred_detection_rejects_detector_version_change(temp_db):
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project", defer_detection=True)
    await temp_db.execute(
        "UPDATE reconciler_runs SET detector_version = ? WHERE id = ?",
        ("candidate-old", run["id"]),
    )

    result = await service.process_next("worker-1", MergeProvider())

    assert result["processed"] is False
    assert "detector changed" in (await service.get_run(run["id"]))["error"]


@pytest.mark.asyncio
async def test_queued_wait_does_not_consume_judgment_time_budget(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project", defer_detection=True)
    await temp_db.execute(
        "UPDATE reconciler_runs SET created_at = ? WHERE id = ?",
        ("2020-01-01T00:00:00+00:00", run["id"]),
    )

    detected = await service.process_next("worker-1", MergeProvider())
    judged = await service.process_next("worker-1", MergeProvider())

    assert detected["run_id"] == run["id"]
    assert judged["status"] == "preview"
    assert (await service.get_run(run["id"]))["stats"]["llm_calls"] == 1


def test_run_scope_rejects_invalid_anchor_and_time_range():
    from pydantic import ValidationError

    from app.core.schemas.reconciler import ReconcilerRunRequest

    with pytest.raises(ValidationError):
        ReconcilerRunRequest(project_id="scope", anchored_path="../other")
    with pytest.raises(ValidationError):
        ReconcilerRunRequest(project_id="scope", created_after=datetime(2026, 10, 1))
    with pytest.raises(ValidationError):
        ReconcilerRunRequest(
            project_id="scope",
            created_after=datetime(2026, 10, 20, tzinfo=timezone.utc),
            created_before=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_explicit_scope_has_separate_candidate_dedup_key(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)

    broad = await service.create_run("reconciler-project")
    scoped = await service.create_run("reconciler-project", anchored_path="app/core")
    repeated = await service.create_run("reconciler-project", anchored_path="app/core")

    assert broad["candidate_counts"] == {"pending_judgment": 1}
    assert scoped["candidate_counts"] == {"pending_judgment": 1}
    assert repeated["candidate_counts"] == {}


@pytest.mark.asyncio
async def test_evidence_contains_detector_and_retrieval_context(temp_db):
    await _add_memory(temp_db, "m1", "# Shared task\nFirst supported form.")
    await _add_memory(temp_db, "m2", "# Shared task\nSecond supported form.")
    await temp_db.execute(
        "UPDATE memories SET access_count = 3, last_accessed_at = ? WHERE id = ?",
        ("2026-10-19T11:00:00+00:00", "m1"),
    )
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")
    candidate = await temp_db.fetchone(
        "SELECT * FROM reconciler_candidates WHERE run_id = ?", (run["id"],)
    )

    evidence = await service._evidence(dict(candidate))

    first = next(item for item in evidence if item["memory_id"] == "m1")
    assert first["title"] == "Shared task"
    assert first["retrieval_stats"] == {
        "access_count": 3,
        "last_accessed_at": "2026-10-19T11:00:00+00:00",
    }
    assert first["detector_signals"]


@pytest.mark.asyncio
async def test_no_retention_snapshots_exclude_raw_text_and_rehydrate_for_judgment(
    temp_db,
):
    await _add_memory(
        temp_db, "m1", "RAW_BODY_MARKER supported form one. sk-abcdefghijklmnop"
    )
    await _add_memory(temp_db, "m2", "RAW_BODY_MARKER supported form two.")
    await temp_db.execute(
        "UPDATE memories SET tags = ?, anchors = ? WHERE id = 'm1'",
        (
            json.dumps(["PRIVATE_TAG_MARKER"]),
            json.dumps({"file_paths": ["PRIVATE_ANCHOR_MARKER"]}),
        ),
    )
    await temp_db.execute(
        "INSERT INTO memory_relations(id, source_id, target_id, relation_type, strength, metadata, created_at, updated_at) VALUES ('rel-test', 'm1', 'm2', 'related', 1, ?, datetime('now'), datetime('now'))",
        (json.dumps({"note": "PRIVATE_RELATION_MARKER"}),),
    )
    service = MemoryReconcilerService(temp_db)
    await service.set_policy("reconciler-project", {"retain_evidence_content": False})
    run = await service.create_run("reconciler-project")
    assert run["stats"]["policy"]["retain_evidence_content"] is False
    stored = await temp_db.fetchall(
        "SELECT snapshot_json FROM reconciler_inputs WHERE run_id = ?", (run["id"],)
    )
    stored_text = json.dumps([json.loads(row["snapshot_json"]) for row in stored])
    for marker in (
        "RAW_BODY_MARKER",
        "PRIVATE_TAG_MARKER",
        "PRIVATE_ANCHOR_MARKER",
        "PRIVATE_RELATION_MARKER",
    ):
        assert marker not in stored_text
    assert all(
        json.loads(row["snapshot_json"])["content_retained"] is False for row in stored
    )

    class CaptureProvider(MergeProvider):
        async def reconcile_group(self, evidence):
            self.evidence = evidence
            return await super().reconcile_group(evidence)

    provider = CaptureProvider()
    result = await service.process_next("worker-1", provider)
    assert result["status"] == "preview"
    assert "RAW_BODY_MARKER" in json.dumps(provider.evidence)
    assert "sk-abcdefghijklmnop" not in json.dumps(provider.evidence)
    assert "PRIVATE_TAG_MARKER" not in json.dumps(provider.evidence)
    assert "PRIVATE_RELATION_MARKER" not in json.dumps(provider.evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_source", [False, True])
async def test_no_retention_reconstruction_keeps_hash_and_complete_payload_guards(
    temp_db, monkeypatch, changed_source
):
    import app.core.services.memory_reconciler as reconciler_module

    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    await service.set_policy("reconciler-project", {"retain_evidence_content": False})
    await service.create_run("reconciler-project")
    if changed_source:
        await temp_db.execute(
            "UPDATE memories SET content = 'Changed input' WHERE id = 'm1'"
        )
    else:
        candidate = dict(await temp_db.fetchone("SELECT * FROM reconciler_candidates"))
        evidence = await service._evidence(candidate)
        size = len(reconciler_module.canonical_json(evidence))
        monkeypatch.setattr(reconciler_module, "MAX_EVIDENCE_CHARS", size - 1)
    provider = MergeProvider()
    result = await service.process_next("worker-1", provider)
    assert result["status"] == "needs_review"
    assert provider.calls == 0
    assert (
        "input hash" in result["error"]
        if changed_source
        else "budget exceeded" in result["error"]
    )


@pytest.mark.asyncio
async def test_snapshot_records_pin_and_session_provenance(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    now = "2026-10-19T10:00:00+00:00"
    await temp_db.execute(
        "INSERT INTO projects(id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("reconciler-project", "Reconciler Project", now, now),
    )
    await temp_db.execute(
        "INSERT INTO sessions(id, project_id, user_id, started_at, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("session-1", "reconciler-project", "test", now, "completed", now, now),
    )
    await temp_db.execute(
        "INSERT INTO pins(id, session_id, project_id, user_id, content, importance, status, promoted_to_memory_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "pin-1",
            "session-1",
            "reconciler-project",
            "test",
            "A source pin",
            3,
            "completed",
            "m1",
            now,
            now,
        ),
    )
    service = MemoryReconcilerService(temp_db)

    run = await service.create_run("reconciler-project")
    row = await temp_db.fetchone(
        "SELECT snapshot_json FROM reconciler_inputs WHERE run_id = ? AND memory_id = ?",
        (run["id"], "m1"),
    )

    assert json.loads(row["snapshot_json"])["provenance"] == {
        "pin_ids": ["pin-1"],
        "session_ids": ["session-1"],
    }


@pytest.mark.asyncio
async def test_anchor_stale_status_changes_snapshot_input_hash(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    service = MemoryReconcilerService(temp_db)
    row = await temp_db.fetchone("SELECT * FROM memories WHERE id = ?", ("m1",))
    before = await service._snapshot_memory(row)
    await temp_db.execute(
        "UPDATE memories SET stale_status = ?, stale_checked_at = ? WHERE id = ?",
        ("stale", "2026-10-20T10:00:00+00:00", "m1"),
    )
    changed = await temp_db.fetchone("SELECT * FROM memories WHERE id = ?", ("m1",))

    after = await service._snapshot_memory(changed)

    assert after["metadata"]["stale_status"] == "stale"
    assert before["input_hash"] != after["input_hash"]


@pytest.mark.asyncio
async def test_evidence_budget_counts_metadata_and_signals(temp_db, monkeypatch):
    import app.core.services.memory_reconciler as reconciler_module

    await _add_memory(temp_db, "m1", "Same brief task one.")
    await _add_memory(temp_db, "m2", "Same brief task two.")
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")
    candidate = await temp_db.fetchone(
        "SELECT * FROM reconciler_candidates WHERE run_id = ?", (run["id"],)
    )
    monkeypatch.setattr(reconciler_module, "MAX_EVIDENCE_CHARS", 200)

    with pytest.raises(ReconcilerValidationError, match="character budget"):
        await service._evidence(dict(candidate))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "Q: Investigate the entire session.\n\nA: Full session reply.",
        '{"messages": [{"role": "user", "content": "Private transcript marker"}]}',
        '{"type": "tool_result", "content": "Private tool marker"}',
    ],
)
@pytest.mark.parametrize("retain", [True, False])
@pytest.mark.parametrize("old_snapshot", [True, False])
async def test_full_transcript_and_tool_payload_are_held_before_judgment(
    temp_db, content, retain, old_snapshot
):
    await _add_memory(temp_db, "m1", content)
    await _add_memory(temp_db, "m2", "Distilled project fact.")
    service = MemoryReconcilerService(temp_db)
    await service.set_policy("reconciler-project", {"retain_evidence_content": retain})
    run = await service.create_run("reconciler-project")
    stored = await temp_db.fetchone(
        "SELECT snapshot_json FROM reconciler_inputs WHERE run_id = ? AND memory_id = 'm1'",
        (run["id"],),
    )
    snapshot = json.loads(stored["snapshot_json"])
    assert not snapshot.get("content")
    assert snapshot["content_excluded_reason"]
    if old_snapshot:
        snapshot.pop("content_excluded_reason")
        if retain:
            snapshot["content"] = content
        await temp_db.execute(
            "UPDATE reconciler_inputs SET snapshot_json = ? WHERE run_id = ? AND memory_id = 'm1'",
            (json.dumps(snapshot), run["id"]),
        )
    provider = MergeProvider()
    result = await service.process_next("worker-1", provider)
    assert result["status"] == "needs_review"
    assert "excluded evidence" in result["error"]
    assert provider.calls == 0
    original = await temp_db.fetchone(
        "SELECT content, status FROM memories WHERE id = 'm1'"
    )
    assert original["content"] == content
    assert original["status"] == "canonical"


@pytest.mark.asyncio
async def test_oversized_source_is_held_without_judging_truncated_text(
    temp_db, monkeypatch
):
    import app.core.services.memory_reconciler as reconciler_module

    monkeypatch.setattr(reconciler_module, "MAX_EVIDENCE_CHARS", 2000)
    await _add_memory(temp_db, "m1", "Same supported task. " * 170)
    await _add_memory(temp_db, "m2", "Same supported task. " * 170)
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")
    provider = MergeProvider()

    result = await service.process_next("worker-1", provider)
    snapshot = await temp_db.fetchone(
        "SELECT snapshot_json FROM reconciler_inputs WHERE run_id = ? AND memory_id = ?",
        (run["id"], "m1"),
    )

    assert json.loads(snapshot["snapshot_json"])["content_truncated"] is True
    assert result["status"] == "needs_review"
    assert "source content exceeds evidence limit" in result["error"]
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_evidence_redacts_metadata_and_anchors(temp_db):
    secret = "sk-abcdefghijklmnop"
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    await temp_db.execute(
        "UPDATE memories SET tags = ?, anchors = ? WHERE id = ?",
        (json.dumps([secret]), json.dumps({"file_paths": [secret]}), "m1"),
    )
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")
    candidate = await temp_db.fetchone(
        "SELECT * FROM reconciler_candidates WHERE run_id = ?", (run["id"],)
    )

    evidence = await service._evidence(dict(candidate))

    assert secret not in json.dumps(evidence)
    assert "<REDACTED>" in json.dumps(evidence)


@pytest.mark.asyncio
async def test_same_source_and_day_do_not_group_unrelated_memories(temp_db):
    await _add_memory(temp_db, "m1", "Landing page theme colors and pricing cards.")
    await _add_memory(temp_db, "m2", "Terminal daemon socket routing for remote panes.")
    await temp_db.execute(
        "UPDATE memories SET anchors = ? WHERE id = 'm2'",
        (json.dumps({"file_paths": ["other/project.py"]}),),
    )
    service = MemoryReconcilerService(temp_db)

    run = await service.create_run("reconciler-project")
    candidates = await temp_db.fetchall(
        "SELECT memory_ids_json FROM reconciler_candidates WHERE run_id = ?",
        (run["id"],),
    )

    assert all(len(json.loads(row["memory_ids_json"])) == 1 for row in candidates)


@pytest.mark.asyncio
async def test_typed_relation_forms_candidate_without_text_overlap(temp_db):
    await _add_memory(
        temp_db, "m1", "Vector compression design for the local cache.", source="import"
    )
    await _add_memory(
        temp_db,
        "m2",
        "Keyboard focus ring requirements in the settings panel.",
        source="import",
    )
    await temp_db.execute(
        "UPDATE memories SET anchors = ? WHERE id = ?",
        (json.dumps({"file_paths": ["ui/settings.py"]}), "m2"),
    )
    await temp_db.execute(
        "INSERT INTO memory_relations(id, source_id, target_id, relation_type, strength, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "relation-1",
            "m1",
            "m2",
            "related",
            1.0,
            "2026-10-19T10:00:00+00:00",
            "2026-10-19T10:00:00+00:00",
        ),
    )
    service = MemoryReconcilerService(temp_db)

    run = await service.create_run("reconciler-project")

    assert run["candidate_counts"] == {"pending_judgment": 1}
    candidate = await temp_db.fetchone(
        "SELECT signal_json FROM reconciler_candidates WHERE run_id = ?",
        (run["id"],),
    )
    assert any(
        signal["kind"] == "graph_relation"
        for signal in json.loads(candidate["signal_json"])
    )


@pytest.mark.asyncio
async def test_existing_embeddings_detect_paraphrase_group(temp_db):
    await _add_memory(
        temp_db,
        "m1",
        "Landing page theme registry architecture.",
        source="import-a",
        created_at="2026-10-01T10:00:00+00:00",
    )
    await _add_memory(
        temp_db,
        "m2",
        "Visual design variant lookup system.",
        source="import-b",
        created_at="2026-10-19T10:00:00+00:00",
    )
    vector = struct.pack(f"{temp_db.embedding_dim}f", *([0.5] * temp_db.embedding_dim))
    for memory_id in ("m1", "m2"):
        await temp_db.execute(
            "UPDATE memories SET embedding = ? WHERE id = ?", (vector, memory_id)
        )
    await temp_db.execute(
        "UPDATE memories SET anchors = ? WHERE id = 'm2'",
        (json.dumps({"file_paths": ["other/project.py"]}),),
    )
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    await temp_db.set_embedding_metadata("embedding_model", embedding.model_name)
    service = MemoryReconcilerService(temp_db, embedding_service=embedding)

    run = await service.create_run("reconciler-project")
    candidate = await temp_db.fetchone(
        "SELECT memory_ids_json, signal_json FROM reconciler_candidates WHERE run_id = ?",
        (run["id"],),
    )

    assert json.loads(candidate["memory_ids_json"]) == ["m1", "m2"]
    assert any(
        signal["kind"] == "embedding_similarity"
        for signal in json.loads(candidate["signal_json"])
    )


@pytest.mark.asyncio
async def test_malformed_provider_payload_retries_once_and_stays_reviewable(temp_db):
    await _add_memory(temp_db, "m1", "The same decision has a first supported form.")
    await _add_memory(temp_db, "m2", "The same decision has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")
    provider = MergeProvider({"action": "merge", "representative_memory_id": "outside"})

    result = await service.process_next("worker-1", provider)

    assert result["status"] == "failed"
    assert result["processed"] is False
    assert provider.calls == 2
    candidate_row = await temp_db.fetchone(
        "SELECT status FROM reconciler_candidates WHERE id = ?",
        (result["candidate_id"],),
    )
    assert candidate_row["status"] == "failed"
    final = await service.get_run(run["id"])
    assert final["status"] == "failed"
    assert final["stats"]["judge_failed_calls"] == 2
    metrics = await service.get_metrics("reconciler-project")
    assert metrics["judge_failed_call_count"] == 2
    assert metrics["judge_call_failure_rate"] == 1.0
    assert final["candidate_issues"] == [
        {
            "candidate_id": result["candidate_id"],
            "status": "failed",
            "reason": "representative is outside candidate group",
        }
    ]


@pytest.mark.asyncio
async def test_provider_timeout_counts_failed_judge_calls(temp_db):
    class TimeoutProvider:
        base_url = "http://127.0.0.1:8000/v1"

        def __init__(self):
            self.calls = 0

        async def reconcile_group(self, evidence):
            self.calls += 1
            raise TimeoutError("judge timed out")

    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")
    provider = TimeoutProvider()

    result = await service.process_next("worker-1", provider)
    metrics = await service.get_metrics("reconciler-project")

    assert result["status"] == "failed"
    assert provider.calls == 2
    assert (await service.get_run(run["id"]))["stats"]["judge_failed_calls"] == 2
    assert metrics["judge_call_failure_rate"] == 1.0


@pytest.mark.asyncio
async def test_invalid_claim_refs_use_targeted_repair_once(temp_db):
    class RepairProvider(MergeProvider):
        def __init__(self):
            super().__init__()
            self.repair_error = None

        async def reconcile_group(self, evidence):
            self.calls += 1
            return {
                "action": "merge",
                "representative_memory_id": evidence[-1]["memory_id"],
                "body": "The supported combined fact.",
                "claims": [{"text": "A supported fact."}],
            }

        async def _repair_reconcile_group(self, evidence, error):
            self.repair_error = error
            return await MergeProvider.reconcile_group(self, evidence)

    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    await service.create_run("reconciler-project")
    provider = RepairProvider()

    result = await service.process_next("worker-1", provider)

    assert result["status"] == "preview"
    assert provider.calls == 2
    assert provider.repair_error == "claim source_refs are required"
    metrics = await service.get_metrics("reconciler-project")
    assert metrics["judge_failed_call_count"] == 1
    assert metrics["judge_call_failure_rate"] == 0.5


@pytest.mark.asyncio
async def test_pairwise_provider_is_not_used_for_group_judgment(temp_db):
    class PairOnlyProvider:
        async def reconcile(self, new_content, old_content):
            raise AssertionError("legacy pairwise prompt was called")

    service = MemoryReconcilerService(temp_db)
    with pytest.raises(ReconcilerValidationError, match="group"):
        await service._call_judge(
            PairOnlyProvider(),
            [{"memory_id": "m1", "content": "First", "input_hash": "h1"}],
        )


@pytest.mark.asyncio
async def test_merge_requires_explicit_representative_body_and_claim_sources(temp_db):
    service = MemoryReconcilerService(temp_db)
    evidence = [{"memory_id": "m1", "content": "Supported fact", "input_hash": "h1"}]
    valid = {
        "action": "merge",
        "representative_memory_id": "m1",
        "body": "Supported fact",
        "claims": [
            {
                "claim_id": "claim-1",
                "text": "Supported fact",
                "source_refs": [{"memory_id": "m1", "input_hash": "h1"}],
            }
        ],
    }

    for missing, message in (
        ("representative_memory_id", "representative"),
        ("body", "body"),
        ("claims", "claims"),
    ):
        payload = dict(valid)
        payload.pop(missing)
        with pytest.raises(ReconcilerValidationError, match=message):
            service._normalize_payload(payload, evidence)

    payload = dict(valid)
    payload["claims"] = [{"claim_id": "claim-1", "text": "Supported fact"}]
    with pytest.raises(ReconcilerValidationError, match="source_refs"):
        service._normalize_payload(payload, evidence)


def test_needs_review_keeps_rationale_without_ungrounded_claims():
    service = MemoryReconcilerService(None)
    evidence = [{"memory_id": "m1", "content": "First", "input_hash": "h1"}]
    payload = {
        "action": "needs_review",
        "rationale": "The source project is uncertain.",
        "claims": [{"text": "Unverified conflict"}],
    }

    normalized = service._normalize_payload(payload, evidence)

    assert normalized["action"] == "needs_review"
    assert normalized["rationale"] == (
        "The source project is uncertain. Uncited claims were omitted."
    )
    assert normalized["claims"] == []


def test_merge_accepts_explicit_source_refs_with_matching_snapshot_hash():
    service = MemoryReconcilerService(None)
    evidence = [{"memory_id": "m1", "content": "Supported fact", "input_hash": "h1"}]
    payload = {
        "action": "merge",
        "representative_memory_id": "m1",
        "body": "Supported fact",
        "claims": [
            {
                "text": "Supported fact",
                "explicit_source_refs": [{"memory_id": "m1", "input_hash": "h1"}],
            }
        ],
    }

    normalized = service._normalize_payload(payload, evidence)

    assert normalized["claims"][0]["source_refs"] == [
        {"memory_id": "m1", "input_hash": "h1"}
    ]
    payload["claims"][0]["explicit_source_refs"][0]["input_hash"] = "wrong"
    with pytest.raises(ReconcilerValidationError, match="stale hash"):
        service._normalize_payload(payload, evidence)


def test_claim_condition_string_remains_one_condition():
    service = MemoryReconcilerService(None)
    evidence = [{"memory_id": "m1", "content": "Supported fact", "input_hash": "h1"}]
    payload = {
        "action": "merge",
        "representative_memory_id": "m1",
        "body": "Supported fact",
        "claims": [
            {
                "text": "Supported fact",
                "conditions": "applies to stable packages only",
                "source_refs": [{"memory_id": "m1", "input_hash": "h1"}],
            }
        ],
    }

    normalized = service._normalize_payload(payload, evidence)

    assert normalized["claims"][0]["conditions"] == ["applies to stable packages only"]


def test_judge_output_redacts_claims_conditions_and_rationale():
    secret = "sk-abcdefghijklmnop"
    service = MemoryReconcilerService(None)
    evidence = [{"memory_id": "m1", "content": "Supported fact", "input_hash": "h1"}]
    payload = {
        "action": "merge",
        "representative_memory_id": "m1",
        "body": f"Supported fact {secret}",
        "rationale": f"Judgment echoed {secret}",
        "risk": f"Echoed {secret}",
        "relations": [
            {
                "source_id": "m1",
                "target_id": "m1",
                "relation_type": "related",
                "note": secret,
            }
        ],
        "claims": [
            {
                "text": f"Supported fact {secret}",
                "conditions": [f"Only when {secret}"],
                "source_refs": [{"memory_id": "m1", "input_hash": "h1"}],
            }
        ],
    }

    normalized = service._normalize_payload(payload, evidence)

    assert secret not in json.dumps(normalized)
    assert normalized["claims"][0]["text"].endswith("<REDACTED>")
    assert normalized["claims"][0]["conditions"][0].endswith("<REDACTED>")
    assert normalized["relations"] == [
        {"source_id": "m1", "target_id": "m1", "relation_type": "related"}
    ]


@pytest.mark.asyncio
async def test_judge_output_redaction_persists_in_ledger_and_curated_result(temp_db):
    secret = "sk-abcdefghijklmnop"
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    provider = MergeProvider(
        {
            "action": "merge",
            "representative_memory_id": "m1",
            "body": f"Consolidated task {secret}",
            "rationale": f"Two sources support it {secret}",
            "claims": [
                {
                    "text": f"The task is supported {secret}",
                    "conditions": [f"When {secret}"],
                    "source_refs": [],
                }
            ],
        }
    )
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    evidence = await service.list_candidates(
        (await service.list_runs("reconciler-project", 1))["runs"][0]["id"],
        "reconciler-project",
    )
    candidate_id = evidence["candidates"][0]["id"]
    inputs = await service.get_candidate_detail(candidate_id, "reconciler-project")
    provider.payload["claims"][0]["source_refs"] = [
        {"memory_id": item["memory_id"], "input_hash": item["input_hash"]}
        for item in inputs["inputs"]
    ]

    applied = await service.process_next("worker-1", provider)

    assert applied["status"] == "active"
    proposal = await temp_db.fetchone(
        "SELECT proposal_json, claims_json FROM reconciler_proposals WHERE candidate_id = ?",
        (candidate_id,),
    )
    result = await temp_db.fetchone(
        "SELECT body FROM curated_results WHERE id = ?", (applied["result_id"],)
    )
    claims = await temp_db.fetchall(
        "SELECT text, conditions_json FROM curated_claims WHERE result_id = ?",
        (applied["result_id"],),
    )
    stored = json.dumps(
        {
            "proposal": dict(proposal),
            "result": dict(result),
            "claims": [dict(claim) for claim in claims],
        }
    )
    assert secret not in stored
    assert "<REDACTED>" in stored


def test_add_relation_requires_edge_and_rejects_dependency_cycle():
    service = MemoryReconcilerService(None)
    evidence = [
        {"memory_id": "m1", "content": "First", "input_hash": "h1"},
        {"memory_id": "m2", "content": "Second", "input_hash": "h2"},
    ]
    payload = {"action": "add_relation", "representative_memory_id": "m1"}

    with pytest.raises(ReconcilerValidationError, match="relations are required"):
        service._normalize_payload(payload, evidence)

    payload["relations"] = [
        {"source_id": "m1", "target_id": "m2", "relation_type": "depends_on"},
        {"source_id": "m2", "target_id": "m1", "relation_type": "depends_on"},
    ]
    with pytest.raises(ReconcilerValidationError, match="dependency cycle"):
        service._normalize_payload(payload, evidence)

    payload["relations"] = payload["relations"][:1]
    assert len(service._normalize_payload(payload, evidence)["relations"]) == 1


@pytest.mark.asyncio
async def test_proposal_preserves_explanation_and_all_input_versions(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")

    class ExplanationProvider(MergeProvider):
        async def reconcile_group(self, evidence):
            payload = await super().reconcile_group(evidence)
            payload["claims"][0]["source_refs"] = payload["claims"][0]["source_refs"][
                :1
            ]
            payload.update(
                {
                    "preserved_conditions": ["Stable releases require signatures."],
                    "removed_repetition": ["Repeated checksum instructions."],
                    "uncertainties": ["Nightly signing status is unverified."],
                }
            )
            return payload

    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    result = await service.process_next("worker-1", ExplanationProvider())
    proposal = (await service.list_proposals("reconciler-project"))[0]
    inputs = json.loads(proposal["input_sources_json"])
    assert {item["memory_id"] for item in inputs} == {"m1", "m2"}
    assert all(item["input_hash"] for item in inputs)
    detail = await service.get_result_detail(result["result_id"], "reconciler-project")
    assert detail["preserved_conditions"] == ["Stable releases require signatures."]
    assert detail["removed_repetition"] == ["Repeated checksum instructions."]
    assert detail["uncertainties"] == ["Nightly signing status is unverified."]


@pytest.mark.parametrize(
    "field", ["preserved_conditions", "removed_repetition", "uncertainties"]
)
def test_explanation_fields_reject_non_list_payload(field):
    service = MemoryReconcilerService(None)
    with pytest.raises(ReconcilerValidationError, match=field):
        service._normalize_payload(
            {"action": "needs_review", field: "Not a list"},
            [{"memory_id": "m1", "content": "Fact", "input_hash": "h1"}],
        )


@pytest.mark.asyncio
async def test_dry_run_can_be_followed_by_live_run_and_duplicate_run_completes(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first form.")
    await _add_memory(temp_db, "m2", "The same task has a second form.")
    service = MemoryReconcilerService(temp_db)

    preview = await service.create_run("reconciler-project")
    live = await service.create_run("reconciler-project", dry_run=False)
    duplicate = await service.create_run("reconciler-project", dry_run=False)

    assert preview["candidate_counts"]["pending_judgment"] == 1
    assert live["candidate_counts"]["pending_judgment"] == 1
    assert duplicate["status"] == "completed"
    assert duplicate["candidate_counts"] == {}
    assert duplicate["stats"]["candidate_group_count"] == 1
    assert duplicate["stats"]["deduplicated_candidate_count"] == 1
    metrics = await service.get_metrics("reconciler-project")
    assert metrics["deduplicated_candidate_count"] == 1
    assert metrics["replay_checked_input_count"] == 2
    assert metrics["replay_non_idempotent_input_count"] == 0
    assert metrics["replay_non_idempotency_rate"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["activation", "index_repair"])
async def test_replay_metrics_detect_duplicate_activation_history(temp_db, operation):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    applied = await service.process_next("worker-1", MergeProvider())
    assert applied["status"] == "active"
    before = await service.get_metrics("reconciler-project")
    assert before["replay_non_idempotent_input_count"] == 0
    await temp_db.execute(
        "INSERT INTO reconciler_receipts(id, proposal_id, result_id, operation, revision, actor, created_at) "
        "SELECT 'duplicate-activation', proposal_id, result_id, ?, revision + 10, actor, created_at "
        "FROM reconciler_receipts WHERE result_id = ? AND operation = 'activation'",
        (operation, applied["result_id"]),
    )
    metrics = await service.get_metrics("reconciler-project")
    assert metrics["replay_checked_input_count"] == 1
    expected = int(operation == "activation")
    assert metrics["replay_non_idempotent_input_count"] == expected
    assert metrics["replay_duplicate_activation_count"] == expected
    assert metrics["replay_duplicate_result_count"] == 0
    assert metrics["replay_non_idempotency_rate"] == expected
    assert {item["kind"]: item["count"] for item in metrics["alerts"]}.get(
        "replay_non_idempotency", 0
    ) == expected
    other = await service.get_metrics("another-project")
    assert other["replay_checked_input_count"] == 0
    assert other["replay_non_idempotency_rate"] is None


@pytest.mark.asyncio
async def test_replay_metrics_include_cancelled_duplicate_results(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    applied = await service.process_next("worker-1", MergeProvider())
    await temp_db.execute(
        "INSERT INTO reconciler_proposals(id, candidate_id, run_id, project_id, action, status, input_policy_hash, created_at, updated_at) "
        "SELECT 'duplicate-proposal', candidate_id, run_id, project_id, action, 'applied', input_policy_hash || '-corrupt', created_at, updated_at "
        "FROM reconciler_proposals WHERE result_id = ?",
        (applied["result_id"],),
    )
    await temp_db.execute(
        "INSERT INTO curated_results(id, proposal_id, candidate_id, project_id, body, action, status, input_policy_hash, created_at) "
        "SELECT 'duplicate-result', 'duplicate-proposal', candidate_id, project_id, body, action, 'cancelled', input_policy_hash, created_at "
        "FROM curated_results WHERE id = ?",
        (applied["result_id"],),
    )
    metrics = await service.get_metrics("reconciler-project")
    assert metrics["replay_checked_input_count"] == 1
    assert metrics["replay_non_idempotent_input_count"] == 1
    assert metrics["replay_duplicate_result_count"] == 1
    assert metrics["replay_duplicate_activation_count"] == 0


@pytest.mark.asyncio
async def test_cancel_run_stops_pending_candidates(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project", dry_run=False)

    cancelled = await service.cancel_run(run["id"])
    provider = MergeProvider()
    await service.process_next("worker-1", provider)

    assert cancelled["status"] == "cancelled"
    assert cancelled["candidate_counts"]["cancelled"] == 1
    assert provider.calls == 0
    assert await service.list_proposals("reconciler-project") == []


@pytest.mark.asyncio
async def test_cancel_run_during_judgment_prevents_activation(temp_db):
    class BlockingProvider(MergeProvider):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def reconcile_group(self, evidence):
            self.started.set()
            await self.release.wait()
            return await super().reconcile_group(evidence)

    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    run = await service.create_run("reconciler-project", dry_run=False)
    provider = BlockingProvider()
    task = asyncio.create_task(service.process_next("worker-1", provider))
    await asyncio.wait_for(provider.started.wait(), timeout=2)

    await service.cancel_run(run["id"])
    provider.release.set()
    await asyncio.wait_for(task, timeout=2)

    assert (await service.get_run(run["id"]))["status"] == "cancelled"
    assert await service.list_proposals("reconciler-project") == []
    assert not await temp_db.fetchone(
        "SELECT id FROM curated_results WHERE status = 'active'"
    )


@pytest.mark.asyncio
async def test_cancel_run_endpoint_returns_terminal_progress(temp_db):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.web.dashboard.route_modules.curation import (
        get_reconciler_service,
        router,
    )

    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project", dry_run=False)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_reconciler_service] = lambda: service

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/curation/reconciler/runs/{run['id']}/cancel"
        )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["candidate_counts"]["cancelled"] == 1


@pytest.mark.asyncio
async def test_project_scoped_candidate_audit_reads_snapshot_and_proposal(temp_db):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.web.dashboard.route_modules.curation import get_reconciler_service, router

    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")
    await service.process_next("worker-1", MergeProvider())
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_reconciler_service] = lambda: service

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        listed = await client.get(
            f"/api/curation/reconciler/runs/{run['id']}/candidates",
            params={"project_id": "reconciler-project"},
        )
        assert listed.status_code == 200
        candidate_id = listed.json()["candidates"][0]["id"]
        detail = await client.get(
            f"/api/curation/reconciler/candidates/{candidate_id}",
            params={"project_id": "reconciler-project"},
        )
        wrong_scope = await client.get(
            f"/api/curation/reconciler/candidates/{candidate_id}",
            params={"project_id": "another-project"},
        )

    assert listed.json()["total"] == 1
    assert listed.json()["candidates"][0]["memory_ids"] == ["m1", "m2"]
    assert len(detail.json()["inputs"]) == 2
    assert all(item["input_hash"] for item in detail.json()["inputs"])
    assert detail.json()["proposals"][0]["status"] == "preview"
    assert detail.json()["receipts"] == []
    assert wrong_scope.status_code == 404


@pytest.mark.asyncio
async def test_project_metrics_count_runs_judgments_and_actions(temp_db):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.web.dashboard.route_modules.curation import get_reconciler_service, router

    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    await service.create_run("reconciler-project")
    await service.process_next("worker-1", MergeProvider())
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_reconciler_service] = lambda: service

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/curation/reconciler/metrics",
            params={"project_id": "reconciler-project"},
        )

    assert response.status_code == 200
    metrics = response.json()
    assert metrics["run_count"] == 1
    assert metrics["runs_by_status"] == {"completed": 1}
    assert metrics["terminal_outcome_run_count"] == 1
    assert metrics["run_outcome_rates"] == {
        "completed": 1.0,
        "partial_success": 0.0,
        "failed": 0.0,
    }
    assert metrics["candidate_count"] == 1
    assert metrics["llm_calls"] == 1
    assert metrics["reported_usage_coverage"] == 0.0
    assert metrics["unreported_usage_calls"] == 1
    assert metrics["proposal_actions"] == {"merge": 1}
    assert metrics["active_result_count"] == 0
    assert metrics["cancellation_count"] == 0
    assert metrics["alerts"] == []
    assert metrics["duration_seconds"]["average"] >= 0


@pytest.mark.asyncio
async def test_recent_runs_api_is_project_scoped(temp_db):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.web.dashboard.route_modules.curation import get_reconciler_service, router

    service = MemoryReconcilerService(temp_db)
    first = await service.create_run("reconciler-project")
    second = await service.create_run("another-project")
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_reconciler_service] = lambda: service

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/curation/reconciler/runs",
            params={"project_id": "reconciler-project", "limit": 1},
        )

    assert response.status_code == 200
    assert response.json()["project_id"] == "reconciler-project"
    assert [run["id"] for run in response.json()["runs"]] == [first["id"]]
    assert second["id"] not in str(response.json())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cancel_first,increase_default", [(True, False), (False, True), (True, True)]
)
async def test_activation_budget_is_cumulative_and_frozen_for_the_run(
    temp_db, monkeypatch, cancel_first, increase_default
):
    import app.core.services.memory_reconciler as reconciler_module

    monkeypatch.setattr(reconciler_module, "MAX_ACTIVATIONS_PER_RUN", 1)
    for memory_id, timestamp in [
        ("old-1", "2023-01-01T00:00:00Z"),
        ("old-2", "2023-01-02T00:00:00Z"),
        ("new-1", "2026-01-01T00:00:00Z"),
        ("new-2", "2026-01-02T00:00:00Z"),
    ]:
        await _add_memory(
            temp_db,
            memory_id,
            "The same task has supported facts.",
            created_at=timestamp,
        )
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    run = await service.create_run("reconciler-project", dry_run=False)
    assert run["budget"]["max_activations"] == 1
    first = await service.process_next("worker-1", MergeProvider())
    assert first["status"] == "active"
    if cancel_first:
        await service.cancel_result(first["result_id"], 1)
    if increase_default:
        monkeypatch.setattr(reconciler_module, "MAX_ACTIVATIONS_PER_RUN", 10)
    second = await service.process_next("worker-2", MergeProvider())
    assert second["status"] == "needs_review"
    assert "activation budget exceeded" in second["error"]
    assert (await service.get_metrics("reconciler-project"))["activation_count"] == 1
    assert (await service.get_run(run["id"]))["budget"]["max_activations"] == 1
    assert (await service.get_run(run["id"]))["status"] == "partial_success"


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [None, True, False, -1, 1.5, 0])
async def test_activation_requires_a_valid_recorded_budget(temp_db, limit):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    run = await service.create_run("reconciler-project", dry_run=False)
    budget = run["budget"]
    if limit is None:
        budget.pop("max_activations")
    else:
        budget["max_activations"] = limit
    await temp_db.execute(
        "UPDATE reconciler_runs SET budget_json = ? WHERE id = ?",
        (json.dumps(budget), run["id"]),
    )
    result = await service.process_next("worker-1", MergeProvider())
    assert result["status"] == "needs_review"
    assert (
        "activation budget exceeded"
        if type(limit) is int and limit == 0
        else "invalid run activation budget"
    ) in result["error"]
    assert await temp_db.fetchone("SELECT id FROM curated_results") is None
    assert (await service.get_metrics("reconciler-project"))["activation_count"] == 0


@pytest.mark.asyncio
async def test_parallel_workers_share_the_recorded_activation_budget(
    temp_db, monkeypatch
):
    import app.core.services.memory_reconciler as reconciler_module

    monkeypatch.setattr(reconciler_module, "MAX_ACTIVATIONS_PER_RUN", 1)
    await _add_memory(
        temp_db, "m1", "A supported project fact.", created_at="2023-01-01T00:00:00Z"
    )
    await _add_memory(
        temp_db, "m2", "A supported project fact.", created_at="2026-01-01T00:00:00Z"
    )
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)

    class YieldingProvider(MergeProvider):
        async def reconcile_group(self, evidence):
            await asyncio.sleep(0)
            return await super().reconcile_group(evidence)

    provider = YieldingProvider()
    results = await asyncio.gather(
        service.process_next("worker-1", provider),
        service.process_next("worker-2", provider),
    )
    assert sorted(result["status"] for result in results) == ["active", "needs_review"]
    assert (await service.get_metrics("reconciler-project"))["activation_count"] == 1


@pytest.mark.asyncio
async def test_failed_index_does_not_spend_activation_budget(temp_db, monkeypatch):
    import app.core.services.memory_reconciler as reconciler_module

    monkeypatch.setattr(reconciler_module, "MAX_ACTIVATIONS_PER_RUN", 1)
    for memory_id, timestamp in [
        ("m1", "2023-01-01T00:00:00Z"),
        ("m2", "2026-01-01T00:00:00Z"),
    ]:
        await _add_memory(
            temp_db, memory_id, "A supported project fact.", created_at=timestamp
        )

    class FailOnceEmbedding(_FakeEmbedding):
        async def aembed(self, text):
            if not self.calls:
                self.calls.append(text)
                raise RuntimeError("index unavailable")
            return await super().aembed(text)

    service = MemoryReconcilerService(
        temp_db, embedding_service=FailOnceEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    first = await service.process_next("worker-1", MergeProvider())
    assert first["processed"] is False
    second = await service.process_next("worker-2", MergeProvider())
    assert second["status"] == "active"
    assert (await service.get_metrics("reconciler-project"))["activation_count"] == 1


@pytest.mark.asyncio
async def test_run_llm_call_budget_holds_extra_candidate(temp_db, monkeypatch):
    import app.core.services.memory_reconciler as reconciler_module

    monkeypatch.setattr(reconciler_module, "MAX_LLM_CALLS_PER_RUN", 1)
    for memory_id, content in (
        ("m1", "Alpha pricing card supported form one."),
        ("m2", "Alpha pricing card supported form two."),
        ("m3", "Terminal socket routing supported form one."),
        ("m4", "Terminal socket routing supported form two."),
    ):
        await _add_memory(temp_db, memory_id, content, source="import")
    for memory_id in ("m3", "m4"):
        await temp_db.execute(
            "UPDATE memories SET anchors = ? WHERE id = ?",
            (json.dumps({"file_paths": ["terminal/socket.py"]}), memory_id),
        )
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")
    assert run["candidate_counts"]["pending_judgment"] == 2
    provider = MergeProvider()

    await service.process_next("worker-1", provider)
    second = await service.process_next("worker-1", provider)
    final = await service.get_run(run["id"])

    assert provider.calls == 1
    assert second["status"] == "needs_review"
    assert final["stats"]["llm_calls"] == 1
    assert final["status"] == "partial_success"
    metrics = await service.get_metrics("reconciler-project")
    assert metrics["run_outcome_rates"] == {
        "completed": 0.0,
        "partial_success": 1.0,
        "failed": 0.0,
    }
    assert metrics["budget_exceeded_candidate_count"] == 1
    assert metrics["alerts"] == [{"kind": "budget_exceeded", "count": 1}]

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.web.dashboard.route_modules.curation import get_reconciler_service, router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_reconciler_service] = lambda: service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/curation/reconciler/metrics",
            params={"project_id": "reconciler-project"},
        )
    assert response.status_code == 200
    assert response.json()["alerts"] == metrics["alerts"]


@pytest.mark.asyncio
async def test_run_metrics_keep_provider_usage_separate_from_estimates(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")

    class MeteredProvider(MergeProvider):
        last_usage = None

        async def reconcile_group(self, evidence):
            self.last_usage = {
                "input_tokens": 40,
                "output_tokens": 12,
                "cache_creation_input_tokens": 5,
                "cache_read_input_tokens": 7,
            }
            return await super().reconcile_group(evidence)

    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")
    await service.process_next("worker-1", MeteredProvider())
    stored = await service.get_run(run["id"])
    metrics = await service.get_metrics("reconciler-project")

    assert stored["stats"]["estimated_input_tokens"] > 0
    assert stored["stats"]["reported_usage_calls"] == 1
    assert metrics["reported_usage_coverage"] == 1.0
    assert metrics["unreported_usage_calls"] == 0
    assert metrics["reported_input_tokens"] == 40
    assert metrics["reported_output_tokens"] == 12
    assert metrics["reported_cache_creation_input_tokens"] == 5
    assert metrics["reported_cache_read_input_tokens"] == 7


@pytest.mark.asyncio
async def test_metrics_report_failed_curated_index_as_validation_alert(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    await service.create_run("reconciler-project", dry_run=False)

    result = await service.process_next("worker-1", MergeProvider())
    metrics = await service.get_metrics("reconciler-project")

    assert result["processed"] is False
    assert metrics["validation_failure_count"] == 1
    assert metrics["index_validation_failure_count"] == 1
    assert metrics["failed_candidate_count"] == 1
    assert metrics["judge_failed_call_count"] == 0
    assert metrics["alerts"] == [
        {"kind": "validation_failure", "count": 1},
        {"kind": "candidate_failure", "count": 1},
        {"kind": "index_validation_failure", "count": 1},
    ]
    await temp_db.execute(
        "UPDATE reconciler_validations SET details_json = ? WHERE status = 'failed'",
        (json.dumps({"error": "source hash changed"}),),
    )
    unrelated = await service.get_metrics("reconciler-project")
    assert unrelated["validation_failure_count"] == 1
    assert unrelated["index_validation_failure_count"] == 0


@pytest.mark.asyncio
async def test_metrics_identify_embedding_dimension_mismatch(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim + 1)
    )
    await service.create_run("reconciler-project", dry_run=False)

    result = await service.process_next("worker-1", MergeProvider())
    metrics = await service.get_metrics("reconciler-project")

    assert result["processed"] is False
    assert metrics["validation_failure_count"] == 1
    assert metrics["index_validation_failure_count"] == 1
    assert metrics["judge_failed_call_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    [
        "fts_missing",
        "fts_body",
        "fallback_missing",
        "active_missing",
        "vector_data",
        "model",
    ],
)
async def test_explicit_validation_rejects_inconsistent_derived_indexes(
    temp_db, corruption
):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    result = await service.process_next("worker-1", MergeProvider())
    result_id = result["result_id"]
    assert (await service.validate_result(result_id))["valid"] is True
    if corruption == "fts_missing":
        await temp_db.execute(
            "DELETE FROM curated_results_fts WHERE result_id = ?", (result_id,)
        )
    elif corruption == "fts_body":
        await temp_db.execute(
            "UPDATE curated_results_fts SET body = 'Unrelated content' WHERE result_id = ?",
            (result_id,),
        )
    elif corruption == "fallback_missing":
        await temp_db.execute(
            "DELETE FROM curated_results_vec_fallback WHERE result_id = ?", (result_id,)
        )
    elif corruption == "active_missing":
        await temp_db.execute(
            "DELETE FROM curated_results_vec_active WHERE result_id = ?", (result_id,)
        )
    elif corruption == "vector_data":
        await temp_db.execute(
            "UPDATE curated_results_vec_fallback SET embedding = ? WHERE result_id = ?",
            (struct.pack("f", float("nan")) * temp_db.embedding_dim, result_id),
        )
    else:
        await temp_db.set_embedding_metadata(
            "reconciler_embedding_model", "different-model"
        )

    validation = await service.validate_result(result_id)

    assert validation["valid"] is False
    assert validation["status"] == "stale"
    assert validation["errors"]
    assert (await service.get_metrics("reconciler-project"))[
        "index_validation_failure_count"
    ] == 1
    restored = await service.effective_read.search(
        "supported", {"project_id": "reconciler-project"}, limit=5
    )
    assert {item.id for item in restored.results} == {"m1", "m2"}


@pytest.mark.asyncio
async def test_validation_preserves_cancelled_result_status(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    result = await service.process_next("worker-1", MergeProvider())
    await service.cancel_result(result["result_id"], 1)
    validation = await service.validate_result(result["result_id"])
    assert validation["valid"] is False
    assert validation["status"] == "cancelled"


@pytest.mark.asyncio
async def test_metrics_detect_missing_claim_source_evidence(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    result = await service.process_next("worker-1", MergeProvider())
    assert result["status"] == "active"
    before = await service.get_metrics("reconciler-project")
    assert before["provenance_coverage"] == 1.0

    await temp_db.execute(
        "DELETE FROM curated_claim_sources WHERE result_id = ?",
        (result["result_id"],),
    )
    after = await service.get_metrics("reconciler-project")

    assert after["active_claim_count"] == 1
    assert after["covered_claim_count"] == 0
    assert after["provenance_coverage"] == 0.0
    assert {item["kind"]: item["count"] for item in after["alerts"]} == {
        "provenance_gap": 1
    }


@pytest.mark.asyncio
async def test_run_time_budget_prevents_judgment(temp_db, monkeypatch):
    import app.core.services.memory_reconciler as reconciler_module

    monkeypatch.setattr(reconciler_module, "MAX_RUN_SECONDS", 0)
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    await service.create_run("reconciler-project")
    provider = MergeProvider()

    result = await service.process_next("worker-1", provider)

    assert result["status"] == "needs_review"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_worker_holds_run_created_for_another_prompt_version(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    await MemoryReconcilerService(temp_db, prompt_version="reconciler-old").create_run(
        "reconciler-project"
    )
    provider = MergeProvider()

    result = await MemoryReconcilerService(temp_db).process_next("worker-1", provider)

    assert result["status"] == "needs_review"
    assert "prompt changed" in result["error"]
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_worker_holds_candidates_from_another_detector_version(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")
    await temp_db.execute(
        "UPDATE reconciler_runs SET detector_version = 'candidate-old' WHERE id = ?",
        (run["id"],),
    )
    provider = MergeProvider()
    result = await service.process_next("worker-1", provider)
    assert result["status"] == "needs_review"
    assert "detector changed" in result["error"]
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_dashboard_run_records_configured_judge_model(temp_db):
    from app.web.dashboard.route_modules.curation import get_reconciler_service

    await temp_db.set_app_config("chat.llm_model", "judge-test-model")
    await temp_db.set_app_config("chat.llm_provider", "openai")
    await temp_db.set_app_config("chat.llm_base_url", "http://127.0.0.1:9000/v1")
    await temp_db.set_app_config("chat.llm_api_key", "test-key")
    service = await get_reconciler_service(
        temp_db, _FakeEmbedding(temp_db.embedding_dim)
    )

    run = await service.create_run("reconciler-project")

    assert run["model"] == "judge-test-model"
    assert run["stats"]["llm_configuration"] == {
        "provider": "openai",
        "model": "judge-test-model",
        "endpoint_scope": "local",
        "data_classification": "project_memory_evidence",
    }
    assert "test-key" not in json.dumps(run)
    assert "127.0.0.1" not in json.dumps(run)


@pytest.mark.asyncio
async def test_run_records_actual_judge_data_fields_without_evidence_values(temp_db):
    await _add_memory(temp_db, "m1", "Private fixture marker one.")
    await _add_memory(temp_db, "m2", "Private fixture marker two.")
    service = MemoryReconcilerService(temp_db, provider="openai", model="test-model")
    await service.set_policy("reconciler-project", {"retain_evidence_content": False})
    run = await service.create_run("reconciler-project")
    provider = MergeProvider()
    provider.provider_name = "openai"
    provider.model = "test-model"
    result = await service.process_next("worker-1", provider)
    assert result["status"] == "preview"
    stats = (await service.get_run(run["id"]))["stats"]
    context = stats["judge_contexts"][0]
    assert context["provider"] == "openai"
    assert context["model"] == "test-model"
    assert context["endpoint_scope"] == "local"
    assert context["data_classification"] == "project_memory_evidence"
    assert "content" in context["evidence_fields"]
    assert "tags" not in context["metadata_fields"]
    assert "Private fixture marker" not in json.dumps(stats)


@pytest.mark.asyncio
async def test_candidate_identity_includes_provider_configuration(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    first = await MemoryReconcilerService(
        temp_db, provider="openai", model="shared-name"
    ).create_run("reconciler-project")
    second_service = MemoryReconcilerService(
        temp_db, provider="anthropic", model="shared-name"
    )
    second = await second_service.create_run("reconciler-project")
    first_candidates = await second_service.list_candidates(
        first["id"], "reconciler-project"
    )
    second_candidates = await second_service.list_candidates(
        second["id"], "reconciler-project"
    )
    assert first_candidates["total"] == second_candidates["total"] == 1
    assert (
        first_candidates["candidates"][0]["id"]
        != second_candidates["candidates"][0]["id"]
    )


@pytest.mark.asyncio
async def test_run_blocks_another_provider_before_any_call(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(temp_db, provider="openai")
    run = await service.create_run("reconciler-project")
    provider = MergeProvider()
    provider.provider_name = "anthropic"
    result = await service.process_next("worker-1", provider)
    assert result["status"] == "needs_review"
    assert "provider changed" in result["error"]
    assert provider.calls == 0
    stats = (await service.get_run(run["id"]))["stats"]
    assert stats.get("llm_calls", 0) == 0
    assert stats.get("judge_contexts", []) == []


@pytest.mark.asyncio
async def test_activation_exposes_curated_body_and_keeps_raw_view(temp_db):
    await _add_memory(temp_db, "m1", "The same decision has a first supported form.")
    await _add_memory(temp_db, "m2", "The same decision has a second supported form.")
    before = [
        dict(row)
        for row in await temp_db.fetchall(
            "SELECT id, content, status, category, source, tags, anchors FROM memories ORDER BY id"
        )
    ]
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    processed = await service.process_next("worker-1", MergeProvider())
    proposal = (await service.list_proposals("reconciler-project"))[0]

    effective = await service.effective_read.search(
        "supported", {"project_id": "reconciler-project"}, limit=5
    )
    from app.core.services.unified_search import UnifiedSearchService

    raw_service = UnifiedSearchService(temp_db, None)
    raw = await raw_service.search(
        "supported",
        project_id="reconciler-project",
        search_mode="exact",
        read_view="raw",
    )

    assert processed["status"] == "active"
    assert proposal["status"] == "applied"
    assert proposal["result_status"] == "active"
    assert proposal["result_revision"] == 1
    after = [
        dict(row)
        for row in await temp_db.fetchall(
            "SELECT id, content, status, category, source, tags, anchors FROM memories ORDER BY id"
        )
    ]
    assert before == after
    assert [item.result_kind for item in effective.results] == ["curated"]
    assert all(item.id.startswith("cr_") for item in effective.results)
    assert {item.id for item in raw.results} == {"m1", "m2"}
    receipt = await temp_db.fetchone(
        "SELECT actor FROM reconciler_receipts WHERE proposal_id = ? AND operation = 'activation'",
        (proposal["id"],),
    )
    assert receipt["actor"] == "auto"
    assert (
        await temp_db.fetchone(
            "SELECT status FROM reconciler_candidates WHERE id = ?",
            (proposal["candidate_id"],),
        )
    )["status"] == "completed"
    final_run = await service.get_run(proposal["run_id"])
    assert final_run["status"] == "completed"
    assert final_run["active_result_count"] == 1
    metrics = await service.get_metrics("reconciler-project")
    assert metrics["canonical_count"] == 2
    assert metrics["stored_active_covered_canonical_count"] == 2
    assert metrics["uncovered_canonical_count"] == 0
    assert metrics["automatic_rollback_count"] == 0
    audit = await service.get_candidate_detail(
        proposal["candidate_id"], "reconciler-project"
    )
    assert audit["results"][0]["status"] == "active"
    assert [row["operation"] for row in audit["receipts"]] == ["activation"]
    assert [row["status"] for row in audit["validations"]] == ["passed"]
    detail = await service.get_result_detail(
        processed["result_id"], "reconciler-project"
    )
    assert detail["status"] == "active"
    assert detail["action"] == "merge"
    assert {source["memory_id"] for source in detail["sources"]} == {"m1", "m2"}
    assert {ref["memory_id"] for ref in detail["claims"][0]["source_refs"]} == {
        "m1",
        "m2",
    }
    assert all(ref["input_hash"] for ref in detail["claims"][0]["source_refs"])
    with pytest.raises(ValueError, match="not found"):
        await service.get_result_detail(processed["result_id"], "other-project")

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.web.dashboard.route_modules.curation import get_reconciler_service, router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_reconciler_service] = lambda: service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/curation/reconciler/results/{processed['result_id']}",
            params={"project_id": "reconciler-project"},
        )
        wrong_project = await client.get(
            f"/api/curation/reconciler/results/{processed['result_id']}",
            params={"project_id": "other-project"},
        )
    assert response.status_code == 200
    assert len(response.json()["claims"]) == 1
    assert wrong_project.status_code == 404


@pytest.mark.asyncio
async def test_related_curated_context_keeps_original_citations(temp_db):
    await _add_memory(
        temp_db, "m1", "A supported project fact.", created_at="2023-01-01T00:00:00Z"
    )
    await _add_memory(
        temp_db, "m2", "A supported project fact.", created_at="2026-01-01T00:00:00Z"
    )
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    first = await service.process_next("worker-1", MergeProvider())
    second = await service.process_next("worker-2", MergeProvider())
    primary = await service.effective_read.resolve_primary(first["result_id"])
    related = await service.effective_read.related(primary)
    assert [item.id for item in related] == [second["result_id"]]
    assert related[0].result_kind == "curated"
    assert related[0].representative_memory_id in {"m1", "m2"}
    assert len(related[0].citations) == 1
    assert related[0].citations[0]["memory_id"] == related[0].representative_memory_id
    assert related[0].model_dump()["citations"] == related[0].citations


@pytest.mark.asyncio
@pytest.mark.parametrize("read_view", ["effective", "raw"])
async def test_context_rejects_a_primary_outside_the_requested_project(
    temp_db, read_view
):
    from app.core.errors import ContextNotFoundError
    from app.core.services.context import ContextService

    await _add_memory(temp_db, "m1", "A supported project fact.")
    with pytest.raises(ContextNotFoundError):
        await ContextService(temp_db, None).get_context(
            "m1", project_id="another-project", read_view=read_view
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("read_view", ["effective", "raw"])
async def test_primary_resolver_applies_project_scope_to_canonical_ids(
    temp_db, read_view
):
    from app.core.services.effective_read import EffectiveReadService

    await _add_memory(temp_db, "m1", "A supported project fact.")
    result = await EffectiveReadService(temp_db).resolve_primary(
        "m1", read_view=read_view, filters={"project_id": "another-project"}
    )
    assert result is None


@pytest.mark.asyncio
async def test_uncovered_primary_context_uses_effective_related_results(temp_db):
    from app.core.services.context import ContextService

    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    applied = await service.process_next("worker-1", MergeProvider())
    await _add_memory(temp_db, "follow-up", "The supported claim has a follow-up.")
    await _add_memory(
        temp_db,
        "outside",
        "The supported claim has another follow-up.",
        project_id="another-project",
    )
    contexts = ContextService(temp_db, None)
    effective = await contexts.get_context(
        "follow-up", project_id="reconciler-project", depth=1
    )
    assert effective.primary_memory.id == "follow-up"
    assert [item.id for item in effective.related_memories] == [applied["result_id"]]
    assert effective.related_memories[0].result_kind == "curated"
    assert len(effective.related_memories[0].citations) == 2
    raw = await contexts.get_context(
        "follow-up", project_id="reconciler-project", depth=1, read_view="raw"
    )
    assert {item.id for item in raw.related_memories} == {"m1", "m2"}


@pytest.mark.asyncio
async def test_curated_context_excludes_sources_and_other_projects(temp_db):
    from app.core.services.context import ContextService

    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    await _add_memory(
        temp_db,
        "other",
        "Another project's unrelated and more recent task record.",
        project_id="other-project",
        created_at="2026-10-20T10:00:00+00:00",
    )
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    applied = await service.process_next("worker-1", MergeProvider())
    await _add_memory(
        temp_db,
        "same-project-unrelated",
        "Another workflow uses the words reconciled body and supported claim for a separate deployment task.",
        created_at="2026-10-20T10:00:00+00:00",
    )
    await temp_db.execute(
        "UPDATE memories SET anchors = ? WHERE id = ?",
        (
            json.dumps({"file_paths": ["app/other.py"]}),
            "same-project-unrelated",
        ),
    )

    context = await ContextService(temp_db, None).get_context(
        applied["result_id"], depth=1, project_id="reconciler-project"
    )

    assert context.primary_memory.result_kind == "curated"
    assert context.related_memories == []


@pytest.mark.asyncio
async def test_empty_effective_search_does_not_cache_deleted_raw_memory(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    service = MemoryReconcilerService(temp_db, embedding_service=embedding)
    await service.create_run("reconciler-project", dry_run=False)
    assert (await service.process_next("worker-1", MergeProvider()))[
        "status"
    ] == "active"
    await _add_memory(temp_db, "m3", "An unrelated interface accessibility note.")
    filters = {"project_id": "reconciler-project"}

    before = await service.effective_read.search("", filters, limit=10)
    await temp_db.execute("DELETE FROM memories WHERE id = ?", ("m3",))
    after = await service.effective_read.search("", filters, limit=10)

    assert "m3" in {item.id for item in before.results}
    assert "m3" not in {item.id for item in after.results}


@pytest.mark.asyncio
async def test_effective_search_cache_tracks_canonical_insert_and_delete(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")

    class QueryAwareEmbedding(_FakeEmbedding):
        async def aembed(self, text):
            if text == "accessibility":
                return [-0.25] * self.dimension
            return await super().aembed(text)

    embedding = QueryAwareEmbedding(temp_db.embedding_dim)
    service = MemoryReconcilerService(temp_db, embedding_service=embedding)
    await service.create_run("reconciler-project", dry_run=False)
    assert (await service.process_next("worker-1", MergeProvider()))[
        "status"
    ] == "active"
    filters = {"project_id": "reconciler-project"}

    before = await service.effective_read.search("accessibility", filters, limit=10)
    await _add_memory(temp_db, "m3", "An interface accessibility note.")
    inserted = await service.effective_read.search("accessibility", filters, limit=10)
    await temp_db.execute("DELETE FROM memories WHERE id = ?", ("m3",))
    deleted = await service.effective_read.search("accessibility", filters, limit=10)

    assert before.results == []
    assert [item.id for item in inserted.results] == ["m3"]
    assert deleted.results == []


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["one", "all"])
async def test_incomplete_curated_source_set_is_invalid_and_restores_raw_reads(
    temp_db, missing
):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    applied = await service.process_next("worker-1", MergeProvider())
    result_id = applied["result_id"]
    if missing == "one":
        await temp_db.execute(
            "DELETE FROM curated_sources WHERE result_id = ? AND memory_id = 'm1'",
            (result_id,),
        )
    else:
        await temp_db.execute(
            "DELETE FROM curated_sources WHERE result_id = ?", (result_id,)
        )

    validation = await service.validate_result(result_id)
    assert validation["valid"] is False
    assert validation["status"] == "stale"
    search = await service.effective_read.search(
        "supported", {"project_id": "reconciler-project"}, limit=5
    )
    assert {item.id for item in search.results} == {"m1", "m2"}


@pytest.mark.asyncio
async def test_raw_search_cache_tracks_canonical_delete(temp_db):
    from app.core.services.unified_search import UnifiedSearchService

    await _add_memory(temp_db, "m1", "An interface accessibility note.")
    service = UnifiedSearchService(
        temp_db,
        None,
        enable_quality_features=False,
        enable_korean_optimization=False,
        enable_noise_filter=False,
        enable_score_normalization=False,
    )
    options = {
        "project_id": "reconciler-project",
        "search_mode": "exact",
        "read_view": "raw",
    }

    before = await service.search("accessibility", **options)
    await temp_db.execute("DELETE FROM memories WHERE id = ?", ("m1",))
    after = await service.search("accessibility", **options)

    assert [item.id for item in before.results] == ["m1"]
    assert after.results == []


@pytest.mark.asyncio
async def test_new_run_excludes_sources_of_active_curated_result(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    assert (await service.process_next("worker-1", MergeProvider()))[
        "status"
    ] == "active"

    changed_prompt = MemoryReconcilerService(
        temp_db,
        embedding_service=_FakeEmbedding(temp_db.embedding_dim),
        prompt_version="reconciler-next",
    )
    second = await changed_prompt.create_run("reconciler-project", dry_run=False)

    assert second["status"] == "completed"
    assert second["candidate_counts"] == {}


@pytest.mark.asyncio
async def test_queued_candidate_skips_sources_activated_by_earlier_run(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    first_service = MemoryReconcilerService(temp_db, embedding_service=embedding)
    second_service = MemoryReconcilerService(
        temp_db, embedding_service=embedding, prompt_version="reconciler-next"
    )
    await first_service.create_run("reconciler-project", dry_run=False)
    second = await second_service.create_run("reconciler-project", dry_run=False)
    provider = MergeProvider()

    assert (await first_service.process_next("worker-1", provider))[
        "status"
    ] == "active"
    skipped = await second_service.process_next("worker-1", provider)

    assert skipped["status"] == "no_op"
    assert provider.calls == 1
    assert (await second_service.get_run(second["id"]))["status"] == "completed"


@pytest.mark.asyncio
async def test_auto_activation_conflict_does_not_crash_worker(temp_db, monkeypatch):
    from unittest.mock import AsyncMock

    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    run = await service.create_run("reconciler-project", dry_run=False)
    monkeypatch.setattr(
        service,
        "_activate_proposal",
        AsyncMock(side_effect=ReconcilerConflictError("source overlap")),
    )

    result = await service.process_next("worker-1", MergeProvider())

    assert result["status"] == "needs_review"
    assert "source overlap" in result["error"]
    assert (await service.get_run(run["id"]))["candidate_counts"]["needs_review"] == 1


@pytest.mark.asyncio
async def test_concurrent_approval_cannot_activate_overlapping_sources(temp_db):
    await _add_memory(
        temp_db,
        "m1",
        "The same decision has a first supported form.",
        source="hook",
    )
    await _add_memory(
        temp_db,
        "m2",
        "The same decision has a second supported form.",
        source="hook",
    )
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    first_service = MemoryReconcilerService(temp_db, embedding_service=embedding)
    second_service = MemoryReconcilerService(
        temp_db, embedding_service=embedding, prompt_version="reconciler-next"
    )
    await first_service.create_run("reconciler-project", dry_run=False)
    await second_service.create_run("reconciler-project", dry_run=False)
    provider = MergeProvider({"action": "noise_suppression"})
    await first_service.process_next("worker-1", provider)
    await second_service.process_next("worker-1", provider)
    proposals = await first_service.list_proposals("reconciler-project")
    assert len(proposals) == 2
    assert all(item["status"] == "needs_approval" for item in proposals)

    original_fetchone = temp_db.fetchone
    overlap_reads = 0
    both_read = asyncio.Event()

    async def synchronized_fetchone(query, params=()):
        nonlocal overlap_reads
        if query.startswith(
            "SELECT cr.id FROM curated_results cr JOIN curated_sources"
        ):
            result = await original_fetchone(query, params)
            overlap_reads += 1
            if overlap_reads == 2:
                both_read.set()
            if overlap_reads <= 2:
                await both_read.wait()
            return result
        return await original_fetchone(query, params)

    temp_db.fetchone = synchronized_fetchone
    decisions = await asyncio.gather(
        *(
            first_service.decide_proposal(item["id"], "approve", 0)
            for item in proposals
        ),
        return_exceptions=True,
    )

    assert (
        sum(
            isinstance(item, dict) and item.get("status") == "active"
            for item in decisions
        )
        == 1
    )
    assert sum(isinstance(item, ReconcilerConflictError) for item in decisions) == 1
    active = await temp_db.fetchone(
        "SELECT COUNT(*) AS count FROM curated_results WHERE status = 'active'"
    )
    assert active["count"] == 1


@pytest.mark.asyncio
async def test_relation_only_result_keeps_raw_search_and_overview_uncovered(temp_db):
    from app.core.services.overview import OverviewService

    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.set_policy("reconciler-project", {"auto_derived_relations": True})
    await service.create_run("reconciler-project", dry_run=False)
    provider = MergeProvider(
        {
            "action": "add_relation",
            "representative_memory_id": "m2",
            "relations": [
                {
                    "source_id": "m1",
                    "target_id": "m2",
                    "relation_type": "related",
                }
            ],
        }
    )

    result = await service.process_next("worker-1", provider)
    excluded = await service.effective_read.raw_exclusion(
        {"project_id": "reconciler-project"}
    )
    curated = await service.effective_read.search_curated(
        "same task", filters={"project_id": "reconciler-project"}
    )
    overview_items, _, coverage = await OverviewService(
        temp_db
    )._gather_reconciler_items("reconciler-project")

    assert result["status"] == "active"
    assert excluded == set()
    assert curated == []
    assert overview_items == []
    assert coverage["coverage"]["covered_canonical"] == 0
    assert (await service.get_metrics("reconciler-project"))[
        "orphan_relation_count"
    ] == 0

    await temp_db.execute(
        "UPDATE curated_relations SET target_id = ? WHERE result_id = ?",
        ("missing-memory", result["result_id"]),
    )
    metrics = await service.get_metrics("reconciler-project")
    assert metrics["orphan_relation_count"] == 1
    assert {item["kind"]: item["count"] for item in metrics["alerts"]} == {
        "orphan_relation": 1
    }


@pytest.mark.asyncio
async def test_relation_only_result_does_not_block_later_merge(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    first_service = MemoryReconcilerService(temp_db, embedding_service=embedding)
    await first_service.set_policy(
        "reconciler-project", {"auto_derived_relations": True}
    )
    await first_service.create_run("reconciler-project", dry_run=False)
    relation = await first_service.process_next(
        "worker-1",
        MergeProvider(
            {
                "action": "add_relation",
                "representative_memory_id": "m2",
                "relations": [
                    {
                        "source_id": "m1",
                        "target_id": "m2",
                        "relation_type": "related",
                    }
                ],
            }
        ),
    )
    second_service = MemoryReconcilerService(
        temp_db, embedding_service=embedding, prompt_version="reconciler-next"
    )
    second_run = await second_service.create_run("reconciler-project", dry_run=False)

    merged = await second_service.process_next("worker-1", MergeProvider())

    assert relation["status"] == "active"
    assert second_run["candidate_counts"] == {"pending_judgment": 1}
    assert merged["status"] == "active"
    results = await temp_db.fetchall(
        "SELECT action, status FROM curated_results WHERE project_id = ? ORDER BY action",
        ("reconciler-project",),
    )
    assert [(row["action"], row["status"]) for row in results] == [
        ("add_relation", "active"),
        ("merge", "active"),
    ]


@pytest.mark.asyncio
async def test_second_relation_cannot_cycle_with_active_dependency(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    first_service = MemoryReconcilerService(temp_db, embedding_service=embedding)
    await first_service.set_policy(
        "reconciler-project", {"auto_derived_relations": True}
    )
    await first_service.create_run("reconciler-project", dry_run=False)
    await first_service.process_next(
        "worker-1",
        MergeProvider(
            {
                "action": "add_relation",
                "representative_memory_id": "m1",
                "relations": [
                    {
                        "source_id": "m1",
                        "target_id": "m2",
                        "relation_type": "depends_on",
                    }
                ],
            }
        ),
    )
    second_service = MemoryReconcilerService(
        temp_db, embedding_service=embedding, prompt_version="reconciler-next"
    )
    await second_service.create_run("reconciler-project", dry_run=False)

    await second_service.process_next(
        "worker-1",
        MergeProvider(
            {
                "action": "add_relation",
                "representative_memory_id": "m2",
                "relations": [
                    {
                        "source_id": "m2",
                        "target_id": "m1",
                        "relation_type": "depends_on",
                    }
                ],
            }
        ),
    )

    active = await temp_db.fetchone(
        "SELECT COUNT(*) AS n FROM curated_results WHERE project_id = ? AND status = 'active'",
        ("reconciler-project",),
    )
    assert active["n"] == 1


@pytest.mark.asyncio
async def test_opted_in_noise_suppression_keeps_raw_and_restores_on_cancel(temp_db):
    from app.core.services.unified_search import UnifiedSearchService

    await _add_memory(
        temp_db,
        "m1",
        "Automated queue trace repeats a transient processing event.",
        source="hook",
    )
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    service = MemoryReconcilerService(temp_db, embedding_service=embedding)
    await service.set_policy("reconciler-project", {"auto_noise_suppression": True})
    run = await service.create_run("reconciler-project", dry_run=False)
    provider = MergeProvider(
        {
            "action": "noise_suppression",
            "representative_memory_id": "m1",
            "rationale": "The source is transient automation noise.",
        }
    )

    applied = await service.process_next("worker-1", provider)
    hidden = await service.effective_read.search(
        "queue trace", {"project_id": "reconciler-project"}, limit=5
    )
    raw = await UnifiedSearchService(temp_db, None).search(
        "queue trace",
        project_id="reconciler-project",
        search_mode="exact",
        read_view="raw",
    )
    cancelled = await service.cancel_result(applied["result_id"], 1)
    restored = await service.effective_read.search(
        "queue trace", {"project_id": "reconciler-project"}, limit=5
    )

    assert applied["status"] == "active"
    assert hidden.results == []
    assert [item.id for item in raw.results] == ["m1"]
    assert cancelled["status"] == "cancelled"
    assert (await service.list_proposals("reconciler-project"))[0][
        "result_status"
    ] == "cancelled"
    assert (await service.list_proposals("reconciler-project"))[0][
        "result_revision"
    ] == 2
    assert [item.id for item in restored.results] == ["m1"]
    assert (await service.get_run(run["id"]))["active_result_count"] == 0
    assert (await service.get_metrics("reconciler-project"))["cancellation_count"] == 1
    metrics = await service.get_metrics("reconciler-project")
    assert metrics["cancellation_rate"] == 1.0
    assert metrics["automatic_rollback_rate"] == 1.0
    assert {item["kind"]: item["count"] for item in metrics["alerts"]} == {
        "automatic_rollback": 1
    }
    source = await temp_db.fetchone("SELECT status FROM memories WHERE id = ?", ("m1",))
    assert source["status"] == "canonical"


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent", [False, True])
async def test_result_cancellation_retry_has_one_receipt_and_revision(
    temp_db, monkeypatch, concurrent
):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    applied = await service.process_next("worker-1", MergeProvider())
    result_id = applied["result_id"]
    revision = await service.effective_read.get_read_revision()
    originals = [
        dict(row)
        for row in await temp_db.fetchall("SELECT * FROM memories ORDER BY id")
    ]

    if concurrent:
        original_fetchone = temp_db.fetchone
        both_read = asyncio.Event()
        reads = 0

        async def synchronized_fetchone(query, params=()):
            nonlocal reads
            row = await original_fetchone(query, params)
            if query == "SELECT * FROM curated_results WHERE id = ?" and reads < 2:
                reads += 1
                if reads == 2:
                    both_read.set()
                await both_read.wait()
            return row

        monkeypatch.setattr(temp_db, "fetchone", synchronized_fetchone)
        results = await asyncio.wait_for(
            asyncio.gather(
                service.cancel_result(result_id, 1), service.cancel_result(result_id, 1)
            ),
            timeout=5,
        )
    else:
        results = [await service.cancel_result(result_id, 1)]
        results.append(await service.cancel_result(result_id, 1))

    assert all(
        item["status"] == "cancelled" and item["revision"] == 2 for item in results
    )
    assert (
        await temp_db.fetchone(
            "SELECT COUNT(*) AS n FROM reconciler_receipts WHERE result_id = ? AND operation = 'cancellation'",
            (result_id,),
        )
    )["n"] == 1
    assert await service.effective_read.get_read_revision() == revision + 1
    assert [
        dict(row)
        for row in await temp_db.fetchall("SELECT * FROM memories ORDER BY id")
    ] == originals


@pytest.mark.asyncio
async def test_cancellation_index_failure_rolls_back_result_and_receipt(
    temp_db, monkeypatch
):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    result = await service.process_next("worker-1", MergeProvider())
    revision = await service.effective_read.get_read_revision()
    original_execute = temp_db.execute

    async def fail_vector_delete(query, params=()):
        if query.startswith("DELETE FROM curated_results_vec_active"):
            raise RuntimeError("vector delete failed")
        return await original_execute(query, params)

    monkeypatch.setattr(temp_db, "execute", fail_vector_delete)
    with pytest.raises(RuntimeError, match="vector delete failed"):
        await service.cancel_result(result["result_id"], 1)
    row = await temp_db.fetchone(
        "SELECT status, revision FROM curated_results WHERE id = ?",
        (result["result_id"],),
    )
    assert dict(row) == {"status": "active", "revision": 1}
    assert (
        await temp_db.fetchone(
            "SELECT COUNT(*) AS n FROM reconciler_receipts WHERE operation = 'cancellation'"
        )
    )["n"] == 0
    assert await service.effective_read.get_read_revision() == revision


@pytest.mark.asyncio
async def test_cancelling_stale_result_records_actual_prior_status(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    result = await service.process_next("worker-1", MergeProvider())
    await temp_db.execute(
        "UPDATE memories SET content = 'Changed source' WHERE id = 'm1'"
    )
    assert not await service.effective_read.revalidate_result(result["result_id"])
    cancelled = await service.cancel_result(result["result_id"], 2)
    assert cancelled["revision"] == 3
    receipt = await temp_db.fetchone(
        "SELECT from_status FROM reconciler_receipts WHERE result_id = ? AND operation = 'cancellation'",
        (result["result_id"],),
    )
    assert receipt["from_status"] == "stale"


@pytest.mark.asyncio
async def test_noise_suppression_without_project_opt_in_stays_inactive(temp_db):
    await _add_memory(
        temp_db,
        "m1",
        "Automated queue trace repeats a transient processing event.",
        source="hook",
    )
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)

    result = await service.process_next(
        "worker-1",
        MergeProvider(
            {
                "action": "noise_suppression",
                "representative_memory_id": "m1",
            }
        ),
    )

    assert result["status"] == "needs_approval"
    assert (
        await service.effective_read.raw_exclusion({"project_id": "reconciler-project"})
        == set()
    )


@pytest.mark.asyncio
async def test_live_supersede_activates_without_automatic_source(temp_db):
    await _add_memory(
        temp_db,
        "m1",
        "The same task has an older supported form.",
        source="import",
    )
    await _add_memory(
        temp_db,
        "m2",
        "The same task has a newer supported form.",
        source="import",
    )
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    before = [
        dict(row)
        for row in await temp_db.fetchall(
            "SELECT id, content, status, category, source, tags, anchors FROM memories ORDER BY id"
        )
    ]
    await service.create_run("reconciler-project", dry_run=False)
    result = await service.process_next(
        "worker-1",
        MergeProvider(
            {
                "action": "supersede",
                "representative_memory_id": "m2",
                "body": "The newer supported form.",
            }
        ),
    )

    proposal = (await service.list_proposals("reconciler-project"))[0]
    assert result["status"] == "active"
    assert proposal["action"] == "supersede"
    assert proposal["status"] == "applied"
    after = [
        dict(row)
        for row in await temp_db.fetchall(
            "SELECT id, content, status, category, source, tags, anchors FROM memories ORDER BY id"
        )
    ]
    assert before == after
    receipt = await temp_db.fetchone(
        "SELECT actor FROM reconciler_receipts WHERE proposal_id = ? AND operation = 'activation'",
        (proposal["id"],),
    )
    assert receipt["actor"] == "auto"


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["decision", "incident"])
@pytest.mark.parametrize("action", ["merge", "supersede"])
async def test_decision_and_incident_live_results_activate_without_approval(
    temp_db, category, action
):
    await _add_memory(
        temp_db,
        "m1",
        "The same categorized memory has a first supported form.",
        category=category,
    )
    await _add_memory(
        temp_db,
        "m2",
        "The same categorized memory has a second supported form.",
        category=category,
    )
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    provider = MergeProvider()
    if action == "supersede":
        provider = MergeProvider(
            {
                "action": action,
                "representative_memory_id": "m2",
                "body": "The categorized supported form.",
            }
        )
    result = await service.process_next("worker-1", provider)
    proposal = (await service.list_proposals("reconciler-project"))[0]

    assert result["status"] == "active"
    assert proposal["status"] == "applied"
    assert dict(
        await temp_db.fetchone(
            "SELECT COUNT(*) AS count FROM curated_results WHERE status = 'active'"
        )
    ) == {"count": 1}
    assert (
        await temp_db.fetchone(
            "SELECT actor FROM reconciler_receipts WHERE proposal_id = ? AND operation = 'activation'",
            (proposal["id"],),
        )
    )["actor"] == "auto"
    originals = await temp_db.fetchall(
        "SELECT id, status, content FROM memories WHERE id IN ('m1', 'm2') ORDER BY id"
    )
    assert [(row["id"], row["status"]) for row in originals] == [
        ("m1", "canonical"),
        ("m2", "canonical"),
    ]
    assert all("same categorized memory" in row["content"] for row in originals)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ["contradiction", "insufficient_evidence", "scope_mismatch", None]
)
async def test_review_reason_is_recorded_and_only_explicit_contradictions_are_counted(
    temp_db, reason
):
    await _add_memory(temp_db, "m1", "The same task has a first form.")
    await _add_memory(temp_db, "m2", "The same task has a second form.")
    service = MemoryReconcilerService(temp_db)
    await service.create_run("reconciler-project", dry_run=False)
    result = await service.process_next(
        "worker-1",
        MergeProvider(
            {
                "action": "needs_review",
                "review_reason": reason,
                "rationale": "Unresolved contradiction may be only a scope issue.",
            }
        ),
    )
    assert result["status"] == "needs_review"
    proposal = (await service.list_proposals("reconciler-project"))[0]
    assert json.loads(proposal["proposal_json"])["review_reason"] == reason
    metrics = await service.get_metrics("reconciler-project")
    assert metrics["review_reason_counts"] == {reason or "unclassified": 1}
    assert metrics["unresolved_contradiction_count"] == int(reason == "contradiction")
    assert metrics["unclassified_review_count"] == int(reason is None)
    assert await temp_db.fetchone("SELECT id FROM curated_results") is None


@pytest.mark.parametrize("reason", ["invented", [], {"kind": "contradiction"}])
def test_review_reason_rejects_unknown_or_non_string_codes(reason):
    service = MemoryReconcilerService(None)
    with pytest.raises(ReconcilerValidationError, match="review_reason"):
        service._normalize_payload(
            {"action": "needs_review", "review_reason": reason},
            [{"memory_id": "m1", "content": "Fact", "input_hash": "h1"}],
        )


@pytest.mark.asyncio
async def test_needs_review_is_a_hold_without_activation_path(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first form.")
    await _add_memory(temp_db, "m2", "The same task has a second form.")
    service = MemoryReconcilerService(temp_db)
    await service.create_run("reconciler-project", dry_run=False)
    result = await service.process_next(
        "worker-1", MergeProvider({"action": "conflict"})
    )
    proposal = (await service.list_proposals("reconciler-project"))[0]

    assert result["status"] == "needs_review"
    assert proposal["status"] == "needs_review"
    with pytest.raises(ReconcilerValidationError, match="needs_approval"):
        await service.decide_proposal(
            proposal["id"], "approve", proposal["expected_revision"]
        )
    with pytest.raises(ReconcilerValidationError, match="needs_approval"):
        await service.decide_proposal(
            proposal["id"], "reject", proposal["expected_revision"]
        )
    with pytest.raises(ReconcilerValidationError, match="needs_approval"):
        await service._activate_proposal(
            proposal["id"], proposal["expected_revision"], actor="operator"
        )
    assert dict(
        await temp_db.fetchone("SELECT COUNT(*) AS count FROM curated_results")
    ) == {"count": 0}


@pytest.mark.asyncio
async def test_default_dry_run_is_preview_and_approval_is_rejected(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first form.")
    await _add_memory(temp_db, "m2", "The same task has a second form.")
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project")
    result = await service.process_next("worker-1", MergeProvider())
    proposal = (await service.list_proposals("reconciler-project"))[0]

    assert run["dry_run"] == 1
    assert result["status"] == "preview"
    assert proposal["status"] == "preview"
    with pytest.raises(ReconcilerValidationError, match="preview-only"):
        await service.decide_proposal(
            proposal["id"], "approve", proposal["expected_revision"]
        )
    with pytest.raises(ReconcilerValidationError, match="preview-only"):
        await service.decide_proposal(
            proposal["id"], "reject", proposal["expected_revision"]
        )
    with pytest.raises(ReconcilerValidationError, match="needs_approval"):
        await service._activate_proposal(
            proposal["id"], proposal["expected_revision"], actor="operator"
        )
    unchanged = await temp_db.fetchone(
        "SELECT status, result_id FROM reconciler_proposals WHERE id = ?",
        (proposal["id"],),
    )
    assert dict(unchanged) == {"status": "preview", "result_id": None}
    assert dict(
        await temp_db.fetchone("SELECT COUNT(*) AS count FROM reconciler_receipts")
    ) == {"count": 0}


@pytest.mark.asyncio
async def test_old_detector_proposal_blocks_activation_but_allows_rejection(temp_db):
    await _add_memory(temp_db, "m1", "Automated transient trace.", source="hook")
    service = MemoryReconcilerService(temp_db)
    run = await service.create_run("reconciler-project", dry_run=False)
    await service.process_next(
        "worker-1", MergeProvider({"action": "noise_suppression"})
    )
    proposal = (await service.list_proposals("reconciler-project"))[0]
    await temp_db.execute(
        "UPDATE reconciler_runs SET detector_version = 'candidate-old' WHERE id = ?",
        (run["id"],),
    )
    with pytest.raises(
        ReconcilerConflictError, match="detector changed before activation"
    ):
        await service.decide_proposal(
            proposal["id"], "approve", proposal["expected_revision"]
        )
    assert (
        await temp_db.fetchone("SELECT id FROM curated_results WHERE status = 'active'")
        is None
    )
    rejected = await service.decide_proposal(
        proposal["id"], "reject", proposal["expected_revision"]
    )
    assert rejected["status"] == "rejected"


@pytest.mark.asyncio
async def test_manual_policy_rejection_records_actor_and_metrics(temp_db):
    await _add_memory(
        temp_db,
        "m1",
        "Automated queue trace repeats a transient event.",
        source="hook",
    )
    service = MemoryReconcilerService(temp_db)
    await service.create_run("reconciler-project", dry_run=False)
    await service.process_next(
        "worker-1", MergeProvider({"action": "noise_suppression"})
    )
    proposal = (await service.list_proposals("reconciler-project"))[0]
    assert proposal["status"] == "needs_approval"

    rejected = await service.decide_proposal(
        proposal["id"], "reject", proposal["expected_revision"]
    )
    receipt = await temp_db.fetchone(
        "SELECT actor FROM reconciler_receipts WHERE proposal_id = ? AND operation = 'decision'",
        (proposal["id"],),
    )
    metrics = await service.get_metrics("reconciler-project")

    assert rejected["status"] == "rejected"
    assert rejected["decision_actor"] == "operator"
    assert receipt["actor"] == "operator"
    assert metrics["manual_decision_count"] == 1
    assert metrics["manual_rejection_count"] == 1
    assert metrics["manual_rejection_rate"] == 1.0
    assert metrics["approval_wait_seconds"]["average"] is not None
    repeated = await service.decide_proposal(
        proposal["id"], "reject", proposal["expected_revision"]
    )
    assert repeated["status"] == "rejected"
    assert (
        await temp_db.fetchone(
            "SELECT COUNT(*) AS n FROM reconciler_receipts WHERE proposal_id = ? AND operation = 'decision'",
            (proposal["id"],),
        )
    )["n"] == 1
    with pytest.raises(ReconcilerConflictError, match="already decided"):
        await service.decide_proposal(
            proposal["id"], "approve", proposal["expected_revision"]
        )

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.web.dashboard.route_modules.curation import get_reconciler_service, router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_reconciler_service] = lambda: service
    url = f"/api/curation/reconciler/proposals/{proposal['id']}/decision"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        repeat = await client.post(
            url,
            json={
                "decision": "reject",
                "expected_revision": proposal["expected_revision"],
            },
        )
        opposite = await client.post(
            url,
            json={
                "decision": "approve",
                "expected_revision": proposal["expected_revision"],
            },
        )
    assert repeat.status_code == 200
    assert repeat.json()["status"] == "rejected"
    assert opposite.status_code == 409


@pytest.mark.asyncio
async def test_activation_rejects_stale_input_and_cancellation_is_idempotent(temp_db):
    await _add_memory(
        temp_db,
        "m1",
        "The same decision has a first supported form.",
        category="decision",
    )
    await _add_memory(
        temp_db,
        "m2",
        "The same decision has a second supported form.",
        category="decision",
    )
    service = MemoryReconcilerService(temp_db)
    await service.create_run("reconciler-project", dry_run=False)
    await service.process_next(
        "worker-1", MergeProvider({"action": "noise_suppression"})
    )
    proposal = (await service.list_proposals("reconciler-project"))[0]

    await temp_db.execute(
        "UPDATE memories SET content = ?, content_hash = ? WHERE id = ?",
        ("Changed canonical body.", "changed", "m1"),
    )
    with pytest.raises(ReconcilerValidationError):
        await service.decide_proposal(
            proposal["id"], "approve", proposal["expected_revision"]
        )
    stale_result = await temp_db.fetchone(
        "SELECT status FROM curated_results WHERE id = ?",
        ("cr_" + "0" * 32,),
    )
    assert stale_result is None

    await temp_db.execute(
        "UPDATE memories SET content = ?, content_hash = ? WHERE id = ?",
        ("The same decision has a first supported form.", "hash-m1", "m1"),
    )
    await service.create_run("reconciler-project", dry_run=False)
    assert len(await service.list_proposals("reconciler-project")) == 1


@pytest.mark.asyncio
async def test_activation_is_retryable_after_embedding_migration(temp_db):
    await _add_memory(
        temp_db,
        "m1",
        "The same decision has a first supported form.",
        category="decision",
    )
    await _add_memory(
        temp_db,
        "m2",
        "The same decision has a second supported form.",
        category="decision",
    )
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    await service.create_run("reconciler-project", dry_run=False)
    await service.process_next(
        "worker-1", MergeProvider({"action": "noise_suppression"})
    )
    proposal = (await service.list_proposals("reconciler-project"))[0]
    expected_revision = proposal["expected_revision"]
    sentinel = json.dumps([0.75] * temp_db.embedding_dim)
    await temp_db.execute("DELETE FROM curated_results_vec_next")
    await temp_db.execute(
        "INSERT INTO curated_results_vec_next(result_id, embedding) VALUES ('sentinel', ?)",
        (sentinel,),
    )
    sentinel_value = (
        await temp_db.fetchone(
            "SELECT embedding FROM curated_results_vec_next WHERE result_id = 'sentinel'"
        )
    )["embedding"]
    await temp_db.set_migration_in_progress(True)

    with pytest.raises(ReconcilerValidationError, match="migration"):
        await service.decide_proposal(proposal["id"], "approve", expected_revision)

    blocked = await temp_db.fetchone(
        "SELECT status, expected_revision FROM reconciler_proposals WHERE id = ?",
        (proposal["id"],),
    )
    next_row = await temp_db.fetchone(
        "SELECT embedding FROM curated_results_vec_next WHERE result_id = 'sentinel'"
    )
    assert blocked["status"] == "needs_approval"
    assert blocked["expected_revision"] == expected_revision
    assert next_row["embedding"] == sentinel_value

    await temp_db.set_migration_in_progress(False)
    activated = await service.decide_proposal(
        proposal["id"], "approve", expected_revision
    )
    assert activated["status"] == "active"
    repeated = await service.decide_proposal(
        proposal["id"], "approve", expected_revision
    )
    assert repeated["result_id"] == activated["result_id"]
    metrics = await service.get_metrics("reconciler-project")
    assert metrics["activation_count"] == 1
    assert metrics["automatic_activation_count"] == 0
    assert metrics["approval_wait_seconds"]["average"] is not None
    assert metrics["validation_count"] == 1
    assert metrics["validation_failure_rate"] == 0
    assert (
        await temp_db.fetchone(
            "SELECT embedding FROM curated_results_vec_next WHERE result_id = 'sentinel'"
        )
    )["embedding"] == sentinel_value


@pytest.mark.asyncio
async def test_effective_read_uses_fts_when_migration_or_dimension_is_unsafe(temp_db):
    await _add_memory(
        temp_db,
        "m1",
        "The same decision has a first supported form.",
        category="decision",
    )
    await _add_memory(
        temp_db,
        "m2",
        "The same decision has a second supported form.",
        category="decision",
    )
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    service = MemoryReconcilerService(
        temp_db, embedding_service=embedding, model=embedding.model_name
    )
    await service.create_run("reconciler-project", dry_run=False)
    await service.process_next("worker-1", MergeProvider())

    await temp_db.set_migration_in_progress(True)
    during = await service.effective_read.search(
        "supported", {"project_id": "reconciler-project"}, limit=5
    )
    await temp_db.set_migration_in_progress(False)
    await temp_db.set_embedding_metadata(
        "reconciler_embedding_dimension", str(temp_db.embedding_dim + 1)
    )
    mismatch = await service.effective_read.search(
        "supported", {"project_id": "reconciler-project"}, limit=5
    )

    assert [item.result_kind for item in during.results] == ["curated"]
    assert [item.result_kind for item in mismatch.results] == ["curated"]
