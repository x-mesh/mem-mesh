"""Targeted repair for curated vectors written without an embedding service."""

import struct

import pytest

from app.core.services.memory_reconciler import MemoryReconcilerService
from scripts.reindex_curated_vectors import inspect_active, reindex_active
from tests.test_memory_reconciler import MergeProvider, _add_memory, _FakeEmbedding


@pytest.mark.asyncio
async def test_reindex_curated_vectors_dry_run_and_apply(temp_db):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    await temp_db.set_embedding_metadata("embedding_model", embedding.model_name)
    await temp_db.set_embedding_metadata(
        "embedding_dimension", str(temp_db.embedding_dim)
    )
    service = MemoryReconcilerService(temp_db, embedding_service=embedding)
    await service.create_run("reconciler-project", dry_run=False)
    activated = await service.process_next("worker-1", MergeProvider())
    result_id = activated["result_id"]
    old_vector = struct.pack(
        f"{temp_db.embedding_dim}f", *([0.0] * temp_db.embedding_dim)
    )
    await temp_db.execute(
        "UPDATE curated_results_vec_fallback SET embedding = ? WHERE result_id = ?",
        (old_vector, result_id),
    )
    await temp_db.execute(
        "DELETE FROM embedding_metadata WHERE key IN ('reconciler_embedding_model', 'reconciler_embedding_dimension')"
    )

    checked = await inspect_active(temp_db, "reconciler-project")
    preview = await reindex_active(
        temp_db, embedding, "reconciler-project", apply=False
    )
    unchanged = await temp_db.fetchone(
        "SELECT embedding FROM curated_results_vec_fallback WHERE result_id = ?",
        (result_id,),
    )

    assert checked["active_in_project"] == 1
    assert checked["curated_model"] is None
    assert preview["reindexed"] == 1
    assert preview["applied"] is False
    assert bytes(unchanged["embedding"]) == old_vector

    applied = await reindex_active(temp_db, embedding, "reconciler-project", apply=True)
    repaired = await temp_db.fetchone(
        "SELECT embedding FROM curated_results_vec_fallback WHERE result_id = ?",
        (result_id,),
    )

    assert applied["applied"] is True
    assert applied["curated_model"] == embedding.model_name
    assert bytes(repaired["embedding"]) == embedding.to_bytes(
        [0.25] * temp_db.embedding_dim
    )
    assert (
        await temp_db.get_embedding_metadata("reconciler_embedding_model")
    ) == embedding.model_name


@pytest.mark.asyncio
async def test_reindex_rejects_wrong_model(temp_db):
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    await temp_db.set_embedding_metadata("embedding_model", "another-model")
    await temp_db.set_embedding_metadata(
        "embedding_dimension", str(temp_db.embedding_dim)
    )

    with pytest.raises(ValueError, match="differs from the canonical index"):
        await reindex_active(temp_db, embedding, "reconciler-project", apply=True)


@pytest.mark.asyncio
async def test_reindex_restores_vec0_after_legacy_blob_table_conversion(
    temp_db, monkeypatch
):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    await temp_db.set_embedding_metadata("embedding_model", embedding.model_name)
    await temp_db.set_embedding_metadata(
        "embedding_dimension", str(temp_db.embedding_dim)
    )
    service = MemoryReconcilerService(temp_db, embedding_service=embedding)
    await service.create_run("reconciler-project", dry_run=False)
    result = await service.process_next("worker-1", MergeProvider())
    await temp_db.execute("DROP TABLE curated_results_vec_active")
    await temp_db.execute(
        "CREATE TABLE curated_results_vec_active(result_id TEXT PRIMARY KEY, embedding BLOB NOT NULL)"
    )
    await temp_db.execute(
        "INSERT INTO curated_results_vec_active(result_id, embedding) VALUES (?, ?)",
        (result["result_id"], embedding.to_bytes([0.25] * temp_db.embedding_dim)),
    )

    assert (await service.validate_result(result["result_id"]))["valid"] is False
    preview = await reindex_active(
        temp_db, embedding, "reconciler-project", apply=False
    )
    assert preview["upgrade_to_vec0"] is True
    assert (
        "USING VEC0"
        not in (
            await temp_db.fetchone(
                "SELECT sql FROM sqlite_master WHERE name = 'curated_results_vec_active'"
            )
        )["sql"].upper()
    )
    original_execute = temp_db.execute

    async def fail_insert(query, params=()):
        if query.startswith("INSERT INTO curated_results_vec_active"):
            raise RuntimeError("vector insertion failed")
        return await original_execute(query, params)

    with monkeypatch.context() as patch:
        patch.setattr(temp_db, "execute", fail_insert)
        with pytest.raises(RuntimeError, match="vector insertion failed"):
            await reindex_active(temp_db, embedding, "reconciler-project", apply=True)
    assert (
        "USING VEC0"
        not in (
            await temp_db.fetchone(
                "SELECT sql FROM sqlite_master WHERE name = 'curated_results_vec_active'"
            )
        )["sql"].upper()
    )
    assert (
        await temp_db.fetchone(
            "SELECT status FROM curated_results WHERE id = ?", (result["result_id"],)
        )
    )["status"] == "stale"
    assert (
        await temp_db.fetchone(
            "SELECT id FROM reconciler_receipts WHERE operation = 'index_repair'"
        )
        is None
    )
    repaired = await reindex_active(
        temp_db, embedding, "reconciler-project", apply=True
    )
    assert repaired["upgrade_to_vec0"] is True
    assert (await service.validate_result(result["result_id"]))["valid"] is True
    matches = await service.effective_read.search_curated(
        "unrelated query vocabulary", filters={"project_id": "reconciler-project"}
    )
    assert [item.id for item in matches] == [result["result_id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_source", [False, True])
async def test_reindex_repairs_only_input_valid_index_failures(temp_db, changed_source):
    await _add_memory(temp_db, "m1", "The same task has a first supported form.")
    await _add_memory(temp_db, "m2", "The same task has a second supported form.")
    embedding = _FakeEmbedding(temp_db.embedding_dim)
    await temp_db.set_embedding_metadata("embedding_model", embedding.model_name)
    await temp_db.set_embedding_metadata(
        "embedding_dimension", str(temp_db.embedding_dim)
    )
    service = MemoryReconcilerService(temp_db, embedding_service=embedding)
    await service.create_run("reconciler-project", dry_run=False)
    result = await service.process_next("worker-1", MergeProvider())
    result_id = result["result_id"]
    await temp_db.execute(
        "DELETE FROM curated_results_fts WHERE result_id = ?", (result_id,)
    )
    invalid = await service.validate_result(result_id)
    assert invalid["status"] == "stale"
    assert (await inspect_active(temp_db, "reconciler-project"))[
        "repairable_in_project"
    ] == 1

    if changed_source:
        await temp_db.execute(
            "UPDATE memories SET content = 'Changed source' WHERE id = 'm1'"
        )
        with pytest.raises(ValueError, match="canonical input changed"):
            await reindex_active(temp_db, embedding, "reconciler-project", apply=True)
        assert (
            await temp_db.fetchone(
                "SELECT status FROM curated_results WHERE id = ?", (result_id,)
            )
        )["status"] == "stale"
        assert (
            await temp_db.fetchone(
                "SELECT id FROM reconciler_receipts WHERE operation = 'index_repair'"
            )
            is None
        )
    else:
        originals = [
            dict(row)
            for row in await temp_db.fetchall("SELECT * FROM memories ORDER BY id")
        ]
        dry_run = await reindex_active(
            temp_db, embedding, "reconciler-project", apply=False
        )
        assert dry_run["applied"] is False
        assert (
            await temp_db.fetchone(
                "SELECT status FROM curated_results WHERE id = ?", (result_id,)
            )
        )["status"] == "stale"
        repaired = await reindex_active(
            temp_db, embedding, "reconciler-project", apply=True
        )
        assert repaired["repaired"] == 1
        assert (await service.validate_result(result_id))["valid"] is True
        semantic = await service.effective_read.search_curated(
            "unrelated query vocabulary", filters={"project_id": "reconciler-project"}
        )
        assert [item.id for item in semantic] == [result_id]
        assert (
            await temp_db.fetchone(
                "SELECT revision FROM curated_results WHERE id = ?", (result_id,)
            )
        )["revision"] == 3
        assert [
            dict(row)
            for row in await temp_db.fetchall("SELECT * FROM memories ORDER BY id")
        ] == originals
        assert (
            await temp_db.fetchone(
                "SELECT COUNT(*) AS n FROM reconciler_receipts WHERE operation = 'index_repair'"
            )
        )["n"] == 1
