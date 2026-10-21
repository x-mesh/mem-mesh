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
from app.core.services.embedding_manager import EmbeddingManagerService


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


class _FakeEmbeddingService:
    def __init__(self, dimension=6, fail_on=None, wrong_dimension_on=None):
        self.model_name = "fake-new-model"
        self.dimension = dimension
        self.is_ready = True
        self.fail_on = fail_on
        self.wrong_dimension_on = wrong_dimension_on
        self.calls = []

    async def aembed(self, text):
        self.calls.append(text)
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("fake embedding failure")
        dimension = (
            2
            if self.wrong_dimension_on and self.wrong_dimension_on in text
            else self.dimension
        )
        return [float(index + 1) for index in range(dimension)]

    @staticmethod
    def to_bytes(vector):
        return struct.pack(f"{len(vector)}f", *vector)


async def _add_curated(db, result_id, memory_id, body, revision=1):
    run_id = f"run-{result_id}"
    candidate_id = f"candidate-{result_id}"
    proposal_id = f"proposal-{result_id}"
    now = "2026-06-15T00:00:00Z"
    await db.execute(
        "INSERT INTO reconciler_runs(id, project_id, status, dry_run, detector_version, policy_hash, model, prompt_version, budget_json, stats_json, created_at, updated_at) VALUES (?, 'p', 'completed', 0, 'test', 'policy', 'judge', 'prompt', '{}', '{}', ?, ?)",
        (run_id, now, now),
    )
    await db.execute(
        "INSERT INTO reconciler_candidates(id, run_id, project_id, group_key, memory_ids_json, input_policy_hash, created_at, updated_at) VALUES (?, ?, 'p', 'group', ?, 'policy', ?, ?)",
        (candidate_id, run_id, json.dumps([memory_id]), now, now),
    )
    await db.execute(
        "INSERT INTO reconciler_proposals(id, candidate_id, run_id, project_id, action, status, representative_memory_id, body, input_policy_hash, created_at, updated_at) VALUES (?, ?, ?, 'p', 'merge', 'applied', ?, ?, 'policy', ?, ?)",
        (proposal_id, candidate_id, run_id, memory_id, body, now, now),
    )
    await db.execute(
        "INSERT INTO curated_results(id, proposal_id, candidate_id, project_id, representative_memory_id, body, action, status, revision, input_policy_hash, created_at) VALUES (?, ?, ?, 'p', ?, ?, 'merge', 'active', ?, 'policy', ?)",
        (result_id, proposal_id, candidate_id, memory_id, body, revision, now),
    )
    await db.execute(
        "INSERT INTO curated_sources(result_id, memory_id, input_hash, source_role) VALUES (?, ?, ?, 'representative')",
        (result_id, memory_id, "input-hash"),
    )
    await db.execute(
        "INSERT INTO curated_results_fts(result_id, body, project_id) VALUES (?, ?, 'p')",
        (result_id, body),
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


async def test_manager_reembeds_curated_and_raw_slots_before_atomic_swap(db):
    await _add(db, "m1", EMBEDDING_TABLE_PRIMARY, (0.1, 0.2, 0.3, 0.4))
    await _add_curated(db, "cr1", "m1", "curated migration body")
    await db.execute(
        "INSERT INTO curated_results_vec_active(result_id, embedding) VALUES (?, ?)",
        ("cr1", json.dumps([0.1, 0.2, 0.3, 0.4])),
    )
    await db.set_embedding_metadata("embedding_model", "fake-old-model")
    await db.set_embedding_metadata("embedding_dimension", "4")
    await db.set_embedding_metadata("reconciler_embedding_model", "fake-old-model")
    await db.set_embedding_metadata("reconciler_embedding_dimension", "4")
    revision_before = await db.fetchone(
        "SELECT state_value FROM reconciler_state WHERE state_key = 'read_revision'"
    )

    observed = []
    service = _FakeEmbeddingService()
    original_aembed = service.aembed

    async def observe(text):
        if not observed:
            observed.append(
                (
                    await db.active_embedding_table(),
                    await db.fetchone(
                        "SELECT embedding FROM curated_results_vec_active WHERE result_id = 'cr1'"
                    ),
                )
            )
        return await original_aembed(text)

    service.aembed = observe
    manager = EmbeddingManagerService(db, service)
    manager._migration_progress["total"] = 1
    result = await manager._run_migration(batch_size=1)

    assert result["success"] is True
    assert observed[0][0] == EMBEDDING_TABLE_PRIMARY
    assert observed[0][1] is not None
    assert await db.active_embedding_table() == EMBEDDING_TABLE_SECONDARY
    assert (
        await db.fetchone(
            "SELECT name FROM sqlite_master WHERE name = ?", (EMBEDDING_TABLE_PRIMARY,)
        )
        is None
    )
    assert (
        await db.fetchone("SELECT COUNT(*) AS count FROM curated_results_vec_next")
    )["count"] == 0
    assert (
        await db.fetchone("SELECT COUNT(*) AS count FROM curated_results_vec_active")
    )["count"] == 1
    assert (
        len(
            (await db.fetchone("SELECT embedding FROM memories WHERE id = ?", ("m1",)))[
                "embedding"
            ]
        )
        == 24
    )
    assert await db.get_embedding_metadata("embedding_dimension") == "6"
    assert await db.get_embedding_metadata("reconciler_embedding_dimension") == "6"
    curated_sql = await db.fetchone(
        "SELECT sql FROM sqlite_master WHERE name = 'curated_results_vec_active'"
    )
    assert "USING VEC0" in curated_sql["sql"].upper()
    matches = await db.fetchall(
        "SELECT result_id, distance FROM curated_results_vec_active WHERE embedding MATCH ? ORDER BY distance LIMIT 1",
        (json.dumps([1, 2, 3, 4, 5, 6]),),
    )
    assert matches[0]["result_id"] == "cr1"
    assert matches[0]["distance"] == pytest.approx(0.0)
    revision_after = await db.fetchone(
        "SELECT state_value FROM reconciler_state WHERE state_key = 'read_revision'"
    )
    assert int(revision_after["state_value"]) > int(revision_before["state_value"])


@pytest.mark.parametrize("failure_kind", ["curated", "raw"])
async def test_manager_failure_restores_old_active_state(db, failure_kind):
    await _add(db, "m1", EMBEDDING_TABLE_PRIMARY, (0.1, 0.2, 0.3, 0.4))
    await _add_curated(db, "cr1", "m1", "curated migration body")
    old_curated = json.dumps([0.1, 0.2, 0.3, 0.4])
    await db.execute(
        "INSERT INTO curated_results_vec_active(result_id, embedding) VALUES (?, ?)",
        ("cr1", old_curated),
    )
    old_curated_value = (
        await db.fetchone(
            "SELECT embedding FROM curated_results_vec_active WHERE result_id = 'cr1'"
        )
    )["embedding"]
    await db.set_embedding_metadata("embedding_model", "fake-old-model")
    await db.set_embedding_metadata("embedding_dimension", "4")
    await db.set_embedding_metadata("reconciler_embedding_model", "fake-old-model")
    await db.set_embedding_metadata("reconciler_embedding_dimension", "4")
    old_memory = (
        await db.fetchone("SELECT embedding, updated_at FROM memories WHERE id = 'm1'")
    )["embedding"]

    service = _FakeEmbeddingService(
        fail_on="curated" if failure_kind == "curated" else None,
        wrong_dimension_on="content m1" if failure_kind == "raw" else None,
    )
    manager = EmbeddingManagerService(db, service)
    manager._migration_progress["total"] = 1
    with pytest.raises(Exception):
        await manager._run_migration(batch_size=1)

    assert await db.active_embedding_table() == EMBEDDING_TABLE_PRIMARY
    assert await db.migration_in_progress() is False
    assert (await db.fetchone("SELECT embedding FROM memories WHERE id = 'm1'"))[
        "embedding"
    ] == old_memory
    assert (
        await db.fetchone(
            "SELECT embedding FROM curated_results_vec_active WHERE result_id = 'cr1'"
        )
    )["embedding"] == old_curated_value
    assert await db.get_embedding_metadata("embedding_dimension") == "4"
    assert (
        await db.fetchone("SELECT COUNT(*) AS count FROM curated_results_vec_next")
    )["count"] == 0
