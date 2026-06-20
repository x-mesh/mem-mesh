#!/usr/bin/env python3
"""
One-off OFFLINE re-embedding migration (run on the Mac with MPS).

Takes a snapshot of the production DB, re-embeds every memory with the target
model (arctic-ko) on MPS, rebuilds the vec0 index into a single active table,
normalizes the A/B migration metadata, and validates the result.

Why offline + Mac: the prod box has no GPU, so the in-app A/B migration crawled
(2% in 17h). The Mac (MPS) does the full 16.6k re-embed in minutes.

Design notes:
  - active table is normalized to `memory_embeddings` (primary slot); the `_b`
    slot is dropped. Both are valid slots in EMBEDDING_TABLE_SLOTS.
  - arctic uses asymmetric prefixing: passages (stored docs) get NO prefix,
    so we embed with is_query=False.
  - memories.updated_at is PRESERVED (we only recompute the embedding, the
    memory content did not change).
  - vec0 stores the same float32 bytes as memories.embedding (consistent).

Usage:
  python scripts/_migrate_arctic_offline.py --db data/migrate_work.db \
      --model dragonkue/snowflake-arctic-embed-l-v2.0-ko \
      [--limit N] [--batch-size 256] [--truncate 2000] [--dry-run]
"""
import argparse
import sqlite3
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import sqlite_vec

sys.path.insert(0, str(Path(__file__).parent.parent))

ACTIVE_TABLE = "memory_embeddings"      # normalize active slot to primary
DROP_TABLES = ("memory_embeddings_b",)  # discard the stale green slot


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_bytes(vec) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def load_model(model_name: str):
    """Load EmbeddingService and move to MPS if available. Returns (svc, dim, device)."""
    import torch
    from app.core.embeddings.service import EmbeddingService

    svc = EmbeddingService(model_name, preload=True)
    device = "cpu"
    if torch.backends.mps.is_available():
        svc.model = svc.model.to("mps")
        device = "mps"
    elif torch.cuda.is_available():
        svc.model = svc.model.to("cuda")
        device = "cuda"
    return svc, svc.dimension, device


def recreate_active_table(conn: sqlite3.Connection, dim: int) -> None:
    for t in (ACTIVE_TABLE, *DROP_TABLES):
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.execute(
        f"CREATE VIRTUAL TABLE {ACTIVE_TABLE} USING vec0("
        f"memory_id TEXT PRIMARY KEY, embedding FLOAT[{dim}])"
    )
    conn.commit()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO embedding_metadata(key,value,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, now_iso()),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--model", default="dragonkue/snowflake-arctic-embed-l-v2.0-ko")
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--truncate", type=int, default=2000)
    ap.add_argument("--limit", type=int, default=0, help="0 = all (smoke test with small N)")
    ap.add_argument("--dry-run", action="store_true", help="embed but do not write")
    args = ap.parse_args()

    db_path = args.db
    print(f"[1/5] Loading model {args.model} ...")
    t0 = time.perf_counter()
    svc, dim, device = load_model(args.model)
    print(f"      model ready: dim={dim}, device={device}, {time.perf_counter()-t0:.1f}s")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)

    total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    if args.limit:
        total = min(total, args.limit)
    print(f"[2/5] memories to process: {total} (truncate={args.truncate}, batch={args.batch_size})")

    if not args.dry_run:
        print(f"[3/5] Rebuilding active vec0 table '{ACTIVE_TABLE}' (dim={dim}), dropping {DROP_TABLES} ...")
        recreate_active_table(conn, dim)
    else:
        print("[3/5] DRY-RUN: skip table rebuild")

    print("[4/5] Re-embedding ...")
    processed, failed = 0, 0
    t_embed = 0.0
    limit_clause = f"LIMIT {args.limit}" if args.limit else ""
    rows = conn.execute(
        f"SELECT id, content FROM memories ORDER BY created_at {limit_clause}"
    ).fetchall()

    for i in range(0, len(rows), args.batch_size):
        chunk = rows[i : i + args.batch_size]
        ids = [r["id"] for r in chunk]
        texts = [(r["content"] or "")[: args.truncate] for r in chunk]
        te = time.perf_counter()
        try:
            vecs = svc.embed_batch(texts, is_query=False)
        except Exception as e:
            failed += len(chunk)
            print(f"      batch {i//args.batch_size} FAILED: {e}")
            continue
        t_embed += time.perf_counter() - te

        if not args.dry_run:
            for mid, vec in zip(ids, vecs):
                eb = to_bytes(vec)
                # preserve updated_at: only touch the embedding column
                conn.execute("UPDATE memories SET embedding=? WHERE id=?", (eb, mid))
                conn.execute(
                    f"INSERT INTO {ACTIVE_TABLE}(memory_id, embedding) VALUES(?,?)",
                    (mid, eb),
                )
            conn.commit()
        processed += len(chunk)
        pct = processed / total * 100
        rate = processed / t_embed if t_embed else 0
        eta = (total - processed) / rate if rate else 0
        print(f"      {processed}/{total} ({pct:.0f}%) | {rate:.0f} emb/s | ETA {eta:.0f}s", flush=True)

    if not args.dry_run:
        print("[5/5] Updating metadata ...")
        set_meta(conn, "embedding_model", args.model)
        set_meta(conn, "embedding_dimension", str(dim))
        set_meta(conn, "active_embedding_table", ACTIVE_TABLE)
        set_meta(conn, "migration_in_progress", "0")
        set_meta(conn, "target_embedding_model", "")
        set_meta(conn, "target_embedding_dimension", "")
        set_meta(conn, "last_migration", now_iso())
        conn.commit()
        vcount = conn.execute(f"SELECT COUNT(*) FROM {ACTIVE_TABLE}").fetchone()[0]
        mcount = conn.execute("SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL").fetchone()[0]
        print(f"      vec0={vcount}, memories.embedding={mcount}, processed={processed}, failed={failed}")
        print("      metadata:")
        for r in conn.execute("SELECT key,value FROM embedding_metadata ORDER BY key"):
            print(f"        {r['key']} = {r['value']}")
    else:
        print(f"[5/5] DRY-RUN done. processed={processed} failed={failed} embed_time={t_embed:.1f}s")

    conn.close()
    print(f"DONE in {time.perf_counter()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
