"""Concurrency regression tests for DatabaseConnection.

Guards the torn-transaction fix: all connection access is serialized on the
connection lock, and execute()/fetch* inside a transaction() skip the lock via
the _in_transaction contextvar instead of dead-locking.

Before the fix, execute() acquired no lock, so a concurrent writer's statement
folded into another coroutine's open BEGIN..COMMIT (single shared connection)
and a rollback could discard the other writer's committed work. These tests
fail against that old behavior and pass with the lock-aware connection.
"""

import asyncio
import os
import tempfile

import pytest


@pytest.fixture
async def db():
    from app.core.database.connection import DatabaseConnection

    d = tempfile.mkdtemp()
    path = os.path.join(d, "concurrency.db")
    conn = DatabaseConnection(path)
    await conn.connect()
    await conn.execute(
        "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, who TEXT)"
    )
    yield conn
    await conn.close()


async def test_rollback_does_not_discard_concurrent_writer(db):
    """A's transaction rolls back; B's independent insert must survive.

    Old (no lock): B's INSERT joins A's open transaction, A's ROLLBACK drops
    both → table empty. Fixed: B blocks on the lock until A's transaction ends,
    then commits on its own → only B1 remains.
    """

    async def tx_writer():
        with pytest.raises(RuntimeError):
            async with db.transaction():
                await db.execute("INSERT INTO t (who) VALUES ('A1')")
                await asyncio.sleep(0.02)  # yield so B can attempt to interleave
                raise RuntimeError("force rollback")

    async def other_writer():
        await asyncio.sleep(0.005)  # let A enter its transaction first
        await db.execute("INSERT INTO t (who) VALUES ('B1')")

    await asyncio.gather(tx_writer(), other_writer())

    rows = await db.fetchall("SELECT who FROM t ORDER BY who")
    assert [r["who"] for r in rows] == ["B1"]


async def test_transaction_commits_atomically(db):
    """A clean transaction commits all its statements together."""
    async with db.transaction():
        await db.execute("INSERT INTO t (who) VALUES ('x')")
        await db.execute("INSERT INTO t (who) VALUES ('y')")

    rows = await db.fetchall("SELECT who FROM t ORDER BY who")
    assert [r["who"] for r in rows] == ["x", "y"]


async def test_concurrent_transactions_serialize(db):
    """Two transactions running concurrently do not interleave or torn-write.

    Each inserts a pair; with serialization the pairs never split, so the table
    holds exactly both pairs.
    """

    async def insert_pair(tag):
        async with db.transaction():
            await db.execute("INSERT INTO t (who) VALUES (?)", (f"{tag}-1",))
            await asyncio.sleep(0.01)  # encourage interleaving if the lock fails
            await db.execute("INSERT INTO t (who) VALUES (?)", (f"{tag}-2",))

    await asyncio.gather(insert_pair("p"), insert_pair("q"))

    rows = await db.fetchall("SELECT who FROM t ORDER BY who")
    assert [r["who"] for r in rows] == ["p-1", "p-2", "q-1", "q-2"]


async def test_no_deadlock_on_nested_transaction(db):
    """A transaction() nested on the same task runs inline without dead-locking."""
    async with db.transaction():
        await db.execute("INSERT INTO t (who) VALUES ('outer')")
        async with db.transaction():  # must not block on the lock it already holds
            await db.execute("INSERT INTO t (who) VALUES ('inner')")

    rows = await db.fetchall("SELECT who FROM t ORDER BY who")
    assert [r["who"] for r in rows] == ["inner", "outer"]
