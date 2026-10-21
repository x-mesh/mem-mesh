"""Project-scoped Reconciler trend samples and alert boundaries."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core.services.memory_reconciler import MemoryReconcilerService


async def _seed_windows(
    db,
    *,
    recent_failures=2,
    previous_failures=0,
    calls=10,
    previous_calls=None,
    recent_risk="high",
    previous_risk="low",
    recent_status="completed",
    budget_runs=0,
):
    async with db.transaction():
        for index in range(20):
            recent = index >= 10
            run_id = f"trend-{index:02}"
            timestamp = (
                datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
            ).isoformat()
            stats = {
                "llm_calls": (
                    calls if recent or previous_calls is None else previous_calls
                ),
                "judge_failed_calls": recent_failures if recent else previous_failures,
            }
            await db.execute(
                "INSERT INTO reconciler_runs(id, project_id, status, dry_run, policy_hash, stats_json, created_at, updated_at, completed_at) VALUES (?, 'trend-project', ?, 0, 'policy', ?, ?, ?, ?)",
                (
                    run_id,
                    recent_status if recent else "completed",
                    json.dumps(stats),
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            await db.execute(
                "INSERT INTO reconciler_candidates(id, run_id, project_id, group_key, memory_ids_json, input_policy_hash, status, terminal_reason, created_at, updated_at) VALUES (?, ?, 'trend-project', ?, '[]', ?, 'needs_review', ?, ?, ?)",
                (
                    run_id,
                    run_id,
                    run_id,
                    run_id,
                    (
                        "activation budget exceeded"
                        if recent and index < 10 + budget_runs
                        else "held"
                    ),
                    timestamp,
                    timestamp,
                ),
            )
            await db.execute(
                "INSERT INTO reconciler_proposals(id, candidate_id, run_id, project_id, action, status, input_policy_hash, proposal_json, created_at, updated_at) VALUES (?, ?, ?, 'trend-project', 'no_op', 'preview', ?, ?, ?, ?)",
                (
                    run_id,
                    run_id,
                    run_id,
                    run_id,
                    json.dumps({"risk": recent_risk if recent else previous_risk}),
                    timestamp,
                    timestamp,
                ),
            )


@pytest.mark.asyncio
async def test_trends_require_two_complete_windows(temp_db):
    await _seed_windows(temp_db, recent_status="cancelled")
    metrics = await MemoryReconcilerService(temp_db).get_metrics("trend-project")
    assert metrics["run_trends"] == {
        "window_runs": 10,
        "ready": False,
        "recent": None,
        "previous": None,
    }
    assert not any(item["kind"].endswith("increase") for item in metrics["alerts"])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "needs_approval"])
async def test_trends_compare_rates_and_count_repeated_budget_runs(temp_db, status):
    await _seed_windows(temp_db, budget_runs=2, recent_status=status)
    service = MemoryReconcilerService(temp_db)
    metrics = await service.get_metrics("trend-project")
    trends = metrics["run_trends"]
    assert trends["ready"] is True
    assert trends["recent"]["judge_failure_rate"] == 0.2
    assert trends["previous"]["judge_failure_rate"] == 0
    assert trends["recent"]["high_risk_proposal_rate"] == 1
    assert trends["previous"]["high_risk_proposal_rate"] == 0
    alerts = {item["kind"]: item["count"] for item in metrics["alerts"]}
    assert alerts["judge_failure_increase"] == 20
    assert alerts["high_risk_proposal_increase"] == 10
    assert alerts["activation_budget_repeated"] == 2
    assert (await service.get_metrics("another-project"))["run_trends"][
        "ready"
    ] is False


@pytest.mark.asyncio
async def test_failure_increase_uses_call_rate_instead_of_failure_count(temp_db):
    await _seed_windows(temp_db, previous_calls=100, previous_failures=10)
    metrics = await MemoryReconcilerService(temp_db).get_metrics("trend-project")
    assert metrics["run_trends"]["previous"]["judge_failure_rate"] == 0.1
    assert metrics["run_trends"]["recent"]["judge_failure_rate"] == 0.2
    assert (
        metrics["run_trends"]["previous"]["judge_failed_calls"]
        > metrics["run_trends"]["recent"]["judge_failed_calls"]
    )
    assert any(item["kind"] == "judge_failure_increase" for item in metrics["alerts"])


@pytest.mark.asyncio
async def test_repeated_budget_candidates_in_one_run_do_not_mean_repeated_runs(temp_db):
    await _seed_windows(temp_db, budget_runs=1)
    await temp_db.execute(
        "INSERT INTO reconciler_candidates(id, run_id, project_id, group_key, memory_ids_json, input_policy_hash, status, terminal_reason, created_at, updated_at) "
        "SELECT 'extra-budget', run_id, project_id, group_key, memory_ids_json, 'extra-budget', status, terminal_reason, created_at, updated_at "
        "FROM reconciler_candidates WHERE id = 'trend-10'"
    )
    metrics = await MemoryReconcilerService(temp_db).get_metrics("trend-project")
    assert metrics["run_trends"]["recent"]["activation_budget_run_count"] == 1
    assert not any(
        item["kind"] == "activation_budget_repeated" for item in metrics["alerts"]
    )


@pytest.mark.asyncio
async def test_budget_repetition_does_not_require_a_previous_window(temp_db):
    await _seed_windows(temp_db, budget_runs=2)
    await temp_db.execute(
        "UPDATE reconciler_runs SET status = 'queued', completed_at = NULL WHERE id < 'trend-10'"
    )
    metrics = await MemoryReconcilerService(temp_db).get_metrics("trend-project")
    assert metrics["run_trends"]["ready"] is False
    assert metrics["recent_activation_budget_run_count"] == 2
    assert {item["kind"]: item["count"] for item in metrics["alerts"]}[
        "activation_budget_repeated"
    ] == 2


@pytest.mark.asyncio
async def test_decreased_rates_do_not_trigger_increase_alerts(temp_db):
    await _seed_windows(
        temp_db,
        recent_failures=0,
        previous_failures=2,
        recent_risk="low",
        previous_risk="high",
    )
    metrics = await MemoryReconcilerService(temp_db).get_metrics("trend-project")
    assert metrics["run_trends"]["ready"] is True
    assert not any(item["kind"].endswith("increase") for item in metrics["alerts"])


@pytest.mark.asyncio
async def test_zero_calls_and_unclassified_risk_remain_unmeasured(temp_db):
    await _seed_windows(
        temp_db, calls=0, recent_failures=0, recent_risk="unrated", previous_risk=None
    )
    metrics = await MemoryReconcilerService(temp_db).get_metrics("trend-project")
    recent = metrics["run_trends"]["recent"]
    assert recent["judge_failure_rate"] is None
    assert recent["high_risk_proposal_rate"] is None
    assert recent["risk_classification_coverage"] == 0
    assert not any(item["kind"].endswith("increase") for item in metrics["alerts"])
