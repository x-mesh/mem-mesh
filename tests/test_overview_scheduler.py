"""Scheduled project-overview regeneration (OverviewScheduler) tests."""

import os
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app.core.database.base import Database
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
        assert await ov.get_cached("projB") is None


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
async def test_not_rerun_within_interval():
    """After a run, the same project is not due again until the interval passes,
    even with fresh activity."""
    async with _temp_db() as db:
        sched = OverviewScheduler(db)
        ov = OverviewService(db)
        await sched.ensure_schema()
        await _add_memory(db, "a1", project_id="projA", hours_ago=1)
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
