"""Scheduled project-overview regeneration (OverviewScheduler) tests."""

import json
import os
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app.core.database.base import Database
from app.core.services.effective_read import EffectiveReadService
from app.core.services.overview import (
    OverviewScheduler,
    OverviewService,
    clamp_interval_hours,
)


@asynccontextmanager
async def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path, embedding_dim=3)
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
        os.remove(path)


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


async def _add_memory(db, memory_id, *, project_id, hours_ago=0.0, content_hash="h"):
    ts = _iso(hours_ago)
    await db.execute(
        """
        INSERT INTO memories (
            id, content, content_hash, project_id, category, source,
            embedding, tags, status, created_at, updated_at, content_bytes
        )
        VALUES (?, ?, ?, ?, 'decision', 'test', ?, '[]', 'canonical', ?, ?, 0)
        """,
        (
            memory_id,
            "overview scheduler fixture content long enough for the quality gate",
            content_hash,
            project_id,
            b"123",
            ts,
            ts,
        ),
    )


async def _add_curated(db, result_id, memory_id, *, body):
    memory = await db.fetchone(
        "SELECT project_id FROM memories WHERE id = ?", (memory_id,)
    )
    project_id = memory["project_id"]
    now = _iso(0)
    run_id = f"run-{result_id}"
    candidate_id = f"candidate-{result_id}"
    proposal_id = f"proposal-{result_id}"
    policy_hash = f"policy-{result_id}"
    input_hash = await EffectiveReadService(db).current_input_hash(memory_id)
    await db.execute(
        "INSERT INTO reconciler_runs(id, project_id, status, dry_run, detector_version, policy_hash, model, prompt_version, budget_json, stats_json, created_at, updated_at) VALUES (?, ?, 'completed', 0, 'test', 'policy', 'judge', 'prompt', '{}', '{}', ?, ?)",
        (run_id, project_id, now, now),
    )
    await db.execute(
        "INSERT INTO reconciler_candidates(id, run_id, project_id, group_key, memory_ids_json, input_policy_hash, created_at, updated_at) VALUES (?, ?, ?, 'group', ?, ?, ?, ?)",
        (
            candidate_id,
            run_id,
            project_id,
            json.dumps([memory_id]),
            policy_hash,
            now,
            now,
        ),
    )
    await db.execute(
        "INSERT INTO reconciler_proposals(id, candidate_id, run_id, project_id, action, status, representative_memory_id, body, input_policy_hash, created_at, updated_at) VALUES (?, ?, ?, ?, 'merge', 'applied', ?, ?, ?, ?, ?)",
        (
            proposal_id,
            candidate_id,
            run_id,
            project_id,
            memory_id,
            body,
            policy_hash,
            now,
            now,
        ),
    )
    await db.execute(
        "INSERT INTO curated_results(id, proposal_id, candidate_id, project_id, representative_memory_id, body, action, status, revision, input_policy_hash, created_at, activated_at) VALUES (?, ?, ?, ?, ?, ?, 'merge', 'active', 1, ?, ?, ?)",
        (
            result_id,
            proposal_id,
            candidate_id,
            project_id,
            memory_id,
            body,
            policy_hash,
            now,
            now,
        ),
    )
    await db.execute(
        "INSERT INTO curated_sources(result_id, memory_id, input_hash, source_role) VALUES (?, ?, ?, 'representative')",
        (result_id, memory_id, input_hash),
    )
    await db.execute(
        "INSERT INTO curated_results_fts(result_id, body, project_id) VALUES (?, ?, ?)",
        (result_id, body, project_id),
    )


class _StubChat:
    """generate_project_overview stub — counts calls so tests can assert the
    LLM ran (or didn't)."""

    def __init__(self):
        self.calls = 0

    async def generate_project_overview(self, *, project_id, items, settings):
        self.calls += 1
        return {
            "summary": f"Summary of {project_id} ({len(items)} items)",
            "themes": ["t"],
            "recent_activity": [],
            "open_issues": [],
            "key_decisions": [],
            "source_memory_ids": [i["id"] for i in items],
            "model": "stub",
        }


@pytest.mark.asyncio
async def test_overview_accepts_actual_original_citations_and_preserves_dependencies():
    async with _temp_db() as db:
        await _add_memory(db, "a1", project_id="projA")
        await _add_curated(db, "cr-a1", "a1", body="Grounded project memory")

        class SourceChat(_StubChat):
            async def generate_project_overview(self, **kwargs):
                data = await super().generate_project_overview(**kwargs)
                source_id = kwargs["items"][0]["citations"][0]["memory_id"]
                data["source_memory_ids"] = [source_id]
                data["key_decisions"] = [
                    {"text": "Grounded project memory", "memory_id": source_id}
                ]
                return data

        service = OverviewService(db)
        generated = await service.generate(
            project_id="projA", chat_service=SourceChat(), settings=None
        )
        cached = await service.get_cached("projA")
        assert generated["overview"]["source_memory_ids"] == ["a1"]
        assert cached["overview"] == generated["overview"]
        assert cached["stale"] is False
        dependencies = await db.fetchall(
            "SELECT result_id FROM project_overview_sources WHERE project_id = 'projA'"
        )
        assert [row["result_id"] for row in dependencies] == ["cr-a1"]


@pytest.mark.asyncio
async def test_overview_rejects_uncited_original_from_the_same_project():
    from app.core.errors import ChatProviderError

    async with _temp_db() as db:
        await _add_memory(db, "a1", project_id="projA")
        await _add_memory(db, "uncited", project_id="projA")
        await _add_curated(db, "cr-a1", "a1", body="Grounded project memory")

        class UncitedChat(_StubChat):
            async def generate_project_overview(self, **kwargs):
                data = await super().generate_project_overview(**kwargs)
                data["source_memory_ids"] = ["uncited"]
                return data

        service = OverviewService(db)
        with pytest.raises(ChatProviderError, match="unsupported source"):
            await service.generate(
                project_id="projA", chat_service=UncitedChat(), settings=None
            )
        assert (await service.get_cached("projA"))["overview"] is None


class _RecordingNotifier:
    def __init__(self):
        self.events = []

    async def notify_overview_generated(self, data):
        self.events.append(data)


def test_clamp_interval_hours():
    assert clamp_interval_hours(3) == 6
    assert clamp_interval_hours(12) == 12
    assert clamp_interval_hours(99) == 24
    assert clamp_interval_hours("bad") == 12
    assert clamp_interval_hours(None) == 12


@pytest.mark.asyncio
async def test_only_enabled_projects_are_swept():
    async with _temp_db() as db:
        sched = OverviewScheduler(db)
        ov = OverviewService(db)
        await sched.ensure_schema()
        # projA enabled + recent activity; projB has activity but NOT enabled.
        await _add_memory(db, "a1", project_id="projA", hours_ago=1)
        await _add_memory(db, "b1", project_id="projB", hours_ago=1)
        await _add_curated(db, "cr-a1", "a1", body="Approved project A overview input")
        await sched.set_enabled("projA", True)

        chat = _StubChat()
        res = await sched.process_next(
            chat_service=chat, settings=None, overview_service=ov, interval_hours=6
        )
        assert res["processed"] is True
        assert res["project_id"] == "projA"
        assert res["generated"] is True
        assert chat.calls == 1
        # projB is untouched (not enabled).
        assert (await ov.get_cached("projB"))["unavailable"] is True


@pytest.mark.asyncio
async def test_idle_project_is_skipped():
    """An enabled project with no activity inside the interval window must not
    be regenerated — this is the 'don't re-summarize idle projects' guard."""
    async with _temp_db() as db:
        sched = OverviewScheduler(db)
        ov = OverviewService(db)
        await sched.ensure_schema()
        # Activity is 10h ago; interval window is 6h → outside → idle.
        await _add_memory(db, "a1", project_id="projA", hours_ago=10)
        await sched.set_enabled("projA", True)

        chat = _StubChat()
        res = await sched.process_next(
            chat_service=chat, settings=None, overview_service=ov, interval_hours=6
        )
        assert res == {"processed": False}
        assert chat.calls == 0


@pytest.mark.asyncio
async def test_old_memory_newly_curated_is_due_for_overview():
    async with _temp_db() as db:
        sched = OverviewScheduler(db)
        ov = OverviewService(db)
        await _add_memory(db, "a1", project_id="projA", hours_ago=10)
        await sched.set_enabled("projA", True)
        chat = _StubChat()

        assert await sched.process_next(
            chat_service=chat, settings=None, overview_service=ov, interval_hours=6
        ) == {"processed": False}
        await _add_curated(db, "cr-a1", "a1", body="Approved old project memory")

        result = await sched.process_next(
            chat_service=chat, settings=None, overview_service=ov, interval_hours=6
        )
        assert result["generated"] is True
        assert chat.calls == 1


@pytest.mark.asyncio
async def test_curated_activation_waits_for_interval_then_remains_due():
    async with _temp_db() as db:
        sched = OverviewScheduler(db)
        ov = OverviewService(db)
        await _add_memory(db, "a1", project_id="projA", hours_ago=20)
        await _add_curated(db, "cr-a1", "a1", body="Earlier project memory")
        await sched.set_enabled("projA", True)
        chat = _StubChat()
        await sched.process_next(
            chat_service=chat, settings=None, overview_service=ov, interval_hours=6
        )

        await _add_memory(db, "a2", project_id="projA", hours_ago=20)
        await _add_curated(db, "cr-a2", "a2", body="Later project memory")
        await db.execute(
            "UPDATE overview_schedule SET last_run_at = ? WHERE project_id = 'projA'",
            (_iso(8),),
        )
        await db.execute(
            "UPDATE curated_results SET created_at = ?, activated_at = ? WHERE id = 'cr-a2'",
            (_iso(7), _iso(7)),
        )
        await db.execute(
            "UPDATE curated_results SET created_at = ?, activated_at = ? WHERE id = 'cr-a1'",
            (_iso(9), _iso(9)),
        )

        result = await sched.process_next(
            chat_service=chat, settings=None, overview_service=ov, interval_hours=6
        )
        assert result["generated"] is True
        assert chat.calls == 2


@pytest.mark.asyncio
async def test_overview_coverage_and_new_uncovered_memory_staleness():
    async with _temp_db() as db:
        ov = OverviewService(db)
        await _add_memory(db, "a1", project_id="projA", hours_ago=10)
        await _add_memory(db, "a2", project_id="projA", hours_ago=10)
        await _add_curated(db, "cr-a1", "a1", body="Approved project memory")
        chat = _StubChat()

        generated = await ov.generate(
            project_id="projA", chat_service=chat, settings=None
        )
        assert generated["coverage"]["canonical_total"] == 2
        assert generated["coverage"]["covered_canonical"] == 1
        assert generated["partial"] is True
        assert (await ov.get_cached("projA"))["stale"] is False

        await _add_memory(db, "a3", project_id="projA", hours_ago=0)
        cached = await ov.get_cached("projA")
        assert cached["stale"] is True
        assert cached["coverage"]["canonical_total"] == 3
        assert cached["coverage"]["covered_canonical"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["source", "result", "new_memory"])
async def test_generation_rechecks_inputs_and_preserves_previous_cache(change):
    from app.core.errors import ReconcilerConflictError

    async with _temp_db() as db:
        await _add_memory(db, "a1", project_id="projA")
        await _add_curated(db, "cr-a1", "a1", body="Grounded project memory")
        service = OverviewService(db)
        await service.generate(
            project_id="projA", chat_service=_StubChat(), settings=None
        )
        prior = dict(
            await db.fetchone(
                "SELECT * FROM project_overview WHERE project_id = 'projA'"
            )
        )

        class MutatingChat(_StubChat):
            async def generate_project_overview(self, **kwargs):
                data = await super().generate_project_overview(**kwargs)
                if change == "source":
                    await db.execute(
                        "UPDATE memories SET content = 'Changed canonical input' WHERE id = 'a1'"
                    )
                elif change == "result":
                    await db.execute(
                        "UPDATE curated_results SET status = 'cancelled', revision = revision + 1 WHERE id = 'cr-a1'"
                    )
                else:
                    await _add_memory(db, "a2", project_id="projA")
                return data

        with pytest.raises(ReconcilerConflictError, match="inputs changed"):
            await service.generate(
                project_id="projA", chat_service=MutatingChat(), settings=None
            )
        assert (
            dict(
                await db.fetchone(
                    "SELECT * FROM project_overview WHERE project_id = 'projA'"
                )
            )
            == prior
        )
        assert (await service.get_cached("projA"))["stale"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field", ["source_memory_ids", "open_issues", "key_decisions", "summary"]
)
async def test_generation_rejects_invalid_output_without_replacing_cache(field):
    from app.core.errors import ChatProviderError

    async with _temp_db() as db:
        await _add_memory(db, "a1", project_id="projA")
        await _add_curated(db, "cr-a1", "a1", body="Grounded project memory")
        service = OverviewService(db)
        await service.generate(
            project_id="projA", chat_service=_StubChat(), settings=None
        )
        prior = dict(
            await db.fetchone(
                "SELECT * FROM project_overview WHERE project_id = 'projA'"
            )
        )

        class InvalidChat(_StubChat):
            async def generate_project_overview(self, **kwargs):
                data = await super().generate_project_overview(**kwargs)
                if field == "source_memory_ids":
                    data[field] = ["another-project-source"]
                elif field == "summary":
                    data[field] = None
                else:
                    data[field] = [
                        {
                            "text": "Unsupported claim",
                            "memory_id": "another-project-source",
                        }
                    ]
                return data

        with pytest.raises(ChatProviderError, match="overview"):
            await service.generate(
                project_id="projA", chat_service=InvalidChat(), settings=None
            )
        assert (
            dict(
                await db.fetchone(
                    "SELECT * FROM project_overview WHERE project_id = 'projA'"
                )
            )
            == prior
        )


@pytest.mark.asyncio
async def test_cached_overview_with_invalid_source_is_unavailable():
    async with _temp_db() as db:
        await _add_memory(db, "a1", project_id="projA")
        await _add_curated(db, "cr-a1", "a1", body="Grounded project memory")
        service = OverviewService(db)
        generated = await service.generate(
            project_id="projA", chat_service=_StubChat(), settings=None
        )
        invalid = {
            **generated["overview"],
            "source_memory_ids": ["another-project-source"],
        }
        await db.execute(
            "UPDATE project_overview SET overview_json = ? WHERE project_id = 'projA'",
            (json.dumps(invalid),),
        )

        cached = await service.get_cached("projA")

        assert cached["overview"] is None
        assert cached["stale"] is True
        assert cached["unavailable"] is True


@pytest.mark.asyncio
async def test_needs_review_proposal_marks_overview_partial_and_stale():
    async with _temp_db() as db:
        ov = OverviewService(db)
        await _add_memory(db, "a1", project_id="projA", hours_ago=10)
        await _add_curated(db, "cr-a1", "a1", body="Approved project memory")
        chat = _StubChat()
        generated = await ov.generate(
            project_id="projA", chat_service=chat, settings=None
        )
        assert generated["partial"] is False

        await _add_memory(db, "a2", project_id="projA", hours_ago=10)
        await _add_curated(db, "cr-a2", "a2", body="Unresolved project memory")
        await db.execute(
            "UPDATE curated_results SET status = 'inactive' WHERE id = 'cr-a2'"
        )
        await db.execute(
            "UPDATE reconciler_proposals SET status = 'needs_review' WHERE id = 'proposal-cr-a2'"
        )

        cached = await ov.get_cached("projA")
        assert cached["stale"] is True
        assert cached["partial"] is True
        assert cached["unreviewed_count"] == 1

        await ov.generate(project_id="projA", chat_service=chat, settings=None)
        await db.execute(
            "UPDATE reconciler_proposals SET status = 'rejected' WHERE id = 'proposal-cr-a2'"
        )
        resolved = await ov.get_cached("projA")
        assert resolved["stale"] is True
        assert resolved["unreviewed_count"] == 0


@pytest.mark.asyncio
async def test_unreviewed_count_excludes_preview_and_deduplicates_live_group():
    async with _temp_db() as db:
        ov = OverviewService(db)
        for suffix in ("preview", "live-1", "live-2"):
            memory_id = f"memory-{suffix}"
            result_id = f"result-{suffix}"
            await _add_memory(db, memory_id, project_id="projA", hours_ago=1)
            await _add_curated(db, result_id, memory_id, body="Held result")
            await db.execute(
                "UPDATE curated_results SET status = 'inactive' WHERE id = ?",
                (result_id,),
            )
            await db.execute(
                "UPDATE reconciler_proposals SET status = 'needs_review' WHERE id = ?",
                (f"proposal-{result_id}",),
            )
            await db.execute(
                "UPDATE reconciler_candidates SET group_key = 'same-group' WHERE id = ?",
                (f"candidate-{result_id}",),
            )
        await db.execute(
            "UPDATE reconciler_runs SET dry_run = 1 WHERE id = 'run-result-preview'"
        )

        cached = await ov.get_cached("projA")

        assert cached["unreviewed_count"] == 1


@pytest.mark.asyncio
async def test_not_rerun_within_interval():
    """After a run, the same project is not due again until the interval passes,
    even with fresh activity."""
    async with _temp_db() as db:
        sched = OverviewScheduler(db)
        ov = OverviewService(db)
        await sched.ensure_schema()
        await _add_memory(db, "a1", project_id="projA", hours_ago=1)
        await _add_curated(db, "cr-a1", "a1", body="Approved project A overview input")
        await sched.set_enabled("projA", True)

        chat = _StubChat()
        first = await sched.process_next(
            chat_service=chat, settings=None, overview_service=ov, interval_hours=6
        )
        assert first["generated"] is True

        # New activity arrives, but last_run_at is now → still within interval.
        await _add_memory(db, "a2", project_id="projA", hours_ago=0, content_hash="h2")
        second = await sched.process_next(
            chat_service=chat, settings=None, overview_service=ov, interval_hours=6
        )
        assert second == {"processed": False}
        assert chat.calls == 1


@pytest.mark.asyncio
async def test_fresh_cache_advances_clock_without_llm():
    """If the cached overview is already current, the sweep advances last_run_at
    but skips the LLM call."""
    async with _temp_db() as db:
        sched = OverviewScheduler(db)
        ov = OverviewService(db)
        await sched.ensure_schema()
        await _add_memory(db, "a1", project_id="projA", hours_ago=1)
        await _add_curated(db, "cr-a1", "a1", body="Approved project A overview input")
        await sched.set_enabled("projA", True)

        chat = _StubChat()
        # Pre-generate so the cache is fresh, then force the schedule to look due
        # by backdating last_run_at.
        await ov.generate(project_id="projA", chat_service=chat, settings=None)
        assert chat.calls == 1
        await db.execute(
            "UPDATE overview_schedule SET last_run_at = ? WHERE project_id = 'projA'",
            (_iso(48),),
        )

        res = await sched.process_next(
            chat_service=chat, settings=None, overview_service=ov, interval_hours=6
        )
        assert res["processed"] is True
        assert res["generated"] is False
        assert res.get("skipped_fresh") is True
        assert chat.calls == 1  # no second LLM call


@pytest.mark.asyncio
async def test_notifier_fires_on_generation():
    async with _temp_db() as db:
        sched = OverviewScheduler(db)
        ov = OverviewService(db)
        await sched.ensure_schema()
        await _add_memory(db, "a1", project_id="projA", hours_ago=1)
        await _add_curated(db, "cr-a1", "a1", body="Approved project A overview input")
        await sched.set_enabled("projA", True)

        chat = _StubChat()
        notifier = _RecordingNotifier()
        await sched.process_next(
            chat_service=chat,
            settings=None,
            overview_service=ov,
            interval_hours=6,
            notifier=notifier,
        )
        assert len(notifier.events) == 1
        assert notifier.events[0]["project_id"] == "projA"
        assert notifier.events[0]["item_count"] == 1


@pytest.mark.asyncio
async def test_disable_stops_sweeping():
    async with _temp_db() as db:
        sched = OverviewScheduler(db)
        ov = OverviewService(db)
        await sched.ensure_schema()
        await _add_memory(db, "a1", project_id="projA", hours_ago=1)
        await _add_curated(db, "cr-a1", "a1", body="Approved project A overview input")
        await sched.set_enabled("projA", True)
        await sched.set_enabled("projA", False)

        chat = _StubChat()
        res = await sched.process_next(
            chat_service=chat, settings=None, overview_service=ov, interval_hours=6
        )
        assert res == {"processed": False}
        assert chat.calls == 0


@pytest.mark.asyncio
async def test_relay_worker_run_once_drains_overview():
    """The overview task is reachable through RelayWorker.run_once wiring."""
    from app.core.services.relay import RelayService
    from app.core.services.relay_worker import RelayWorker

    async with _temp_db() as db:
        sched = OverviewScheduler(db)
        ov = OverviewService(db)
        await sched.ensure_schema()
        await _add_memory(db, "a1", project_id="projA", hours_ago=1)
        await _add_curated(db, "cr-a1", "a1", body="Approved project A overview input")
        await sched.set_enabled("projA", True)

        chat = _StubChat()
        service = RelayService(db)
        await service.ensure_schema()
        worker = RelayWorker(
            service=service,
            worker_id="w1",
            overview_scheduler=sched,
            overview_service=ov,
            chat_service=chat,
            chat_settings=object(),  # production always wires settings (non-None)
            overview_interval_hours=6,
        )

        stats = await worker.run_once()
        assert stats["overview_processed"] == 1
        assert chat.calls == 1
        cached = await ov.get_cached("projA")
        assert cached is not None and cached["overview"] is not None


@pytest.mark.asyncio
async def test_no_run_and_no_curated_items_are_unavailable_without_chat():
    async with _temp_db() as db:
        ov = OverviewService(db)
        await _add_memory(db, "raw1", project_id="projA", hours_ago=1)
        chat = _StubChat()

        cached = await ov.get_cached("projA")
        generated = await ov.generate(
            project_id="projA", chat_service=chat, settings=None
        )

        assert cached["overview"] is None
        assert cached["unavailable"] is True
        assert generated["overview"] is None
        assert generated["empty"] is True
        assert generated["unavailable"] is True
        assert chat.calls == 0


@pytest.mark.asyncio
async def test_legacy_raw_cache_is_not_served_or_sent_to_chat():
    async with _temp_db() as db:
        ov = OverviewService(db)
        await ov.ensure_schema()
        await db.execute(
            "INSERT INTO project_overview(project_id, overview_json, source_hash, item_count, model, created_at) VALUES ('projA', ?, 'legacy', 1, 'legacy', ?)",
            (json.dumps({"summary": "raw legacy summary"}), _iso(1)),
        )
        chat = _StubChat()

        cached = await ov.get_cached("projA")
        generated = await ov.generate(
            project_id="projA", chat_service=chat, settings=None
        )

        assert cached["overview"] is None
        assert cached["unavailable"] is True
        assert generated["overview"] is None
        assert chat.calls == 0


# ── HTTP routes (per-project schedule toggle) ───────────────────────────────


def _overview_app(db):
    from fastapi import FastAPI

    from app.web.common.dependencies import get_database
    from app.web.dashboard.route_modules.overview import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_database] = lambda: db
    return app


@pytest.mark.asyncio
async def test_overview_endpoint_explains_missing_derived_input_without_calling_llm():
    from httpx import ASGITransport, AsyncClient

    from app.web.dashboard.route_modules.overview import get_chat_service_dep

    async with _temp_db() as db:
        await _add_memory(db, "raw-only", project_id="projA")

        class ConfiguredChat(_StubChat):
            async def is_configured(self, settings):
                return True

        chat = ConfiguredChat()
        app = _overview_app(db)
        app.dependency_overrides[get_chat_service_dep] = lambda: chat
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/projects/projA/overview")
        assert response.status_code == 404
        assert "no active derived summaries" in response.json()["detail"]
        assert chat.calls == 0
        assert (await db.fetchone("SELECT COUNT(*) AS n FROM memories"))["n"] == 1


@pytest.mark.asyncio
async def test_overview_endpoint_reports_generation_input_conflict():
    from httpx import ASGITransport, AsyncClient

    from app.web.dashboard.route_modules.overview import get_chat_service_dep

    async with _temp_db() as db:
        await _add_memory(db, "a1", project_id="projA")
        await _add_curated(db, "cr-a1", "a1", body="Grounded project memory")

        class ChangingChat(_StubChat):
            async def is_configured(self, settings):
                return True

            async def generate_project_overview(self, **kwargs):
                data = await super().generate_project_overview(**kwargs)
                await db.execute(
                    "UPDATE memories SET content = 'Changed' WHERE id = 'a1'"
                )
                return data

        app = _overview_app(db)
        app.dependency_overrides[get_chat_service_dep] = lambda: ChangingChat()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/projects/projA/overview")
        assert response.status_code == 409
        assert "inputs changed" in response.json()["detail"]
        assert (
            await db.fetchone(
                "SELECT * FROM project_overview WHERE project_id = 'projA'"
            )
            is None
        )


@pytest.mark.asyncio
async def test_schedule_toggle_endpoints():
    from httpx import ASGITransport, AsyncClient

    async with _temp_db() as db:
        app = _overview_app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            # initially empty
            r = await client.get("/api/projects/overview/schedules")
            assert r.status_code == 200
            assert r.json() == {"schedules": []}

            # enable
            r = await client.put(
                "/api/projects/projA/overview/schedule", json={"enabled": True}
            )
            assert r.status_code == 200
            assert r.json() == {"project_id": "projA", "enabled": True}

            r = await client.get("/api/projects/overview/schedules")
            schedules = r.json()["schedules"]
            assert len(schedules) == 1
            assert schedules[0]["project_id"] == "projA"
            assert schedules[0]["enabled"] is True

            # disable
            r = await client.put(
                "/api/projects/projA/overview/schedule", json={"enabled": False}
            )
            assert r.json()["enabled"] is False
