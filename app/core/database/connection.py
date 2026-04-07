"""Database connection management for mem-mesh.

This module provides SQLite database connection with WAL mode support
and sqlite-vec extension for vector search capabilities.

Requirements: 4.1, 4.4 - SQLite WAL mode and busy_timeout configuration
"""

# Use pysqlite3 preferentially (supports extension loading)
try:
    import pysqlite3.dbapi2 as sqlite3

    SQLITE3_MODULE = "pysqlite3"
except ImportError:
    import sqlite3

    SQLITE3_MODULE = "sqlite3"

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import sqlite_vec

    # Check whether SQLite extension loading is supported
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

    async def connect(self) -> bool:
        """Connect to database and load sqlite-vec extension.

        Returns:
            bool: True if sqlite-vec was loaded successfully
        """
        async with self._lock:
            if self.connection is not None:
                return self._vec_loaded

            # Create database directory
            db_path = Path(self.db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                # Create SQLite connection
                self.connection = sqlite3.connect(
                    self.db_path,
                    check_same_thread=False,
                    isolation_level=None,  # autocommit mode
                )

                # Set row factory (return results as dicts)
                self.connection.row_factory = sqlite3.Row

                # Set busy_timeout (Requirement 4.4)
                self.connection.execute(f"PRAGMA busy_timeout={self.busy_timeout}")
                logger.info(f"SQLite busy_timeout set to {self.busy_timeout}ms")

                # Enable WAL mode (Requirement 4.1)
                self.connection.execute("PRAGMA journal_mode=WAL")
                logger.info("SQLite WAL mode enabled")

                # Enable foreign key constraints
                self.connection.execute("PRAGMA foreign_keys=ON")

                # Attempt to load sqlite-vec
                self._vec_loaded = self._load_sqlite_vec()

                logger.info(f"Database connected: {self.db_path}")
                return self._vec_loaded

            except Exception as e:
                logger.error(f"Failed to connect to database: {e}")
                if self.connection:
                    self.connection.close()
                    self.connection = None
                raise

    def _load_sqlite_vec(self) -> bool:
        """Load sqlite-vec extension.

        Returns:
            bool: True if loaded successfully
        """
        vec_loaded = False

        if SQLITE_VEC_AVAILABLE:
            try:
                # Method 1: Load via sqlite-vec Python package
                sqlite_vec.load(self.connection)
                logger.info("sqlite-vec loaded via Python package")
                vec_loaded = True
            except Exception as e:
                logger.warning(f"Failed to load sqlite-vec via Python package: {e}")

        # Method 2: Attempt direct extension load
        if not vec_loaded and hasattr(self.connection, "load_extension"):
            try:
                # Attempt direct sqlite-vec extension load on macOS
                self.connection.enable_load_extension(True)
                self.connection.load_extension("vec0")
                logger.info("sqlite-vec loaded via direct extension loading")
                vec_loaded = True
            except Exception as e:
                logger.warning(f"Failed to load sqlite-vec via extension: {e}")
            finally:
                try:
                    self.connection.enable_load_extension(False)
                except Exception as e:
                    logger.warning(f"Failed to disable extension loading: {e}")

        # Method 3: Test vector table creation
        if vec_loaded:
            try:
                # Test vector functionality
                self.connection.execute("SELECT vec_version()")
                logger.info("sqlite-vec vector functions are available")
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
        async with self._lock:
            if self.connection:
                try:
                    # Commit any in-progress transaction
                    self.connection.commit()
                except Exception as e:
                    logger.warning(f"Error committing final transaction: {e}")

                try:
                    # Run WAL checkpoint (apply changes to main DB file)
                    self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception as e:
                    logger.warning(f"Error during WAL checkpoint: {e}")

                try:
                    # Close connection
                    self.connection.close()
                    logger.info("Database connection closed")
                except Exception as e:
                    logger.warning(f"Error closing database connection: {e}")
                finally:
                    self.connection = None

    async def execute(self, query: str, params: Tuple = ()) -> sqlite3.Cursor:
        """Execute a query."""
        if not self.connection:
            raise RuntimeError("Database not connected")

        try:
            cursor = self.connection.execute(query, params)
            return cursor
        except Exception as e:
            logger.error(
                f"Query execution failed: {query}, params: {params}, error: {e}"
            )
            raise

    async def fetchone(self, query: str, params: Tuple = ()) -> Optional[sqlite3.Row]:
        """Fetch a single row."""
        cursor = await self.execute(query, params)
        return cursor.fetchone()

    async def fetchall(self, query: str, params: Tuple = ()) -> List[sqlite3.Row]:
        """Fetch all rows."""
        cursor = await self.execute(query, params)
        return cursor.fetchall()

    def commit(self) -> None:
        """Commit current transaction."""
        if self.connection:
            self.connection.commit()

    @asynccontextmanager
    async def transaction(self):
        """Transaction context manager. All execute() calls inside use _execute_raw."""
        if not self.connection:
            raise RuntimeError("Database not connected")

        async with self._lock:
            try:
                self.connection.execute("BEGIN")
                yield
                self.connection.execute("COMMIT")
            except Exception as e:
                logger.debug(f"Transaction rolled back: {e}")
                self.connection.execute("ROLLBACK")
                raise

