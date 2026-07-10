"""Enrichment now persists problem/resolution/lesson/confidence, enabling a
curation surface (miscategorized / low-confidence) and a lessons rollup."""

import json
import os
import tempfile
from contextlib import asynccontextmanager

import pytest

from app.core.database.base import Database
from app.core.services.enrich_store import EnrichmentStore
from app.core.services.recall import fetch_curation_candidates, fetch_lessons


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


async def _add_memory(db, mid, *, project_id="p", category="decision"):
    await db.execute(
        """
        INSERT INTO memories (
            id, content, content_hash, project_id, category, source,
            embedding, tags, status, created_at, updated_at, content_bytes
        )
        VALUES (?, ?, ?, ?, ?, 'test', ?, ?, 'canonical', ?, ?, ?)
        """,
        (
            mid,
            f"c {mid}",
            f"h-{mid}",
            project_id,
            category,
            b"1",
            json.dumps([]),
            "2026-01-01",
            "2026-01-01",
            0,
        ),
    )


@pytest.mark.asyncio
async def test_enrichment_persists_new_fields_round_trip():
    async with _temp_db() as db:
        store = EnrichmentStore(db)
        got = await store.upsert(
            memory_id="m1",
            title="T",
            abstract="A",
            problem="P",
            resolution="R",
            lesson="L",
            confidence=0.42,
        )
        assert got["problem"] == "P"
        assert got["resolution"] == "R"
        assert got["lesson"] == "L"
        assert got["confidence"] == 0.42


@pytest.mark.asyncio
async def test_ensure_schema_migrates_pre_existing_table():
    async with _temp_db() as db:
        # Simulate the original (pre-migration) schema without the new columns.
        await db.execute(
            "CREATE TABLE memory_enrichment (memory_id TEXT PRIMARY KEY, title TEXT, "
            "abstract TEXT, tags TEXT, display_kind TEXT, model TEXT, "
            "created_at TEXT NOT NULL)"
        )
        EnrichmentStore._schema_ready.discard(db)  # force ensure_schema to run
        await EnrichmentStore(db).ensure_schema()
        cols = {
            str(r["name"])
            for r in await db.fetchall("PRAGMA table_info(memory_enrichment)")
        }
        assert {"problem", "resolution", "lesson", "confidence"} <= cols


@pytest.mark.asyncio
async def test_curation_flags_miscategorized_and_low_confidence():
    async with _temp_db() as db:
        store = EnrichmentStore(db)
        await _add_memory(db, "m1", category="idea")
        await store.upsert(memory_id="m1", display_kind="bug", confidence=0.9)
        await _add_memory(db, "m2", category="decision")
        await store.upsert(memory_id="m2", display_kind="decision", confidence=0.2)
        await _add_memory(db, "m3", category="decision")
        await store.upsert(memory_id="m3", display_kind="decision", confidence=0.95)

        cands = {
            c["id"]: c for c in await fetch_curation_candidates(db, project_id="p")
        }
        assert "miscategorized" in cands["m1"]["reasons"]  # display_kind bug != idea
        assert "low_confidence" in cands["m2"]["reasons"]
        assert "m3" not in cands  # agrees + high confidence → clean


@pytest.mark.asyncio
async def test_curation_ignores_non_category_display_kinds():
    async with _temp_db() as db:
        store = EnrichmentStore(db)
        await _add_memory(db, "m1", category="decision")
        # 'note'/'reference' are display kinds but not categories → no false flag.
        await store.upsert(memory_id="m1", display_kind="note", confidence=0.9)
        cands = await fetch_curation_candidates(db, project_id="p")
        assert cands == []


@pytest.mark.asyncio
async def test_lessons_rollup_returns_only_non_empty():
    async with _temp_db() as db:
        store = EnrichmentStore(db)
        await _add_memory(db, "m1")
        await store.upsert(memory_id="m1", title="T1", lesson="validate input early")
        await _add_memory(db, "m2")
        await store.upsert(memory_id="m2", title="T2")  # no lesson

        lessons = await fetch_lessons(db, project_id="p")
        assert [x["id"] for x in lessons] == ["m1"]
        assert lessons[0]["lesson"] == "validate input early"
