"""Tests for the C3 read-only connection pool.

Guards the read/write split: reads run concurrently on a pool of read-only
connections (no longer serialized on the single writer lock), while writes and
in-transaction reads stay on the writer connection so read-your-writes and
rollback isolation hold.
"""

import asyncio
import struct
import threading

import pytest

from app.core.database.base import Database
from app.core.database.read_pool import ReadPool, ReadSlot, default_pool_size

# 4-float embedding so add_memory's NOT NULL embedding column is satisfied.
EMB = struct.pack("4f", 0.1, 0.2, 0.3, 0.4)

# A CPU-bound query that holds the SQLite C call long enough (sqlite3 releases
# the GIL during execution) to expose serialization vs. parallelism.
SLOW = (
    "WITH RECURSIVE c(x) AS ("
    "  SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 2000000"
    ") SELECT COUNT(*) AS n FROM c"
)


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "pool.db"), embedding_dim=4)
    await database.connect()
    yield database
    await database.close()


async def _add(database: Database, mid: str) -> None:
    await database.add_memory(
        {
            "id": mid,
            "content": f"content {mid}",
            "content_hash": mid,
            "embedding": EMB,
            "created_at": "2026-06-15T00:00:00Z",
            "updated_at": "2026-06-15T00:00:00Z",
        }
    )


def test_default_pool_size_is_bounded():
    size = default_pool_size()
    assert 2 <= size <= 8


async def test_pool_connected_with_vec(db):
    assert db._read_pool.size >= 2
    assert db._read_pool.is_vec_available


async def test_reads_run_in_parallel(db, monkeypatch):
    """Concurrent SELECTs must not serialize on a single lock.

    Proven by occupancy, not wall clock. A barrier sized to the number of
    concurrent reads only releases if that many are inside their queries at the
    same instant; if reads serialize, the first one waits alone and the barrier
    times out. That is the property under test — "not serialized" — stated
    directly.

    The earlier version compared sequential vs parallel elapsed time and
    required a 25% speedup. On a shared CI runner the CPU-bound query did not
    reliably speed up (observed 0.336s vs 0.357s), so the job failed on runner
    contention rather than on any regression.
    """
    n = min(4, db._read_pool.size)
    # Pin this independently of the pool size: with n == 1 a Barrier(1) opens
    # immediately, so a pool that shrank to a single slot — reads serialized by
    # definition — would sail through the rendezvous below.
    assert n >= 2, f"read pool must offer at least 2 slots, got {db._read_pool.size}"
    barrier = threading.Barrier(n, timeout=15)
    original = ReadSlot._run_fetchone
    arrived = []

    def _rendezvous(self, query, params):
        if query == SLOW:
            arrived.append(threading.current_thread().name)
            barrier.wait()  # releases only once n threads are here together
        return original(self, query, params)

    monkeypatch.setattr(ReadSlot, "_run_fetchone", _rendezvous)

    try:
        await asyncio.gather(*[db.fetchone(SLOW) for _ in range(n)])
    except threading.BrokenBarrierError:
        pytest.fail(
            f"reads appear serialized: only {len(arrived)}/{n} concurrent reads "
            f"were in flight at once (threads: {sorted(set(arrived))})"
        )

    # Each read must have run on its own pinned thread, not one shared worker.
    assert (
        len(set(arrived)) == n
    ), f"expected {n} distinct read threads, got {sorted(set(arrived))}"


async def test_read_pool_blocks_writes(db):
    """A write mis-routed to the read pool must fail (PRAGMA query_only)."""
    with pytest.raises(Exception):
        await db.fetchone(
            "INSERT INTO memories "
            "(id, content, content_hash, embedding, created_at, updated_at) "
            "VALUES ('x', 'c', 'h', ?, 'now', 'now')",
            (EMB,),
        )
    # The write was rejected, not silently dropped.
    assert await db.count_memories() == 0


async def test_read_your_writes_inside_transaction(db):
    """In-transaction reads route to the writer and see uncommitted rows."""
    async with db.transaction():
        await _add(db, "m1")
        # read pool is a separate connection and would see 0; writer sees 1.
        assert await db.count_memories() == 1
    assert await db.count_memories() == 1


async def test_rollback_isolation(db):
    """A rolled-back write must never become visible to the read pool."""
    with pytest.raises(RuntimeError):
        async with db.transaction():
            await _add(db, "m2")
            raise RuntimeError("force rollback")
    assert await db.count_memories() == 0


async def test_committed_writes_visible_to_pool(db):
    """After commit, the read pool (separate connections) sees the new rows."""
    await _add(db, "m3")  # outside a transaction -> writer autocommit
    rows = await db.get_recent_memories(limit=10)
    assert len(rows) == 1
    assert rows[0]["id"] == "m3"


async def test_close_is_idempotent_and_stops_workers(db):
    import threading

    await db.close()
    live = [t.name for t in threading.enumerate() if "mem-read" in t.name]
    assert not live, f"read-pool worker threads still alive: {live}"
    # Fixture will call close() again; ReadPool.close must be safe to repeat.


async def test_explicit_pool_size_override():
    pool = ReadPool(lambda read_only=False: (None, False), size=3)
    assert pool.size == 3
