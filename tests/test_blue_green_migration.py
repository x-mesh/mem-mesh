"""Tests for blue-green embedding-table swap.

vec0 virtual tables can't be RENAMEd, so model migration re-embeds into the
inactive slot and flips the `active_embedding_table` pointer atomically. These
tests cover the swap mechanics and data integrity without loading a model
(vectors are written directly).
"""

import json
import struct

import pytest

from app.core.database.base import (
    EMBEDDING_TABLE_PRIMARY,
    EMBEDDING_TABLE_SECONDARY,
    Database,
)


def _vec(*xs):
    return struct.pack(f"{len(xs)}f", *xs)


@pytest.fixture
async def db():
    # :memory: keeps everything on the single writer connection (read pool off),
    # so direct writes are immediately visible to vector_search.
    database = Database(":memory:", embedding_dim=4)
    await database.connect()
    yield database
    await database.close()


async def _add(db, mid, table, vec):
    async with db.transaction():
        await db.add_memory(
            {
                "id": mid,
                "content": f"content {mid}",
                "content_hash": mid,
                "embedding": _vec(*vec),
                "created_at": "2026-06-15T00:00:00Z",
                "updated_at": "2026-06-15T00:00:00Z",
            }
        )
    await db.execute(
        f"INSERT INTO {table} (memory_id, embedding) VALUES (?, ?)",
        (mid, json.dumps(list(vec))),
    )


async def _create_slot(db, table):
    await db.execute(
        f"CREATE VIRTUAL TABLE {table} USING vec0("
        f"memory_id TEXT PRIMARY KEY, embedding FLOAT[4])"
    )


async def test_default_active_is_primary(db):
    assert await db.active_embedding_table() == EMBEDDING_TABLE_PRIMARY
    assert await db.inactive_embedding_table() == EMBEDDING_TABLE_SECONDARY


async def test_invalid_slot_rejected(db):
    with pytest.raises(ValueError):
        await db.set_active_embedding_table("memories")  # not a slot


async def test_swap_switches_search_to_green(db):
    """After the pointer flip, vector_search reads the green slot's data."""
    await _add(db, "blue1", EMBEDDING_TABLE_PRIMARY, (0.1, 0.2, 0.3, 0.4))
    await _create_slot(db, EMBEDDING_TABLE_SECONDARY)
    await _add(db, "green1", EMBEDDING_TABLE_SECONDARY, (0.9, 0.8, 0.7, 0.6))

    # Before swap: search hits blue slot
    before = await db.vector_search(_vec(0.1, 0.2, 0.3, 0.4), limit=5)
    assert "blue1" in {r["id"] for r in before}
    assert "green1" not in {r["id"] for r in before}

    # Atomic swap
    await db.set_active_embedding_table(EMBEDDING_TABLE_SECONDARY)

    after = await db.vector_search(_vec(0.9, 0.8, 0.7, 0.6), limit=5)
    assert "green1" in {r["id"] for r in after}
    assert "blue1" not in {r["id"] for r in after}


async def test_migration_flag_persists_in_db(db):
    assert await db.migration_in_progress() is False
    await db.set_migration_in_progress(True)
    assert await db.migration_in_progress() is True
    await db.set_migration_in_progress(False)
    assert await db.migration_in_progress() is False


async def test_dual_write_during_migration(db):
    """MemoryService writes to both slots while a migration is in progress."""
    from app.core.embeddings.service import EmbeddingService
    from app.core.services.memory import MemoryService

    es = EmbeddingService(model_name="nlpai-lab/KURE-v1", preload=False)
    ms = MemoryService(db, es)

    assert await ms._write_vector_tables() == [EMBEDDING_TABLE_PRIMARY]

    await _create_slot(db, EMBEDDING_TABLE_SECONDARY)
    await db.set_migration_in_progress(True)
    assert set(await ms._write_vector_tables()) == {
        EMBEDDING_TABLE_PRIMARY,
        EMBEDDING_TABLE_SECONDARY,
    }
    # Search stays on blue during migration
    assert await ms._resolve_vector_table() == EMBEDDING_TABLE_PRIMARY

    await db.set_active_embedding_table(EMBEDDING_TABLE_SECONDARY)
    await db.set_migration_in_progress(False)
    assert await ms._write_vector_tables() == [EMBEDDING_TABLE_SECONDARY]
