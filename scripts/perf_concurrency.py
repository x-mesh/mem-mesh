"""Concurrency load probe for the C3 read pool (before/after read tail).

Compares a serialized pool (size=1, ~the old single-lock design) against the
real pool (size=N) on a prod DB snapshot. Read-only; never writes.

Two scenarios:
  1. head-of-line: one slow query in flight while many light reads arrive.
     This is the prod tail-latency mechanism — under a single lock the light
     reads queue behind the slow one (crowded p95 spiked to 2377ms, max 30s).
  2. uniform burst: N concurrent vector searches. Pure CPU-bound work, so the
     pool gives no throughput win here (and costs CPU contention) — included
     to show the pool's value is head-of-line elimination, NOT raw throughput.

Usage: python scripts/perf_concurrency.py [data/prod_memories.db]
"""

import asyncio
import sys
import time

from app.core.database.connection import DatabaseConnection
from app.core.database.read_pool import ReadPool

DB = sys.argv[1] if len(sys.argv) > 1 else "data/prod_memories.db"

# Real base.py vector_search hot query (CPU/IO heavy).
VEC_SQL = (
    "SELECT m.id, ve.distance FROM memories m JOIN ("
    "SELECT memory_id, distance FROM memory_embeddings "
    "WHERE embedding MATCH ? ORDER BY distance LIMIT ?) ve "
    "ON m.id = ve.memory_id ORDER BY ve.distance LIMIT 25"
)
# A long read that holds a connection (emulates a slow/IO-bound query).
SLOW_SQL = (
    "WITH RECURSIVE c(x) AS ("
    "  SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 5000000"
    ") SELECT COUNT(*) FROM c"
)
# The cheap dashboard recent-list (sub-ms with the composite index).
LIGHT_SQL = "SELECT id FROM memories ORDER BY created_at DESC LIMIT 25"


def pct(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(len(vals) * p))]


async def head_of_line(writer):
    """1 slow query in flight + 20 light reads arriving just after."""
    print("== head-of-line: 1 slow query + 20 light reads ==")
    print(f"{'config':30s} {'light p50':>10s} {'light p95':>10s} {'light max':>10s}")
    for size in (1, 4):
        pool = ReadPool(writer._create_connection, size=size)
        await pool.connect()
        light_lat = []

        async def slow():
            await pool.fetchall(SLOW_SQL)

        async def light():
            await asyncio.sleep(0.001)  # arrive just after slow starts
            t = time.perf_counter()
            await pool.fetchall(LIGHT_SQL)
            light_lat.append((time.perf_counter() - t) * 1000)

        await asyncio.gather(slow(), *[light() for _ in range(20)])
        await pool.close()
        label = (
            "serialized size=1 (~before)"
            if size == 1
            else f"pooled size={size} (after)"
        )
        print(
            f"{label:30s} {pct(light_lat, .5):8.1f}ms "
            f"{pct(light_lat, .95):8.1f}ms {max(light_lat):8.1f}ms"
        )


async def uniform_burst(writer, emb, concurrency=16, rounds=10):
    """N concurrent vector searches — pure CPU-bound, no pool throughput win."""
    print(f"\n== uniform burst: {concurrency} concurrent vector searches ==")
    print(f"{'config':30s} {'p50':>9s} {'p95':>9s} {'max':>9s}")

    async def measure(pool):
        lat = []

        async def one():
            t = time.perf_counter()
            await pool.fetchall(VEC_SQL, (emb, 25))
            return (time.perf_counter() - t) * 1000

        for _ in range(rounds):
            lat.extend(await asyncio.gather(*[one() for _ in range(concurrency)]))
        return lat

    for size in (1, 8):
        pool = ReadPool(writer._create_connection, size=size)
        await pool.connect()
        lat = await measure(pool)
        await pool.close()
        label = (
            "serialized size=1 (~before)"
            if size == 1
            else f"pooled size={size} (after)"
        )
        print(
            f"{label:30s} {pct(lat, .5):7.1f}ms {pct(lat, .95):7.1f}ms "
            f"{max(lat):7.1f}ms"
        )


async def main():
    writer = DatabaseConnection(DB)
    await writer.connect()
    row = await writer.fetchone(
        "SELECT embedding FROM memories WHERE embedding IS NOT NULL LIMIT 1"
    )
    emb = row[0]
    print(f"DB={DB}\n")
    await head_of_line(writer)
    await uniform_burst(writer, emb)
    await writer.close()


if __name__ == "__main__":
    asyncio.run(main())
