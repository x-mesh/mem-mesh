"""Database connection management for mem-mesh.

This module provides SQLite database connection with WAL mode support
and sqlite-vec extension for vector search capabilities.

Requirements: 4.1, 4.4 - SQLite WAL mode and busy_timeout configuration
"""

# pysqlite3를 우선적으로 사용 (extension loading 지원)
try:
    import pysqlite3.dbapi2 as sqlite3

    SQLITE3_MODULE = "pysqlite3"
except ImportError:
    import sqlite3

    SQLITE3_MODULE = "sqlite3"

import asyncio
import contextvars
import logging
import weakref
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional, Tuple

# Marks the asyncio task currently inside a transaction() block so the
# lock-aware execute()/fetch* helpers skip re-acquiring the connection lock the
# transaction already holds (which would self-deadlock). Propagates across
# awaits within the same task.
_in_transaction: "contextvars.ContextVar[bool]" = contextvars.ContextVar(
    "mem_mesh_db_in_transaction", default=False
)

try:
    import sqlite_vec

    # SQLite extension loading 지원 여부 확인
    test_conn = sqlite3.connect(":memory:")
    if hasattr(test_conn, "load_extension"):
        SQLITE_VEC_AVAILABLE = True
        logger = logging.getLogger(__name__)
        logger.info(
            f"sqlite-vec available with {SQLITE3_MODULE} (extension loading supported)"
        )
    else:
        SQLITE_VEC_AVAILABLE = False
        logger = logging.getLogger(__name__)
        logger.warning(
            f"sqlite-vec available with {SQLITE3_MODULE} but extension loading not supported"
        )
    test_conn.close()
except ImportError:
    SQLITE_VEC_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("sqlite-vec Python package not available")

logger = logging.getLogger(__name__)

# WAL permits concurrent readers, but only one writer. Relay concurrency creates
# multiple Database instances in one event loop, so coordinate their short write
# spans before they contend inside SQLite. Scope locks to the current event loop.
_writer_locks: (
    "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]"
) = weakref.WeakKeyDictionary()


def is_sqlite_busy_error(exc: BaseException) -> bool:
    """Return whether an exception is retryable SQLite writer contention."""

    if not isinstance(exc, sqlite3.OperationalError):
        return False
    code = getattr(exc, "sqlite_errorcode", None)
    if code is not None and (code & 0xFF) in {
        getattr(sqlite3, "SQLITE_BUSY", 5),
        getattr(sqlite3, "SQLITE_LOCKED", 6),
    }:
        return True
    message = str(exc).lower()
    return "locked" in message or "busy" in message


class DatabaseConnection:
    """SQLite database connection management.

    Handles connection lifecycle, WAL mode, extension loading,
    and basic query execution.

    Requirements:
    - 4.1: WAL 모드 활성화
    - 4.4: busy_timeout 설정
    """

    def __init__(self, db_path: str, busy_timeout: int = 5000):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file
            busy_timeout: SQLite busy timeout in milliseconds (default: 5000)
        """
        self.db_path = db_path
        self.busy_timeout = busy_timeout
        self.connection: Optional[sqlite3.Connection] = None
        self._lock = asyncio.Lock()
        self._vec_loaded = False
        self._writer_lock_key = self._canonical_writer_lock_key(db_path)

    @staticmethod
    def _canonical_writer_lock_key(db_path: str) -> str:
        if db_path in (":memory:", "") or db_path.startswith("file:"):
            return db_path
        return str(Path(db_path).expanduser().resolve())

    def _writer_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        locks = _writer_locks.setdefault(loop, {})
        return locks.setdefault(self._writer_lock_key, asyncio.Lock())

    async def connect(self) -> bool:
        """Connect to database and load sqlite-vec extension.

        Returns:
            bool: True if sqlite-vec was loaded successfully
        """
        async with self._writer_lock():
            async with self._lock:
                if self.connection is not None:
                    return self._vec_loaded

                # 데이터베이스 디렉토리 생성
                db_path = Path(self.db_path)
                db_path.parent.mkdir(parents=True, exist_ok=True)

                try:
                    # 쓰기 전용 연결 생성 (PRAGMA + sqlite-vec 초기화 포함)
                    self.connection, self._vec_loaded = self._create_connection(
                        read_only=False
                    )

                    logger.info(f"Database connected: {self.db_path}")
                    return self._vec_loaded

                except Exception as e:
                    logger.error(f"Failed to connect to database: {e}")
                    if self.connection:
                        self.connection.close()
                        self.connection = None
                    raise

    def _create_connection(
        self, read_only: bool = False
    ) -> Tuple[sqlite3.Connection, bool]:
        """Create and fully initialize a new SQLite connection.

        Shared by connect() (the single writer connection) and the read pool
        (C3) so every connection in the process is configured identically —
        same PRAGMAs, same sqlite-vec extension. ``read_only=True`` adds
        ``PRAGMA query_only=ON`` so a pooled reader can never mutate the DB,
        even if a write query is mis-routed to it.

        Returns:
            (connection, vec_loaded)
        """
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit mode
        )
        vec_loaded = self._init_connection(conn, read_only=read_only)
        return conn, vec_loaded

    def _init_connection(
        self, conn: sqlite3.Connection, read_only: bool = False
    ) -> bool:
        """Apply row factory, PRAGMAs, and load sqlite-vec on ``conn``.

        Idempotent — safe to call on any freshly opened connection. Extracted
        from connect() so the read pool can initialize its connections through
        the exact same path.

        Requirements: 4.1 (WAL), 4.4 (busy_timeout).

        Returns:
            bool: True if sqlite-vec loaded successfully on this connection.
        """
        # Row factory 설정 (dict 형태로 결과 반환)
        conn.row_factory = sqlite3.Row

        # busy_timeout 설정 (Requirement 4.4)
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout}")

        # WAL is persistent and the writer established it before read-pool
        # connections open. Reissuing journal_mode from every pooled reader can
        # itself require a schema lock during concurrency=N startup.
        if not read_only:
            conn.execute("PRAGMA journal_mode=WAL")

        # Durability: under WAL the default synchronous=NORMAL does not fsync
        # the WAL on commit, so a power loss / kernel panic can lose the last
        # committed memory+vector (the graceful-close checkpoint never runs).
        # FULL fsyncs on commit. For a durability-critical memory store this is
        # the correct default.
        conn.execute("PRAGMA synchronous=FULL")

        # Foreign key 제약 조건 활성화
        conn.execute("PRAGMA foreign_keys=ON")

        if read_only:
            # Pooled reader: hard-block any accidental write at the SQLite layer
            # so a mis-routed INSERT/UPDATE/DELETE fails loudly instead of
            # racing the writer connection.
            conn.execute("PRAGMA query_only=ON")

        return self._load_sqlite_vec(conn)

    def _load_sqlite_vec(self, conn: sqlite3.Connection) -> bool:
        """Load sqlite-vec extension on ``conn``.

        Args:
            conn: the connection to load the extension into.

        Returns:
            bool: True if loaded successfully
        """
        vec_loaded = False

        # Python sqlite3는 기본적으로 extension 로딩이 disabled 이므로
        # 먼저 enable 해야 sqlite_vec.load() / load_extension() 이 성공한다.
        enabled_here = False
        if hasattr(conn, "enable_load_extension"):
            try:
                conn.enable_load_extension(True)
                enabled_here = True
            except Exception as e:
                logger.warning(f"enable_load_extension failed: {e}")

        try:
            if SQLITE_VEC_AVAILABLE:
                try:
                    # 방법 1: sqlite-vec Python 패키지로 로드
                    sqlite_vec.load(conn)
                    vec_loaded = True
                except Exception as e:
                    logger.warning(f"Failed to load sqlite-vec via Python package: {e}")

            # 방법 2: sqlite_vec.loadable_path() 경로로 직접 로드
            if not vec_loaded and hasattr(conn, "load_extension"):
                try:
                    loadable_path = sqlite_vec.loadable_path()
                    conn.load_extension(loadable_path)
                    vec_loaded = True
                except Exception as e:
                    logger.warning(f"Failed to load sqlite-vec via extension: {e}")
        finally:
            if enabled_here:
                try:
                    conn.enable_load_extension(False)
                except Exception as e:
                    logger.warning(f"Failed to disable extension loading: {e}")

        # 방법 3: 벡터 함수 동작 테스트
        if vec_loaded:
            try:
                conn.execute("SELECT vec_version()")
            except Exception as e:
                logger.warning(
                    f"sqlite-vec loaded but vector functions not available: {e}"
                )
                vec_loaded = False

        if not vec_loaded:
            logger.warning("sqlite-vec not available, using fallback text search only")

        return vec_loaded

    @property
    def is_vec_available(self) -> bool:
        """Check if sqlite-vec is available."""
        return self._vec_loaded

    async def close(self) -> None:
        """Close database connection."""
        async with self._writer_lock():
            async with self._lock:
                if not self.connection:
                    return
                try:
                    # 진행 중인 트랜잭션 커밋
                    self.connection.commit()
                except Exception as e:
                    logger.warning(f"Error committing final transaction: {e}")

                try:
                    # WAL 체크포인트 실행 (변경사항을 메인 DB 파일에 반영)
                    self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception as e:
                    logger.warning(f"Error during WAL checkpoint: {e}")

                try:
                    # 연결 종료
                    self.connection.close()
                    logger.info("Database connection closed")
                except Exception as e:
                    logger.warning(f"Error closing database connection: {e}")
                finally:
                    self.connection = None

    async def execute(self, query: str, params: Tuple = ()) -> sqlite3.Cursor:
        """Execute a query, serialized on the connection lock.

        All connection access goes through ``_lock`` so a writer can never
        interleave with — or prematurely commit — another coroutine's open
        transaction() (the torn-transaction hazard). Calls made inside a
        transaction() block already hold the lock, so they skip re-acquiring it.
        Callers that read from the returned cursor must do so synchronously (no
        await before fetch) — the cursor is valid until the next await.
        """
        if not self.connection:
            raise RuntimeError("Database not connected")

        if _in_transaction.get():
            return self._execute_raw(query, params)
        async with self._writer_lock():
            async with self._lock:
                return self._execute_raw(query, params)

    def _execute_raw(self, query: str, params: Tuple = ()) -> sqlite3.Cursor:
        """Run a statement without acquiring the lock.

        Used by execute()/fetch* once the lock is held (or skipped inside a
        transaction) and by transaction() bodies.
        """
        try:
            return self.connection.execute(query, params)
        except Exception as e:
            logger.error(
                f"Query execution failed: {query}, params: {params}, error: {e}"
            )
            raise

    async def fetchone(self, query: str, params: Tuple = ()) -> Optional[sqlite3.Row]:
        """Fetch a single row (execute + fetch under one lock acquisition)."""
        if not self.connection:
            raise RuntimeError("Database not connected")
        if _in_transaction.get():
            return self._execute_raw(query, params).fetchone()
        async with self._lock:
            return self._execute_raw(query, params).fetchone()

    async def fetchall(self, query: str, params: Tuple = ()) -> List[sqlite3.Row]:
        """Fetch all rows (execute + fetch under one lock acquisition)."""
        if not self.connection:
            raise RuntimeError("Database not connected")
        if _in_transaction.get():
            return self._execute_raw(query, params).fetchall()
        async with self._lock:
            return self._execute_raw(query, params).fetchall()

    def commit(self) -> None:
        """Commit current transaction."""
        if self.connection:
            self.connection.commit()

    @asynccontextmanager
    async def transaction(self):
        """Transaction context manager.

        Holds ``_lock`` for the whole BEGIN..COMMIT span and marks the task via
        ``_in_transaction`` so execute()/fetch* calls in the body run on the
        already-held lock instead of dead-locking on it (the docstring's old
        "use _execute_raw" promise is now actually enforced). A nested
        transaction() on the same task runs inline — the outer one owns the
        atomic unit.
        """
        if not self.connection:
            raise RuntimeError("Database not connected")

        if _in_transaction.get():
            yield
            return

        async with self._writer_lock():
            async with self._lock:
                token = _in_transaction.set(True)
                try:
                    # BEGIN IMMEDIATE grabs the write lock up front so
                    # busy_timeout applies before the transaction body runs.
                    # The bounded retry covers residual cross-process contention.
                    await self._execute_with_busy_retry("BEGIN IMMEDIATE")
                    yield
                    await self._execute_with_busy_retry("COMMIT")
                except Exception:
                    try:
                        self.connection.execute("ROLLBACK")
                    except Exception:  # noqa: BLE001 — rollback best-effort
                        pass
                    raise
                finally:
                    _in_transaction.reset(token)

    async def _execute_with_busy_retry(
        self, sql: str, *, attempts: int = 6, base_sleep: float = 0.05
    ) -> None:
        """Run a lock-sensitive statement (BEGIN IMMEDIATE / COMMIT), retrying on
        'database is locked' with exponential backoff beyond busy_timeout.

        Only for statements with no result to read and safe to re-issue before
        they take effect (BEGIN before the body runs; COMMIT is retried only
        after a busy failure, before any ROLLBACK)."""
        for i in range(attempts):
            try:
                self.connection.execute(sql)
                return
            except sqlite3.OperationalError as e:
                if is_sqlite_busy_error(e) and i < attempts - 1:
                    await asyncio.sleep(base_sleep * (2**i))
                    continue
                raise
