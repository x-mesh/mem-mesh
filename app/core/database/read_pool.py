"""Read-only connection pool for concurrent SELECT / vector search (C3).

The legacy single-connection design serialized *every* query on one
asyncio.Lock, so concurrent read requests queued head-to-tail and tail latency
exploded under load (prod: crowded p95 865ms -> 2377ms). SQLite's WAL mode
already allows many concurrent readers + one writer, so the fix is to give
reads a pool of dedicated read-only connections.

Threading model — the production driver is ``pysqlite3`` with
``threadsafety=1`` (a connection may NOT be shared across threads). So each
pooled connection is pinned to its own single-thread executor: the connection
is created on that thread and every query for it runs on that same thread.
N connections on N threads => genuine read parallelism, with no cross-thread
connection sharing.
"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Callable, List, Optional, Tuple

# Reuse the same sqlite3 module alias connection.py resolved (pysqlite3 first)
# so Row types and behavior match the writer connection exactly.
from app.core.database.connection import sqlite3

logger = logging.getLogger(__name__)

# create_connection(read_only=True) -> (connection, vec_loaded)
ConnectionFactory = Callable[..., Tuple["sqlite3.Connection", bool]]


def default_pool_size() -> int:
    """Read pool size: max(2, min(cpu_count()-2, 8)).

    Leaves headroom for the event loop + writer thread, caps at 8 so we never
    open an unbounded number of file handles / WAL readers.
    """
    return max(2, min((os.cpu_count() or 4) - 2, 8))


class ReadSlot:
    """One read-only connection pinned to a dedicated single-thread executor.

    All access to ``self._conn`` happens on ``self._executor``'s single thread,
    which is the only thread that ever touches it — safe under threadsafety=1.
    """

    def __init__(self, create_connection: ConnectionFactory, index: int):
        self._create_connection = create_connection
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"mem-read-{index}"
        )
        self._conn: Optional["sqlite3.Connection"] = None
        self.vec_loaded = False

    async def open(self) -> None:
        """Create the connection on the pinned thread."""
        loop = asyncio.get_event_loop()
        self._conn, self.vec_loaded = await loop.run_in_executor(
            self._executor, self._create_connection, True  # read_only=True
        )

    async def fetchall(self, query: str, params: Tuple = ()) -> List["sqlite3.Row"]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._run_fetchall, query, params
        )

    async def fetchone(self, query: str, params: Tuple = ()) -> Optional["sqlite3.Row"]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._run_fetchone, query, params
        )

    def _run_fetchall(self, query: str, params: Tuple) -> List["sqlite3.Row"]:
        return self._conn.execute(query, params).fetchall()

    def _run_fetchone(self, query: str, params: Tuple) -> Optional["sqlite3.Row"]:
        return self._conn.execute(query, params).fetchone()

    async def close(self) -> None:
        """Close the connection on its thread, then shut the executor down."""
        loop = asyncio.get_event_loop()
        if self._conn is not None:
            try:
                await loop.run_in_executor(self._executor, self._conn.close)
            except Exception as e:
                logger.warning(f"Error closing read connection: {e}")
            finally:
                self._conn = None
        self._executor.shutdown(wait=True)


class ReadPool:
    """Pool of read-only connections for concurrent SELECT / vector search.

    Connections are handed out via ``acquire()`` (an async context manager)
    backed by an asyncio.Queue, so at most ``size`` reads run at once and a
    slot is always returned even if the caller raises.
    """

    def __init__(
        self,
        create_connection: ConnectionFactory,
        size: Optional[int] = None,
    ):
        self._create_connection = create_connection
        self.size = size if size is not None else default_pool_size()
        self._slots: List[ReadSlot] = []
        self._available: Optional[asyncio.Queue] = None
        self._closed = False

    async def connect(self) -> bool:
        """Open all pooled connections. Returns True if every slot has vec."""
        self._available = asyncio.Queue()
        for i in range(self.size):
            slot = ReadSlot(self._create_connection, i)
            await slot.open()
            self._slots.append(slot)
            self._available.put_nowait(slot)
        all_vec = all(s.vec_loaded for s in self._slots)
        logger.info(
            f"ReadPool connected: {self.size} connections, vec_loaded={all_vec}"
        )
        return all_vec

    @property
    def is_vec_available(self) -> bool:
        return bool(self._slots) and all(s.vec_loaded for s in self._slots)

    @asynccontextmanager
    async def acquire(self):
        """Borrow a read slot for the duration of the block."""
        if self._closed or self._available is None:
            raise RuntimeError("ReadPool not connected")
        slot = await self._available.get()
        try:
            yield slot
        finally:
            self._available.put_nowait(slot)

    async def fetchall(self, query: str, params: Tuple = ()) -> List["sqlite3.Row"]:
        async with self.acquire() as slot:
            return await slot.fetchall(query, params)

    async def fetchone(self, query: str, params: Tuple = ()) -> Optional["sqlite3.Row"]:
        async with self.acquire() as slot:
            return await slot.fetchone(query, params)

    async def close(self) -> None:
        """Close every pooled connection and stop accepting acquires."""
        self._closed = True
        for slot in self._slots:
            await slot.close()
        self._slots.clear()
        self._available = None
        logger.info("ReadPool closed")
