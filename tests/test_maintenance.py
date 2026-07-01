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
