"""E scaffolding: abstract embeddings stored separately + a convergent, opt-in
re-embed batch. Uses a fake embedding service (no real model load — L1/L5)."""

import os
import tempfile
from contextlib import asynccontextmanager

import pytest

from app.core.database.base import Database
from app.core.services.abstract_embedding_store import AbstractEmbeddingStore
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
        for ext in ["", "-wal", "-shm"]:
            if os.path.exists(path + ext):
                os.unlink(path + ext)


async def _add_memory(db, mid, *, project_id="p"):
    await db.execute(
        """
        INSERT INTO memories (
            id, content, content_hash, project_id, category, source,
            embedding, tags, status, created_at, updated_at, content_bytes
        )
        VALUES (?, ?, ?, ?, 'decision', 'test', ?, '[]', 'canonical', ?, ?, ?)
        """,
        (mid, f"c {mid}", f"h-{mid}", project_id, b"1", "2026-01-01", "2026-01-01", 0),
    )


class _FakeEmb:
    model_name = "fake-embed"

    async def aembed(self, text, is_query=False):
        return [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_abstract_embedding_store_round_trip():
    async with _temp_db() as db:
        store = AbstractEmbeddingStore(db)
        await store.upsert(memory_id="m1", embedding=[0.5, -0.25, 1.0], model="x")
        got = await store.get("m1")
        assert got["model"] == "x"
        assert got["dim"] == 3
        assert got["embedding"] == pytest.approx([0.5, -0.25, 1.0], abs=1e-6)


@pytest.mark.asyncio
async def test_reembed_targets_abstract_without_embedding_and_converges():
    async with _temp_db() as db:
        svc = MaintenanceService(db)
        enr = EnrichmentStore(db)
        await _add_memory(db, "m1")
        await _add_memory(db, "m2")
        await enr.upsert(memory_id="m1", abstract="a summary")
        await enr.upsert(memory_id="m2", abstract="")  # empty → not a target

        res = await svc.reembed_abstracts(embedding_service=_FakeEmb())
        assert res["stored"] == 1

        aes = AbstractEmbeddingStore(db)
        assert await aes.count() == 1
        assert (await aes.get("m1"))["embedding"] == pytest.approx(
            [0.1, 0.2, 0.3], abs=1e-6
        )

        # Converges: m1 now has an embedding → no targets left.
        assert await svc.reembed_abstracts(embedding_service=_FakeEmb()) == {
            "stored": 0,
            "scanned": 0,
        }


def _worker(db, *, reembed=False):
    from app.core.services.relay import RelayService
    from app.core.services.relay_worker import RelayWorker

    return RelayWorker(
        service=RelayService(db),
        worker_id="w1",
        embedding_service=_FakeEmb(),
        maintenance_service=MaintenanceService(db),
        chat_settings=object(),
        abstract_reembed_enabled=reembed,
    )


@pytest.mark.asyncio
async def test_worker_abstract_reembed_sweep_stores_when_enabled():
    async with _temp_db() as db:
        await _add_memory(db, "m1")
        await EnrichmentStore(db).upsert(memory_id="m1", abstract="s")
        s = await _worker(db, reembed=True).run_once()
        assert s.get("abstract_reembed") == 1


@pytest.mark.asyncio
async def test_worker_abstract_reembed_noop_when_disabled():
    async with _temp_db() as db:
        await _add_memory(db, "m1")
        await EnrichmentStore(db).upsert(memory_id="m1", abstract="s")
        s = await _worker(db, reembed=False).run_once()
        assert "abstract_reembed" not in s
        assert await AbstractEmbeddingStore(db).count() == 0
