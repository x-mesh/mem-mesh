from unittest.mock import AsyncMock

import pytest

from app.core.services.effective_read import EffectiveReadService


@pytest.mark.asyncio
async def test_raw_exclusion_does_not_validate_other_projects():
    service = EffectiveReadService(AsyncMock())
    service._active_results = AsyncMock(return_value=[])
    await service.raw_exclusion({"project_id": "selected"})
    service._active_results.assert_awaited_once_with("selected")


@pytest.mark.asyncio
async def test_effective_pagination_collects_offset_candidates():
    from app.core.schemas.responses import SearchResponse, SearchResult

    service = EffectiveReadService(AsyncMock())
    service._revalidate_active_results = AsyncMock()
    service.get_read_revision = AsyncMock(return_value=1)
    service.db.migration_in_progress = AsyncMock(return_value=False)
    service.search_curated = AsyncMock(return_value=[])

    async def candidates(query, filters, limit, offset=0):
        return SearchResponse(
            total=50,
            results=[
                SearchResult(
                    id=str(i),
                    content="body",
                    similarity_score=1,
                    created_at="2026-10-20",
                    category="task",
                    source="test",
                    project_id="selected",
                )
                for i in range(min(limit, 50))
            ],
        )

    service._raw_candidates = AsyncMock(side_effect=candidates)
    response = await service.search("", limit=5, offset=25)
    assert len(response.results) == 5


@pytest.mark.asyncio
async def test_failed_candidate_can_be_retried_in_new_run(temp_db):
    from app.core.services.memory_reconciler import MemoryReconcilerService
    from tests.test_memory_reconciler import MergeProvider, _add_memory

    await _add_memory(temp_db, "m1", "The same release requires review.")
    await _add_memory(temp_db, "m2", "The same release requires review.")
    service = MemoryReconcilerService(temp_db)
    first = await service.create_run("reconciler-project")
    await temp_db.execute(
        "UPDATE reconciler_candidates SET status = 'failed' WHERE run_id = ?",
        (first["id"],),
    )
    second = await service.create_run("reconciler-project")
    candidates = await temp_db.fetchall(
        "SELECT * FROM reconciler_candidates WHERE run_id = ?", (second["id"],)
    )
    assert len(candidates) == 1
    result = await service.process_next("worker", MergeProvider())
    assert result["status"] != "failed"
    third = await service.create_run("reconciler-project")
    assert not await temp_db.fetchall(
        "SELECT id FROM reconciler_candidates WHERE run_id = ?", (third["id"],)
    )


@pytest.mark.asyncio
async def test_slow_judgment_renews_lease(temp_db):
    import asyncio

    from app.core.services.memory_reconciler import MemoryReconcilerService
    from tests.test_memory_reconciler import _add_memory

    await _add_memory(temp_db, "m1", "Release requires review.")
    service = MemoryReconcilerService(temp_db, lease_seconds=0.15)
    await service.create_run("reconciler-project")
    candidate = await service._claim_candidate("first")
    original = candidate["lease_until"]

    class SlowJudge:
        async def reconcile_group(self, evidence):
            await asyncio.sleep(0.3)
            assert await service._claim_candidate("second") is None
            return {"action": "no_op"}

    await service._judge_with_lease(candidate, SlowJudge(), [])
    assert candidate["lease_until"] > original


@pytest.mark.asyncio
async def test_migration_claim_is_exclusive_across_service_instances(
    temp_db, monkeypatch
):
    import asyncio
    from types import SimpleNamespace

    from app.core.services.embedding_manager import EmbeddingManagerService

    started = []

    async def background(self, *args):
        started.append(self)

    monkeypatch.setattr(
        EmbeddingManagerService, "_run_migration_background", background
    )
    managers = [
        EmbeddingManagerService(temp_db, SimpleNamespace(model_name="new", dimension=4))
        for _ in range(2)
    ]
    for manager in managers:
        manager.get_status = AsyncMock(
            return_value={"needs_migration": True, "total_memories": 1}
        )
    outcomes = await asyncio.gather(
        *(manager.start_migration() for manager in managers)
    )
    await asyncio.sleep(0)
    assert sum(item["success"] for item in outcomes) == 1
    assert len(started) == 1


@pytest.mark.asyncio
async def test_index_failure_can_recover_with_identical_sources(temp_db):
    from app.core.services.memory_reconciler import MemoryReconcilerService
    from tests.test_memory_reconciler import MergeProvider, _add_memory, _FakeEmbedding

    for mid in ("m1", "m2"):
        await _add_memory(temp_db, mid, "The same release requires review.")
    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim + 1)
    )
    await service.create_run("reconciler-project", dry_run=False)
    failed = await service.process_next("worker", MergeProvider())
    assert failed["processed"] is False
    service.embedding_service = _FakeEmbedding(temp_db.embedding_dim)
    await service.create_run("reconciler-project", dry_run=False)
    recovered = await service.process_next("worker", MergeProvider())
    assert recovered["status"] == "active"


@pytest.mark.asyncio
async def test_effective_filter_cache_isolation_and_full_page_total(temp_db):
    from tests.test_memory_reconciler import _add_memory

    service = EffectiveReadService(temp_db)
    for i in range(30):
        await _add_memory(
            temp_db, f"m{i:02d}", "Release fact", source="left" if i < 15 else "right"
        )
    left = await service.search(
        "Release", {"project_id": "reconciler-project", "source": "left"}, limit=5
    )
    right = await service.search(
        "Release", {"project_id": "reconciler-project", "source": "right"}, limit=5
    )
    assert {item.source for item in left.results} == {"left"}
    assert {item.source for item in right.results} == {"right"}
    page = await service.search(
        "", {"project_id": "reconciler-project"}, limit=5, offset=25
    )
    assert len(page.results) == 5
    assert page.total == 30


@pytest.mark.asyncio
async def test_effective_semantic_candidates_use_existing_ranker(temp_db, monkeypatch):
    from app.core.schemas.responses import SearchResponse, SearchResult
    from app.core.services.search import SearchService
    from tests.test_memory_reconciler import _add_memory

    await _add_memory(temp_db, "m1", "자동차 수리 기록")
    ranker = AsyncMock(
        return_value=SearchResponse(
            results=[
                SearchResult(
                    id="m1",
                    content="자동차 수리 기록",
                    similarity_score=0.9,
                    created_at="2026-10-20",
                    project_id="reconciler-project",
                    category="task",
                    source="session",
                )
            ]
        )
    )
    monkeypatch.setattr(SearchService, "_semantic_search", ranker)
    service = EffectiveReadService(temp_db, embedding_service=object())
    result = await service._raw_candidates(
        "vehicle repair",
        {"project_id": "reconciler-project", "search_mode": "semantic"},
        limit=5,
    )
    assert [item.id for item in result.results] == ["m1"]
    ranker.assert_awaited_once()


def test_detector_bounds_comparisons_for_unrelated_memories(monkeypatch):
    import app.core.services.memory_reconciler as module

    comparisons = 0

    def compare(left, right):
        nonlocal comparisons
        comparisons += 1
        return 0

    monkeypatch.setattr(module, "_similarity", compare)
    memories = [
        {
            "memory_id": f"m{i}",
            "content": str(i),
            "metadata": {"created_at": "2026-10-20T00:00:00Z", "source": "session"},
            "anchors": None,
            "relations": [],
        }
        for i in range(600)
    ]
    groups = module.MemoryReconcilerService(None)._detect_groups(memories, {}, 0.7)
    assert len(groups) == 600
    assert comparisons <= 600 * module.MAX_COMPARISON_GROUPS


@pytest.mark.asyncio
async def test_detector_loads_relations_once_for_project(temp_db, monkeypatch):
    from app.core.services.memory_reconciler import MemoryReconcilerService
    from tests.test_memory_reconciler import _add_memory

    for i in range(5):
        await _add_memory(temp_db, f"m{i}", "Release fact")
    fetch = temp_db.fetchall
    queries = []

    async def track(query, params=()):
        if "FROM memory_relations" in query:
            queries.append(query)
        return await fetch(query, params)

    monkeypatch.setattr(temp_db, "fetchall", track)
    await MemoryReconcilerService(temp_db).create_run("reconciler-project")
    assert len(queries) == 1


@pytest.mark.asyncio
async def test_overview_schedule_detects_result_cancellation(temp_db):
    from app.core.services.memory_reconciler import MemoryReconcilerService
    from app.core.services.overview import OverviewScheduler
    from tests.test_memory_reconciler import MergeProvider, _add_memory, _FakeEmbedding

    service = MemoryReconcilerService(
        temp_db, embedding_service=_FakeEmbedding(temp_db.embedding_dim)
    )
    for group in range(2):
        for i in range(2):
            await _add_memory(
                temp_db, f"m{group}-{i}", "The same release requires review."
            )
        await service.create_run("reconciler-project", dry_run=False)
        result = await service.process_next("worker", MergeProvider())
        assert result["status"] == "active"
    scheduler = OverviewScheduler(temp_db)
    await scheduler.set_enabled("reconciler-project", True)
    await temp_db.execute(
        "UPDATE overview_schedule SET last_run_at = '2026-10-20T00:00:00Z'"
    )
    await temp_db.execute(
        "UPDATE curated_results SET activated_at = '2026-10-19T00:00:00Z'"
    )
    await temp_db.execute(
        "UPDATE reconciler_proposals SET updated_at = '2026-10-19T00:00:00Z'"
    )
    assert await scheduler._claim_due_project("2026-10-22T00:00:00Z") is None
    await service.cancel_result(result["result_id"], 1)
    assert (
        await scheduler._claim_due_project("2026-10-22T00:00:00Z")
        == "reconciler-project"
    )
