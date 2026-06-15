"""Search-quality eval harness over the real hybrid pipeline.

Self-retrieval through UnifiedSearchService (vector + FTS + RRF + normalize +
optional rerank) — measures the *whole* search path, not just the embedding.
For each sampled memory we issue a short (keyword-ish) and a long (first
sentence) query and check the rank of that memory in the results.

Query types are split because the adaptive-hybrid lever mainly helps SHORT
queries (lexical/proper-noun), so we want to see that bucket move independently.

Paired by design: run before a change, run after, compare on the same gold
(same DB snapshot + same sampled ids). Use a COPY of prod (sqlite3 .backup)
so the harness's own search_metrics writes don't pollute production.

Usage: python scripts/eval_search_quality.py [/tmp/eval.db] [N] [label]
"""

import asyncio
import json
import re
import sqlite3
import sys

from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.unified_search import UnifiedSearchService

DB = sys.argv[1] if len(sys.argv) > 1 else "/tmp/eval.db"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 200
LABEL = sys.argv[3] if len(sys.argv) > 3 else "baseline"
LIMIT = 25


def short_query(content: str) -> str:
    # First ~8 tokens — emulates a terse keyword query (adaptive-hybrid target).
    return " ".join(content.replace("\n", " ").split()[:8])


def long_query(content: str) -> str:
    # First sentence — emulates a natural-language query.
    return re.split(r"[.!?\n]", content.strip())[0][:120]


def metrics(ranks):
    n = len(ranks)
    found = [r for r in ranks if r > 0]
    mrr = sum(1.0 / r for r in found) / n if n else 0.0
    return {
        "n": n,
        "found_rate": round(len(found) / n, 3) if n else 0,
        "MRR": round(mrr, 4),
        "R1": round(sum(1 for r in found if r <= 1) / n, 3) if n else 0,
        "R5": round(sum(1 for r in found if r <= 5) / n, 3) if n else 0,
        "R10": round(sum(1 for r in found if r <= 10) / n, 3) if n else 0,
    }


async def main():
    db = Database(DB, embedding_dim=1024)
    await db.connect()
    model = await db.get_embedding_metadata("embedding_model") or "nlpai-lab/KURE-v1"
    es = EmbeddingService(model_name=model, preload=True)
    svc = UnifiedSearchService(
        db=db,
        embedding_service=es,
        enable_quality_features=True,
        enable_korean_optimization=True,
        enable_noise_filter=True,
        enable_score_normalization=True,
        score_normalization_method="sigmoid",
    )

    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT id, content FROM memories "
        "WHERE content IS NOT NULL AND LENGTH(content) BETWEEN 200 AND 3000 "
        "ORDER BY id LIMIT ?",
        (N,),
    ).fetchall()
    c.close()

    buckets = {"short": [], "long": []}
    for r in rows:
        gid, content = r["id"], r["content"]
        for qt, q in (("short", short_query(content)), ("long", long_query(content))):
            if not q.strip():
                continue
            resp = await svc.search(query=q, limit=LIMIT, search_mode="hybrid")
            ids = [x.id for x in resp.results]
            buckets[qt].append(ids.index(gid) + 1 if gid in ids else 0)

    out = {
        "label": LABEL,
        "model": model,
        "n_memories": len(rows),
        "short": metrics(buckets["short"]),
        "long": metrics(buckets["long"]),
        "overall": metrics(buckets["short"] + buckets["long"]),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    with open(f"/tmp/eval_{LABEL}.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
