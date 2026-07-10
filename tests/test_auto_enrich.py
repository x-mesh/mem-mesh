"""Auto-enrich: per-project opt-in subscription, gate, write-time hook, and the
periodic worker sweep."""

import os
import tempfile
from contextlib import asynccontextmanager

import pytest

from app.core.database.base import Database
from app.core.services.maintenance import MaintenanceService


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


async def _add_memory(db, memory_id, *, project_id="proj"):
    await db.execute(
        """
        INSERT INTO memories (
            id, content, content_hash, project_id, category, source,
            embedding, tags, status, created_at, updated_at, content_bytes
        )
        VALUES (?, ?, ?, ?, 'decision', 'test', ?, '[]', 'canonical', ?, ?, ?)
        """,
        (
            memory_id,
            "content long enough here",
            f"h-{memory_id}",
            project_id,
            b"123",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            0,
        ),
    )


def _patch_relay_llm(monkeypatch, *, api_key):
    async def _fake(db, settings, service):
        return {"provider": "anthropic", "api_key": api_key, "model": "m"}

    monkeypatch.setattr("app.core.services.llm_resolver.resolve_service_llm", _fake)


# ── t1: subscription CRUD ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_enrich_subscription_defaults_to_none():
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        assert await svc.get_auto_enrich("proj") is None
        assert await svc.list_auto_enrich_enabled() == []


@pytest.mark.asyncio
async def test_auto_enrich_subscription_toggle_persists():
    async with _temp_db() as db:
        svc = MaintenanceService(db)

        sub = await svc.set_auto_enrich("proj", enabled=True)
        assert sub.enabled is True
        assert sub.operations == ["enrich"]

        fetched = await svc.get_auto_enrich("proj")
        assert fetched is not None and fetched.enabled is True
        assert [s.project_id for s in await svc.list_auto_enrich_enabled()] == ["proj"]

        # Disable → dropped from the enabled list, row retained.
        await svc.set_auto_enrich("proj", enabled=False)
        assert (await svc.get_auto_enrich("proj")).enabled is False
        assert await svc.list_auto_enrich_enabled() == []


@pytest.mark.asyncio
async def test_auto_enrich_operations_are_validated():
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        # Unknown ops dropped; empty falls back to ["enrich"].
        sub = await svc.set_auto_enrich(
            "proj", enabled=True, operations=["improve", "bogus"]
        )
        assert sub.operations == ["improve"]
        sub2 = await svc.set_auto_enrich("p2", enabled=True, operations=["bogus"])
        assert sub2.operations == ["enrich"]


# ── t2: gate (enabled AND worker LLM configured) ─────────────────────────────


@pytest.mark.asyncio
async def test_auto_enrich_active_requires_enabled_and_llm(monkeypatch):
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        settings = object()

        # disabled (no subscription) → inactive regardless of LLM.
        _patch_relay_llm(monkeypatch, api_key="sk-123")
        assert await svc.auto_enrich_active("proj", settings) is False

        # enabled + LLM configured → active.
        await svc.set_auto_enrich("proj", enabled=True)
        assert await svc.auto_enrich_active("proj", settings) is True

        # enabled but LLM missing → inactive (would only pile up undrained).
        _patch_relay_llm(monkeypatch, api_key=None)
        assert await svc.auto_enrich_active("proj", settings) is False


# ── t4: batch cap ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enqueue_project_batch_cap_limits_new_jobs():
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        await svc.ensure_schema()
        for i in range(5):
            await _add_memory(db, f"m{i}")

        first = await svc.enqueue_project(
            project_id="proj", operations=["enrich"], limit=2
        )
        assert first["enqueued"]["enrich"] == 2

        # Next sweep enqueues the remainder (idempotent — no dupes for the 2).
        second = await svc.enqueue_project(
            project_id="proj", operations=["enrich"], limit=2
        )
        assert second["enqueued"]["enrich"] == 2

        third = await svc.enqueue_project(
            project_id="proj", operations=["enrich"], limit=2
        )
        assert third["enqueued"]["enrich"] == 1  # only the 5th remains

        total = await db.fetchone(
            "SELECT COUNT(*) AS n FROM maintenance_queue WHERE operation = 'enrich'"
        )
        assert total["n"] == 5


# ── t3: write-time hook ──────────────────────────────────────────────────────


def _memory_service(db):
    from app.core.services.memory import MemoryService

    # conflict_detector injected (non-None) to skip ML model init (CLAUDE.md L1).
    return MemoryService(db, embedding_service=object(), conflict_detector=object())


@pytest.mark.asyncio
async def test_write_time_hook_enqueues_when_active(monkeypatch):
    from types import SimpleNamespace

    async with _temp_db() as db:
        await MaintenanceService(db).set_auto_enrich("proj", enabled=True)
        _patch_relay_llm(monkeypatch, api_key="sk-1")

        mem_svc = _memory_service(db)
        await mem_svc._auto_enrich_new_memory(
            SimpleNamespace(id="m1", content_hash="h1"), "proj"
        )
        row = await db.fetchone(
            "SELECT COUNT(*) AS n FROM maintenance_queue "
            "WHERE memory_id = 'm1' AND operation = 'enrich'"
        )
        assert row["n"] == 1


@pytest.mark.asyncio
async def test_write_time_hook_noop_when_disabled_or_no_llm(monkeypatch):
    from types import SimpleNamespace

    async with _temp_db() as db:
        await MaintenanceService(db).ensure_schema()
        mem_svc = _memory_service(db)
        mem = SimpleNamespace(id="m1", content_hash="h1")

        # disabled (no subscription) even with an LLM → no enqueue.
        _patch_relay_llm(monkeypatch, api_key="sk-1")
        await mem_svc._auto_enrich_new_memory(mem, "proj")

        # enabled but LLM missing → no enqueue.
        await MaintenanceService(db).set_auto_enrich("proj", enabled=True)
        _patch_relay_llm(monkeypatch, api_key=None)
        await mem_svc._auto_enrich_new_memory(mem, "proj")

        row = await db.fetchone("SELECT COUNT(*) AS n FROM maintenance_queue")
        assert row["n"] == 0


# ── t5: worker periodic sweep ────────────────────────────────────────────────


def _worker(db, *, batch_cap=2, backfill=False):
    from app.core.services.relay import RelayService
    from app.core.services.relay_worker import RelayWorker

    # Only maintenance_service + chat_settings set → run_once runs the sweep
    # only (drain needs chat_service; all other steps need their own services).
    return RelayWorker(
        service=RelayService(db),
        worker_id="w1",
        maintenance_service=MaintenanceService(db),
        chat_settings=object(),
        auto_enrich_batch_cap=batch_cap,
        enrich_backfill_enabled=backfill,
    )


@pytest.mark.asyncio
async def test_worker_sweep_batch_capped_and_idempotent(monkeypatch):
    async with _temp_db() as db:
        await MaintenanceService(db).set_auto_enrich("proj", enabled=True)
        for i in range(3):
            await _add_memory(db, f"m{i}")
        _patch_relay_llm(monkeypatch, api_key="sk-1")

        worker = _worker(db, batch_cap=2)

        s1 = await worker.run_once()
        assert s1.get("auto_enrich_enqueued") == 2

        # Next interval: enqueue the remainder, no dupes for the first two.
        worker._last_auto_enrich_sweep_monotonic = None
        s2 = await worker.run_once()
        assert s2.get("auto_enrich_enqueued") == 1

        worker._last_auto_enrich_sweep_monotonic = None
        s3 = await worker.run_once()
        assert "auto_enrich_enqueued" not in s3  # backlog drained, nothing new

        n = await db.fetchone("SELECT COUNT(*) AS n FROM maintenance_queue")
        assert n["n"] == 3


@pytest.mark.asyncio
async def test_worker_sweep_noop_without_llm(monkeypatch):
    async with _temp_db() as db:
        await MaintenanceService(db).set_auto_enrich("proj", enabled=True)
        await _add_memory(db, "m0")
        _patch_relay_llm(monkeypatch, api_key=None)

        worker = _worker(db)
        s = await worker.run_once()
        assert "auto_enrich_enqueued" not in s
        n = await db.fetchone("SELECT COUNT(*) AS n FROM maintenance_queue")
        assert n["n"] == 0


# ── enrich backfill (convergent, confidence IS NULL target) ──────────────────


@pytest.mark.asyncio
async def test_enqueue_backfill_targets_null_confidence_and_converges():
    from app.core.services.enrich_store import EnrichmentStore

    async with _temp_db() as db:
        svc = MaintenanceService(db)
        store = EnrichmentStore(db)
        await _add_memory(db, "m1")
        await _add_memory(db, "m2")
        await store.upsert(memory_id="m1", title="T")  # confidence NULL (pre-field)
        await store.upsert(memory_id="m2", title="T", confidence=0.8)  # has field

        res = await svc.enqueue_backfill(limit=100)
        assert res["enqueued"] == 1  # only m1 targeted
        row = await db.fetchone(
            "SELECT memory_id FROM maintenance_queue WHERE operation = 'enrich'"
        )
        assert row["memory_id"] == "m1"

        # Simulate the re-enrich completing → confidence set → converges to 0.
        await store.upsert(memory_id="m1", title="T", confidence=0.5)
        assert await svc.enqueue_backfill(limit=100) == {"enqueued": 0, "scanned": 0}


@pytest.mark.asyncio
async def test_worker_backfill_sweep_enqueues_when_enabled(monkeypatch):
    from app.core.services.enrich_store import EnrichmentStore

    async with _temp_db() as db:
        await _add_memory(db, "m1")
        await EnrichmentStore(db).upsert(memory_id="m1", title="T")  # NULL confidence
        _patch_relay_llm(monkeypatch, api_key="sk-1")

        s = await _worker(db, backfill=True).run_once()
        assert s.get("enrich_backfill_enqueued") == 1


@pytest.mark.asyncio
async def test_worker_backfill_noop_when_disabled_or_no_llm(monkeypatch):
    from app.core.services.enrich_store import EnrichmentStore

    async with _temp_db() as db:
        await _add_memory(db, "m1")
        await EnrichmentStore(db).upsert(memory_id="m1", title="T")

        # disabled
        _patch_relay_llm(monkeypatch, api_key="sk-1")
        assert (
            "enrich_backfill_enqueued"
            not in await _worker(db, backfill=False).run_once()
        )

        # enabled but no LLM
        _patch_relay_llm(monkeypatch, api_key=None)
        assert (
            "enrich_backfill_enqueued"
            not in await _worker(db, backfill=True).run_once()
        )
