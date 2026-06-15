"""Compare two embedding models on the local mem-mesh corpus.

KURE-v1 (current) vs arctic-ko (candidate). Two evaluations:

1. split-half self-retrieval (quantitative, auto-gold): each memory is split
   into first-half (query) and second-half (doc). The corpus is all second
   halves; we measure whether each query retrieves its own second half.
   Reports MRR / R@1 / R@5 / R@10 — a proxy for semantic-consistency retrieval
   that needs no human labels and ranks the two models fairly.

2. natural-language queries (qualitative): a handful of realistic queries run
   over the full memory contents, top-3 shown side by side.

Read-only. Applies each model's correct prefix convention (arctic: 'query: '
on queries only; KURE: none).

Usage: python scripts/compare_embeddings.py [data/prod_memories.db] [N]
"""

import sqlite3
import sys
import time

import numpy as np
from sentence_transformers import SentenceTransformer

DB = sys.argv[1] if len(sys.argv) > 1 else "data/prod_memories.db"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 500

MODELS = {
    "KURE-v1": ("nlpai-lab/KURE-v1", False),
    "arctic-ko": ("dragonkue/snowflake-arctic-embed-l-v2.0-ko", True),
}

QUAL_QUERIES = [
    "데이터베이스 커넥션 풀 동시성 개선",
    "임베딩 모델 선택과 성능 비교",
    "비동기 처리에서 이벤트 루프 블로킹",
    "검색 tail latency 병목 원인",
    "핀 동시성 race condition 버그",
]


def prep(text, is_query, is_arctic):
    """arctic: 'query: ' on queries only. KURE/others: raw text."""
    if is_arctic and is_query:
        return "query: " + text
    return text


def split_half(text):
    mid = len(text) // 2
    sp = text.find(" ", mid)
    if sp == -1:
        sp = mid
    return text[:sp].strip(), text[sp:].strip()


def main():
    c = sqlite3.connect(DB)
    rows = c.execute(
        "SELECT id, content FROM memories "
        "WHERE content IS NOT NULL AND LENGTH(content) BETWEEN 300 AND 4000 "
        "ORDER BY id LIMIT ?",
        (N,),
    ).fetchall()
    c.close()

    contents = [r[1] for r in rows]
    pairs = [split_half(c) for c in contents]
    queries = [p[0] for p in pairs]
    docs = [p[1] for p in pairs]
    print(f"DB={DB}  corpus={len(contents)} memories\n")

    qual_top = {}  # label -> list of (query, [top3 snippets])
    for label, (name, is_arctic) in MODELS.items():
        t = time.perf_counter()
        model = SentenceTransformer(name)

        # split-half self-retrieval
        d_emb = model.encode(
            [prep(d, False, is_arctic) for d in docs],
            normalize_embeddings=True,
            batch_size=32,
        )
        q_emb = model.encode(
            [prep(q, True, is_arctic) for q in queries],
            normalize_embeddings=True,
            batch_size=32,
        )
        sims = q_emb @ d_emb.T
        ranks = np.empty(len(queries), dtype=int)
        for i in range(len(queries)):
            order = np.argsort(-sims[i])
            ranks[i] = int(np.where(order == i)[0][0]) + 1
        mrr = float(np.mean(1.0 / ranks))
        r1 = float(np.mean(ranks <= 1))
        r5 = float(np.mean(ranks <= 5))
        r10 = float(np.mean(ranks <= 10))

        # qualitative over full contents
        full_emb = model.encode(
            [prep(t, False, is_arctic) for t in contents],
            normalize_embeddings=True,
            batch_size=32,
        )
        qq = model.encode(
            [prep(q, True, is_arctic) for q in QUAL_QUERIES],
            normalize_embeddings=True,
            batch_size=32,
        )
        qsims = qq @ full_emb.T
        tops = []
        for i, q in enumerate(QUAL_QUERIES):
            top = np.argsort(-qsims[i])[:3]
            tops.append((q, [(float(qsims[i][j]), contents[j][:70]) for j in top]))
        qual_top[label] = tops

        elapsed = time.perf_counter() - t
        print(
            f"[{label:10s}] MRR={mrr:.4f}  R@1={r1:.3f}  R@5={r5:.3f}  "
            f"R@10={r10:.3f}   ({elapsed:.0f}s)"
        )

    print("\n=== Qualitative top-3 (natural-language queries) ===")
    for i, q in enumerate(QUAL_QUERIES):
        print(f"\nQ: {q}")
        for label in MODELS:
            print(f"  [{label}]")
            for score, snippet in qual_top[label][i][1]:
                clean = snippet.replace("\n", " ")
                print(f"     {score:.3f}  {clean}")


if __name__ == "__main__":
    main()
