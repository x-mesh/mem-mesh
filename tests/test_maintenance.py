"""Project-level batch maintenance (enrich/improve) tests."""

import os
import tempfile
from contextlib import asynccontextmanager

import pytest

from app.core.database.base import Database
from app.core.services.enrich_store import EnrichmentStore
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


async def _add_memory(
    db,
    memory_id,
    *,
    content="content long enough here",
    content_hash="h",
    project_id="proj",
    category="decision",
    status="canonical",
):
    await db.execute(
        """
        INSERT INTO memories (
            id, content, content_hash, project_id, category, source,
            embedding, tags, status, created_at, updated_at, content_bytes
        )
        VALUES (?, ?, ?, ?, ?, 'test', ?, '[]', ?, ?, ?, ?)
        """,
        (
            memory_id,
            content,
            content_hash,
            project_id,
            category,
            b"123",
            status,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            0,
        ),
    )


class _StubChat:
    async def enrich_memory_content(self, *, content, settings):
        return {
            "title": "T",
            "abstract": "A",
            "tags": ["x"],
            "display_kind": "decision",
            "model": "stub",
        }

    async def refine_memory_content(self, *, content, category, tags, settings):
        return {
            "content": content + " (improved)",
            "category": "decision",
            "tags": ["y"],
            "rationale": "clearer",
            "model": "stub",
        }


@pytest.mark.asyncio
async def test_enqueue_project_dedups_live_jobs():
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        await svc.ensure_schema()
        for i in range(3):
            await _add_memory(db, f"m{i}", content_hash=f"h{i}")

        r = await svc.enqueue_project(
            project_id="proj", operations=["enrich", "improve"], force=False
        )
        assert r["enqueued"] == {"enrich": 3, "improve": 3}
        assert r["total_memories"] == 3

        # Re-run: live jobs already queued → all skipped, none duplicated.
        r2 = await svc.enqueue_project(
            project_id="proj", operations=["enrich"], force=False
        )
        assert r2["enqueued"]["enrich"] == 0
        assert r2["skipped"]["enrich"] == 3


@pytest.mark.asyncio
async def test_enqueue_skips_already_enriched_unless_forced():
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        await svc.ensure_schema()
        await _add_memory(db, "m1")
        await EnrichmentStore(db).upsert(memory_id="m1", title="done")

        r = await svc.enqueue_project(
            project_id="proj", operations=["enrich"], force=False
        )
        assert r["enqueued"]["enrich"] == 0
        assert r["skipped"]["enrich"] == 1

        forced = await svc.enqueue_project(
            project_id="proj", operations=["enrich"], force=True
        )
        assert forced["enqueued"]["enrich"] == 1


@pytest.mark.asyncio
async def test_process_enrich_writes_enrichment_store():
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        await svc.ensure_schema()
        await _add_memory(db, "m1")
        await svc.enqueue_project(project_id="proj", operations=["enrich"], force=False)

        result = await svc.process_next(
            worker_id="w", chat_service=_StubChat(), settings=None
        )
        assert result["processed"] is True
        assert result["operation"] == "enrich"

        enrichment = await EnrichmentStore(db).get("m1")
        assert enrichment is not None
        assert enrichment["title"] == "T"
        assert enrichment["abstract"] == "A"


@pytest.mark.asyncio
async def test_process_improve_stores_proposal_not_applied():
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        await svc.ensure_schema()
        await _add_memory(db, "m1", content="original content here", content_hash="h1")
        await svc.enqueue_project(
            project_id="proj", operations=["improve"], force=False
        )

        await svc.process_next(worker_id="w", chat_service=_StubChat(), settings=None)

        # Memory content untouched — improve only proposes.
        row = await db.fetchone("SELECT content FROM memories WHERE id = 'm1'")
        assert row["content"] == "original content here"

        proposals = await svc.list_refine_proposals(project_id="proj")
        assert len(proposals) == 1
        assert proposals[0]["proposed_content"].endswith("(improved)")
        assert proposals[0]["stale"] is False


@pytest.mark.asyncio
async def test_process_stale_job_when_memory_changed():
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        await svc.ensure_schema()
        await _add_memory(db, "m1", content_hash="h1")
        await svc.enqueue_project(project_id="proj", operations=["enrich"], force=False)
        # Memory edited after enqueue → content_hash drift → job goes stale.
        await db.execute("UPDATE memories SET content_hash = 'h2' WHERE id = 'm1'")

        result = await svc.process_next(
            worker_id="w", chat_service=_StubChat(), settings=None
        )
        assert result["stale"] is True
        assert await EnrichmentStore(db).get("m1") is None


@pytest.mark.asyncio
async def test_cancel_pending_scoped_by_operation():
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        await svc.ensure_schema()
        for i in range(3):
            await _add_memory(db, f"m{i}", content_hash=f"h{i}")
        await svc.enqueue_project(
            project_id="proj", operations=["enrich", "improve"], force=False
        )

        cancelled = await svc.cancel_pending(operation="improve")
        assert cancelled == 3

        counts = await svc.status_counts()
        # improve cancelled, enrich untouched.
        assert counts["improve"] == {"cancelled": 3}
        assert counts["enrich"] == {"pending": 3}

        # A cancelled job is never claimed by the worker.
        result = await svc.process_next(
            worker_id="w", chat_service=_StubChat(), settings=None
        )
        assert result["operation"] == "enrich"  # picks the pending enrich, not improve


class _FailingChat:
    """Chat stub that always fails — drives jobs into retry/dead_letter."""

    async def enrich_memory_content(self, *, content, settings):
        raise RuntimeError("Could not parse the model's refinement output as JSON")

    async def refine_memory_content(self, *, content, category, tags, settings):
        raise RuntimeError("Could not parse the model's refinement output as JSON")


@pytest.mark.asyncio
async def test_finish_done_clears_last_error():
    """A job that failed once then succeeded must not keep the old error."""
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        await svc.ensure_schema()
        await _add_memory(db, "m1")
        await svc.enqueue_project(project_id="proj", operations=["enrich"], force=False)

        # First attempt fails → pending retry with last_error recorded.
        await svc.process_next(
            worker_id="w", chat_service=_FailingChat(), settings=None
        )
        row = await db.fetchone("SELECT status, last_error FROM maintenance_queue")
        assert row["status"] == "pending"
        assert "Could not parse" in row["last_error"]

        # Skip the backoff, then succeed → done with last_error cleared.
        await db.execute("UPDATE maintenance_queue SET next_attempt_at = 0")
        result = await svc.process_next(
            worker_id="w", chat_service=_StubChat(), settings=None
        )
        assert result["processed"] is True
        row = await db.fetchone("SELECT status, last_error FROM maintenance_queue")
        assert row["status"] == "done"
        assert row["last_error"] is None


async def _dead_letter_all(db, svc):
    """Drain the queue with a failing chat until every job is dead-lettered."""
    for _ in range(20):
        await db.execute(
            "UPDATE maintenance_queue SET next_attempt_at = 0 "
            "WHERE status = 'pending'"
        )
        result = await svc.process_next(
            worker_id="w", chat_service=_FailingChat(), settings=None
        )
        if result["job_id"] is None:
            break


@pytest.mark.asyncio
async def test_retry_dead_letters_bulk_scoped_and_individual():
    async with _temp_db() as db:
        svc = MaintenanceService(db, max_attempts=1)
        await svc.ensure_schema()
        await _add_memory(db, "m1", content_hash="h1", project_id="projA")
        await _add_memory(db, "m2", content_hash="h2", project_id="projB")
        await svc.enqueue_project(
            project_id="projA", operations=["enrich", "improve"], force=False
        )
        await svc.enqueue_project(
            project_id="projB", operations=["enrich"], force=False
        )
        await _dead_letter_all(db, svc)
        counts = await svc.status_counts()
        assert counts["enrich"] == {"dead_letter": 2}
        assert counts["improve"] == {"dead_letter": 1}

        # Operation + project scope: only projA's enrich job requeued.
        retried = await svc.retry_dead_letters(operation="enrich", project_id="projA")
        assert retried == 1
        row = await db.fetchone(
            "SELECT status, attempts, next_attempt_at, last_error "
            "FROM maintenance_queue WHERE project_id = 'projA' "
            "AND operation = 'enrich'"
        )
        assert row["status"] == "pending"
        assert row["attempts"] == 0
        assert row["next_attempt_at"] == 0
        assert row["last_error"] is not None  # kept until the retry succeeds

        # Individual job retry.
        job = await db.fetchone(
            "SELECT id FROM maintenance_queue WHERE status = 'dead_letter' "
            "AND operation = 'improve'"
        )
        assert await svc.retry_dead_letters(job_id=str(job["id"])) == 1

        # Remaining dead_letter (projB enrich) via unscoped bulk retry.
        assert await svc.retry_dead_letters() == 1
        counts = await svc.status_counts()
        assert counts["enrich"] == {"pending": 2}
        assert counts["improve"] == {"pending": 1}


@pytest.mark.asyncio
async def test_retry_skips_dead_letter_with_live_duplicate():
    """Requeueing a dead_letter whose (memory, op) already has a live job would
    violate the live-uniqueness index — those rows are skipped."""
    async with _temp_db() as db:
        svc = MaintenanceService(db, max_attempts=1)
        await svc.ensure_schema()
        await _add_memory(db, "m1")
        await svc.enqueue_project(project_id="proj", operations=["enrich"], force=False)
        await _dead_letter_all(db, svc)
        # A fresh live job for the same (memory, operation).
        second = await svc.enqueue_project(
            project_id="proj", operations=["enrich"], force=True
        )
        assert second["enqueued"]["enrich"] == 1

        assert await svc.retry_dead_letters() == 0
        counts = await svc.status_counts()
        assert counts["enrich"] == {"dead_letter": 1, "pending": 1}


@pytest.mark.asyncio
async def test_bulk_retry_requeues_one_per_duplicate_group_without_error():
    """Two dead_letter rows can share (memory_id, operation) — e.g. re-enqueued
    with force=True after the first dead-lettered. A bulk retry flipping BOTH
    to pending in one UPDATE would itself violate idx_maintenance_queue_live
    (IntegrityError, whole retry rolled back, nothing requeued). Only the
    newest of each duplicate group should go live; the rest stay dead_letter."""
    async with _temp_db() as db:
        svc = MaintenanceService(db, max_attempts=1)
        await svc.ensure_schema()
        await _add_memory(db, "m1")
        await svc.enqueue_project(
            project_id="proj", operations=["improve"], force=False
        )
        await _dead_letter_all(db, svc)
        # Re-enqueue + dead-letter again → a second dead_letter row for the
        # SAME (memory_id, operation).
        await svc.enqueue_project(project_id="proj", operations=["improve"], force=True)
        await _dead_letter_all(db, svc)
        counts = await svc.status_counts()
        assert counts["improve"] == {"dead_letter": 2}

        retried = await svc.retry_dead_letters()  # must not raise IntegrityError

        assert retried == 1
        counts = await svc.status_counts()
        assert counts["improve"] == {"dead_letter": 1, "pending": 1}


@pytest.mark.asyncio
async def test_status_counts_project_scope():
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        await svc.ensure_schema()
        await _add_memory(db, "m1", content_hash="h1", project_id="projA")
        await _add_memory(db, "m2", content_hash="h2", project_id="projB")
        await svc.enqueue_project(
            project_id="projA", operations=["enrich"], force=False
        )
        await svc.enqueue_project(
            project_id="projB", operations=["enrich"], force=False
        )

        assert (await svc.status_counts())["enrich"] == {"pending": 2}
        assert (await svc.status_counts(project_id="projA"))["enrich"] == {"pending": 1}
        assert await svc.status_counts(project_id="nope") == {}


@pytest.mark.asyncio
async def test_reject_refine_proposal():
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        await svc.ensure_schema()
        await _add_memory(db, "m1", content_hash="h1")
        await svc.enqueue_project(
            project_id="proj", operations=["improve"], force=False
        )
        await svc.process_next(worker_id="w", chat_service=_StubChat(), settings=None)
        proposals = await svc.list_refine_proposals(project_id="proj")
        pid = proposals[0]["id"]

        assert await svc.reject_refine_proposal(pid) is True
        assert await svc.count_refine_proposals(project_id="proj") == 0
        # Second reject is a no-op (already resolved).
        assert await svc.reject_refine_proposal(pid) is False


# ── HTTP routes (retry + project-scoped status) ─────────────────────────────


def _maintenance_app(db):
    from fastapi import FastAPI

    from app.web.common.dependencies import get_database
    from app.web.dashboard.route_modules.maintenance import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_database] = lambda: db
    return app


def _client(app):
    from httpx import ASGITransport, AsyncClient

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_retry_endpoint_requeues_and_validates_operation():
    async with _temp_db() as db:
        svc = MaintenanceService(db, max_attempts=1)
        await svc.ensure_schema()
        await _add_memory(db, "m1")
        await svc.enqueue_project(project_id="proj", operations=["enrich"], force=False)
        await _dead_letter_all(db, svc)

        async with _client(_maintenance_app(db)) as client:
            r = await client.post("/api/maintenance/retry", json={"operation": "nope"})
            assert r.status_code == 400

            r = await client.post("/api/maintenance/retry", json={"project_id": "proj"})
            assert r.status_code == 200
            assert r.json() == {"retried": 1}
        assert (await svc.status_counts())["enrich"] == {"pending": 1}


@pytest.mark.asyncio
async def test_status_endpoint_project_scope_includes_reconcile():
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        await svc.ensure_schema()
        await _add_memory(db, "m1", content_hash="h1", project_id="projA")
        await _add_memory(db, "m2", content_hash="h2", project_id="projB")
        await svc.enqueue_project(
            project_id="projA", operations=["enrich"], force=False
        )
        await svc.enqueue_project(
            project_id="projB", operations=["enrich"], force=False
        )
        # A reconcile job for projA (schema v11 table created by migration).
        await db.execute(
            "INSERT INTO reconcile_queue (id, new_memory_id, old_memory_id, "
            "project_id, status, created_at, updated_at) "
            "VALUES ('r1', 'm1', 'm2', 'projA', 'pending', "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )

        async with _client(_maintenance_app(db)) as client:
            r = await client.get(
                "/api/maintenance/status", params={"project_id": "projA"}
            )
            assert r.status_code == 200
            queue = r.json()["queue"]
            assert queue["enrich"] == {"pending": 1}
            assert queue["reconcile"] == {"pending": 1}

            # No param → global counts, backward-compatible shape.
            r = await client.get("/api/maintenance/status")
            body = r.json()
            assert body["queue"]["enrich"] == {"pending": 2}
            assert "queue_by_project" not in body

            # by_project → one map covering every project (card progress poll).
            r = await client.get("/api/maintenance/status", params={"by_project": True})
            by_proj = r.json()["queue_by_project"]
            assert by_proj["projA"]["enrich"] == {"pending": 1}
            assert by_proj["projA"]["reconcile"] == {"pending": 1}
            assert by_proj["projB"] == {"enrich": {"pending": 1}}
