"""Tag facet aggregation: enrichment + source topic tags with counts, scoped by
project, for facet navigation. Graceful when enrichment never ran."""

import os
import tempfile
from contextlib import asynccontextmanager

import pytest

from app.core.database.base import Database
from app.core.services.enrich_store import EnrichmentStore
from app.core.services.recall import fetch_tag_facets


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


async def _add_memory(db, mid, *, project_id="p", tags=None):
    import json

    await db.execute(
        """
        INSERT INTO memories (
            id, content, content_hash, project_id, category, source,
            embedding, tags, status, created_at, updated_at, content_bytes
        )
        VALUES (?, ?, ?, ?, 'decision', 'test', ?, ?, 'canonical', ?, ?, ?)
        """,
        (
            mid,
            f"content {mid}",
            f"h-{mid}",
            project_id,
            b"1",
            json.dumps(tags or []),
            "2026-01-01",
            "2026-01-01",
            0,
        ),
    )


@pytest.mark.asyncio
async def test_facets_count_source_tags_scoped_by_project():
    async with _temp_db() as db:
        await _add_memory(db, "m1", project_id="p", tags=["auth", "jwt"])
        await _add_memory(db, "m2", project_id="p", tags=["auth"])
        await _add_memory(db, "m3", project_id="other", tags=["auth", "misc"])

        facets = await fetch_tag_facets(db, project_id="p")
        counts = {f["tag"]: f["count"] for f in facets}
        assert counts["auth"] == 2  # m1, m2 (m3 is another project)
        assert counts["jwt"] == 1
        assert "misc" not in counts  # scoped out


@pytest.mark.asyncio
async def test_facets_merge_enrichment_tags_dedup_per_memory():
    async with _temp_db() as db:
        await _add_memory(db, "m1", tags=["auth"])
        store = EnrichmentStore(db)
        # Same tag in both source and enrichment → counts once for that memory.
        await store.upsert(memory_id="m1", title="T", abstract="A", tags=["auth"])
        # Enrichment-only topic tag on another memory.
        await _add_memory(db, "m2", tags=[])
        await store.upsert(memory_id="m2", title="T2", abstract="A2", tags=["vector"])

        facets = await fetch_tag_facets(db, project_id="p")
        counts = {f["tag"]: f["count"] for f in facets}
        assert counts["auth"] == 1  # deduped (source + enrichment on same memory)
        assert counts["vector"] == 1  # enrichment-only tag surfaces


@pytest.mark.asyncio
async def test_facets_graceful_without_enrichment_table():
    async with _temp_db() as db:
        # No EnrichmentStore.upsert → memory_enrichment table absent.
        await _add_memory(db, "m1", tags=["auth"])
        facets = await fetch_tag_facets(db, project_id="p")
        assert {f["tag"]: f["count"] for f in facets} == {"auth": 1}


@pytest.mark.asyncio
async def test_facets_sorted_by_count_desc():
    async with _temp_db() as db:
        await _add_memory(db, "m1", tags=["a", "b"])
        await _add_memory(db, "m2", tags=["a"])
        await _add_memory(db, "m3", tags=["a"])
        facets = await fetch_tag_facets(db)
        assert facets[0] == {"tag": "a", "count": 3}


# ── click-to-filter: tag filter matches source OR enrichment tags ────────────


@pytest.mark.asyncio
async def test_tag_filter_matches_enrichment_only_tag():
    async with _temp_db() as db:
        await _add_memory(db, "m1", tags=[])  # no source tags
        store = EnrichmentStore(db)
        await store.upsert(memory_id="m1", title="T", abstract="A", tags=["vector"])
        await _add_memory(db, "m2", tags=["other"])

        rows = await db.get_recent_memories(limit=10, filters={"tag": "vector"})
        assert {r["id"] for r in rows} == {"m1"}  # matched via enrichment tag
        assert await db.count_memories(filters={"tag": "vector"}) == 1


@pytest.mark.asyncio
async def test_tag_filter_still_matches_source_tag():
    async with _temp_db() as db:
        await _add_memory(db, "m1", tags=["auth"])
        store = EnrichmentStore(db)
        await store.upsert(memory_id="m1", title="T", abstract="A")  # table exists
        await _add_memory(db, "m2", tags=["other"])

        rows = await db.get_recent_memories(limit=10, filters={"tag": "auth"})
        assert {r["id"] for r in rows} == {"m1"}


@pytest.mark.asyncio
async def test_tag_filter_source_only_without_enrichment_table():
    async with _temp_db() as db:
        await _add_memory(db, "m1", tags=["auth"])  # no enrichment table at all
        rows = await db.get_recent_memories(limit=10, filters={"tag": "auth"})
        assert {r["id"] for r in rows} == {"m1"}
