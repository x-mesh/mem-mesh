"""Rebuild curated indexes and repair index-invalid results from stored bodies."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from typing import Any
from uuid import uuid4

from app.core.config import get_settings
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.effective_read import EffectiveReadService
from app.core.services.memory_reconciler import MemoryReconcilerService

_REPAIRABLE = "(status = 'active' OR (status = 'stale' AND stale_reason = 'curated index validation failed'))"


async def _checked_sources(db: Database, result: dict) -> dict[str, str]:
    reader = EffectiveReadService(db)
    candidate = await db.fetchone(
        "SELECT memory_ids_json FROM reconciler_candidates WHERE id = ?",
        (result["candidate_id"],),
    )
    sources = await reader._source_rows(result["id"])
    expected = json.loads(candidate["memory_ids_json"]) if candidate else []
    if (
        not sources
        or {source["memory_id"] for source in sources} != set(expected)
        or result["representative_memory_id"] not in expected
    ):
        raise ValueError("curated source provenance changed before index repair")
    versions = {}
    for source in sources:
        current = await reader.current_input_hash(source["memory_id"])
        if (
            source.get("project_id") != result["project_id"]
            or current != source["input_hash"]
        ):
            raise ValueError("canonical input changed before index repair")
        versions[source["memory_id"]] = current
    return versions


async def inspect_active(db: Database, project_id: str) -> dict[str, Any]:
    rows = await db.fetchall(
        "SELECT id, project_id, revision, body FROM curated_results "
        "WHERE status = 'active' ORDER BY id"
    )
    target = [dict(row) for row in rows if row["project_id"] == project_id]
    repairable = await db.fetchall(
        "SELECT project_id FROM curated_results WHERE status = 'stale' AND stale_reason = 'curated index validation failed'"
    )
    return {
        "project_id": project_id,
        "active_total": len(rows),
        "active_in_project": len(target),
        "repairable_total": len(repairable),
        "repairable_in_project": sum(
            row["project_id"] == project_id for row in repairable
        ),
        "embedding_model": await db.get_embedding_metadata("embedding_model"),
        "embedding_dimension": await db.get_embedding_metadata("embedding_dimension"),
        "curated_model": await db.get_embedding_metadata("reconciler_embedding_model"),
        "curated_dimension": await db.get_embedding_metadata(
            "reconciler_embedding_dimension"
        ),
    }


async def reindex_active(
    db: Database, embedding_service: Any, project_id: str, *, apply: bool
) -> dict[str, Any]:
    info = await inspect_active(db, project_id)
    if await db.migration_in_progress():
        raise ValueError("embedding migration is in progress")
    if (
        info["active_total"] + info["repairable_total"]
        != info["active_in_project"] + info["repairable_in_project"]
    ):
        raise ValueError(
            "project does not include every active or repairable curated result"
        )
    model = str(getattr(embedding_service, "model_name", "") or "")
    dimension = int(getattr(embedding_service, "dimension", 0))
    if not model or model != info["embedding_model"]:
        raise ValueError("embedding model differs from the canonical index")
    if (
        dimension != int(info["embedding_dimension"] or 0)
        or dimension != db.embedding_dim
    ):
        raise ValueError("embedding dimension differs from the canonical index")
    if info["curated_model"] and info["curated_model"] != model:
        raise ValueError("curated model differs; use the embedding model migration")

    rows = await db.fetchall(
        "SELECT * FROM curated_results "
        f"WHERE {_REPAIRABLE} AND project_id = ? ORDER BY id",
        (project_id,),
    )
    active_table = await db.fetchone(
        "SELECT sql FROM sqlite_master WHERE name = 'curated_results_vec_active'"
    )
    if not active_table:
        raise ValueError("curated active vector table is missing")
    use_vec = "USING VEC0" in str(active_table["sql"] or "").upper()
    canonical_table = await db.active_embedding_table()
    canonical_schema = await db.fetchone(
        "SELECT sql FROM sqlite_master WHERE name = ?", (canonical_table,)
    )
    upgrade_to_vec = bool(
        not use_vec
        and canonical_schema
        and "USING VEC0" in str(canonical_schema["sql"] or "").upper()
    )
    use_vec = use_vec or upgrade_to_vec
    prepared = []
    for row in rows:
        result = dict(row)
        result["source_versions"] = await _checked_sources(db, result)
        vector = await embedding_service.aembed(str(row["body"] or ""))
        if len(vector) != dimension or not all(
            math.isfinite(float(value)) for value in vector
        ):
            raise ValueError(f"curated result {row['id']} has an invalid dimension")
        vector_bytes = embedding_service.to_bytes(vector)
        if len(vector_bytes) != dimension * 4:
            raise ValueError(f"curated result {row['id']} has invalid embedding bytes")
        prepared.append({**result, "vector": vector, "vector_bytes": vector_bytes})

    if apply:
        async with db.transaction():
            if await db.migration_in_progress():
                raise ValueError("embedding migration is in progress")
            if await db.get_embedding_metadata("embedding_model") != model or str(
                await db.get_embedding_metadata("embedding_dimension")
            ) != str(dimension):
                raise ValueError("embedding model changed during index repair")
            current = await db.fetchall(
                "SELECT id, revision, status, body FROM curated_results "
                f"WHERE {_REPAIRABLE} ORDER BY id"
            )
            if [
                (str(row["id"]), int(row["revision"]), row["status"], row["body"])
                for row in current
            ] != [
                (row["id"], row["revision"], row["status"], row["body"])
                for row in prepared
            ]:
                raise ValueError("active curated results changed during reindex")
            if upgrade_to_vec:
                await db.execute("DROP TABLE curated_results_vec_active")
                await db.execute(
                    f"CREATE VIRTUAL TABLE curated_results_vec_active USING vec0(result_id TEXT PRIMARY KEY, embedding FLOAT[{dimension}])"
                )
            for result in prepared:
                if await _checked_sources(db, result) != result["source_versions"]:
                    raise ValueError("canonical input changed during index repair")
                result_id = result["id"]
                await db.execute(
                    "DELETE FROM curated_results_vec_fallback WHERE result_id = ?",
                    (result_id,),
                )
                await db.execute(
                    "INSERT INTO curated_results_vec_fallback(result_id, embedding) VALUES (?, ?)",
                    (result_id, result["vector_bytes"]),
                )
                await db.execute(
                    "DELETE FROM curated_results_vec_active WHERE result_id = ?",
                    (result_id,),
                )
                await db.execute(
                    "INSERT INTO curated_results_vec_active(result_id, embedding) VALUES (?, ?)",
                    (
                        result_id,
                        (
                            json.dumps(result["vector"])
                            if use_vec
                            else result["vector_bytes"]
                        ),
                    ),
                )
                await db.execute(
                    "DELETE FROM curated_results_fts WHERE result_id = ?", (result_id,)
                )
                await db.execute(
                    "INSERT INTO curated_results_fts(result_id, body, project_id) VALUES (?, ?, ?)",
                    (result_id, result["body"], result["project_id"]),
                )
            for key, value in (
                ("reconciler_embedding_model", model),
                ("reconciler_embedding_dimension", str(dimension)),
            ):
                await db.execute(
                    "INSERT INTO embedding_metadata(key, value, updated_at) "
                    "VALUES (?, ?, datetime('now')) ON CONFLICT(key) DO UPDATE SET "
                    "value = excluded.value, updated_at = excluded.updated_at",
                    (key, value),
                )
            validator = MemoryReconcilerService(db, embedding_service=embedding_service)
            for result in prepared:
                errors = await validator._index_errors(
                    result["id"], result["body"], result["project_id"]
                )
                if errors:
                    raise ValueError("; ".join(errors))
                if result["status"] == "stale":
                    await db.execute(
                        "UPDATE curated_results SET status = 'active', revision = revision + 1, stale_at = NULL, stale_reason = NULL WHERE id = ?",
                        (result["id"],),
                    )
                    await db.execute(
                        "INSERT INTO reconciler_receipts(id, result_id, operation, from_status, to_status, revision, actor, details_json, created_at) VALUES (?, ?, 'index_repair', 'stale', 'active', ?, 'operator', '{}', datetime('now'))",
                        (
                            "rrc_" + uuid4().hex,
                            result["id"],
                            int(result["revision"]) + 1,
                        ),
                    )
            await EffectiveReadService(db).bump_read_revision("curated_reindex")

    current_info = await inspect_active(db, project_id) if apply else info
    return {
        **current_info,
        "reindexed": len(prepared),
        "upgrade_to_vec0": upgrade_to_vec,
        "repaired": sum(row["status"] == "stale" for row in prepared) if apply else 0,
        "applied": apply,
    }


async def _main(project_id: str, mode: str) -> dict[str, Any]:
    settings = get_settings()
    db = Database(settings.database_path, embedding_dim=settings.embedding_dim)
    await db.connect()
    try:
        if mode == "check-only":
            return await inspect_active(db, project_id)
        embedding_service = EmbeddingService(
            model_name=settings.embedding_model, preload=False, defer_loading=False
        )
        return await reindex_active(
            db, embedding_service, project_id, apply=mode == "apply"
        )
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    selected = (
        "check-only" if args.check_only else "dry-run" if args.dry_run else "apply"
    )
    print(json.dumps(asyncio.run(_main(args.project, selected)), ensure_ascii=False))


if __name__ == "__main__":
    main()
