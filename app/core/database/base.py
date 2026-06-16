"""Database facade for mem-mesh - backward compatible interface.

This module provides the Database class that delegates to specialized modules:
- connection.py: Connection management, WAL mode, extension loading
- initializer.py: Table creation, schema setup
- migrator.py: Embedding migrations, metadata management

Requirements: 4.1, 4.4 - SQLite WAL mode and busy_timeout configuration
"""

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .connection import (
    SQLITE3_MODULE,
    SQLITE_VEC_AVAILABLE,
    DatabaseConnection,
    _in_transaction,
)
from .initializer import DatabaseInitializer
from .migrator import DatabaseMigrator
from .read_pool import ReadPool

try:
    import pysqlite3.dbapi2 as sqlite3
except ImportError:
    import sqlite3

logger = logging.getLogger(__name__)

# Blue-green embedding table slots. The vector table is a sqlite-vec vec0
# virtual table, which cannot be RENAMEd, so model migration re-embeds into the
# *inactive* slot and then flips the `active_embedding_table` metadata pointer
# atomically — search/writes always target the active slot. PRIMARY is the
# legacy name so existing DBs keep working with no migration.
EMBEDDING_TABLE_PRIMARY = "memory_embeddings"
EMBEDDING_TABLE_SECONDARY = "memory_embeddings_b"
EMBEDDING_TABLE_SLOTS = (EMBEDDING_TABLE_PRIMARY, EMBEDDING_TABLE_SECONDARY)
EMBEDDING_TABLE_FALLBACK = "memories_vec_fallback"

__all__ = [
    "Database",
    "SQLITE_VEC_AVAILABLE",
    "SQLITE3_MODULE",
    "EMBEDDING_TABLE_PRIMARY",
    "EMBEDDING_TABLE_SECONDARY",
    "EMBEDDING_TABLE_SLOTS",
]


class Database:
    """SQLite + sqlite-vec database facade.

    Provides backward-compatible interface while delegating to specialized modules.

    Requirements:
    - 4.1: WAL mode enabled
    - 4.4: busy_timeout configuration
    """

    def __init__(
        self,
        db_path: str,
        busy_timeout: int = 5000,
        embedding_dim: Optional[int] = None,
    ):
        if embedding_dim is None:
            try:
                from ..config import Settings

                embedding_dim = Settings().embedding_dim
            except Exception as e:
                logger.debug(
                    f"Failed to load settings for embedding_dim, using default 384: {e}"
                )
                embedding_dim = 384

        self.db_path = db_path
        self.busy_timeout = busy_timeout
        self.embedding_dim = embedding_dim
        self._db_path_in_memory = self._is_in_memory(db_path)
        # Cached active embedding-table pointer (blue-green). Invalidated on swap.
        self._active_embedding_table: Optional[str] = None
        self._connection = DatabaseConnection(db_path, busy_timeout)
        # C3: read-only connection pool for concurrent SELECT / vector search.
        # Reuses the writer's _create_connection so every connection is
        # configured identically (PRAGMAs + sqlite-vec), read_only=True.
        #
        # An in-memory DB (":memory:") is private to each connection, so a
        # pooled reader would open an *empty* second database and never see the
        # writer's tables. Disable the pool there and route every read to the
        # writer connection. Production uses a file DB, so the pool is active.
        self._read_pool_enabled = not self._db_path_in_memory
        self._read_pool = ReadPool(self._connection._create_connection)
        self._initializer = DatabaseInitializer(self._connection, embedding_dim)
        self._migrator = DatabaseMigrator(self._connection)

    @staticmethod
    def _is_in_memory(db_path: str) -> bool:
        """True for an in-memory SQLite DB (private to each connection)."""
        return (
            db_path in (":memory:", "")
            or db_path.startswith("file::memory:")
            or "mode=memory" in db_path
        )

    @property
    def connection(self) -> Optional[sqlite3.Connection]:
        return self._connection.connection

    @property
    def _lock(self):
        return self._connection._lock

    async def connect(self) -> None:
        await self._connection.connect()
        await self.init_tables()
        # Open the read pool only after schema init so every reader sees the
        # final schema (and the WAL the writer just created). Skipped for
        # in-memory DBs, where pooled connections can't see the writer's tables.
        if self._read_pool_enabled:
            await self._read_pool.connect()
        logger.info(f"Database connected: {self.db_path}")

    async def init_tables(self) -> None:
        await self._initializer.initialize_schema()
        if self._connection.is_vec_available:
            await self._migrator.migrate_embeddings_to_vector_table()

    async def close(self) -> None:
        # Close readers first (they hold WAL read locks), then the writer runs
        # the final checkpoint with no readers pinning the WAL.
        if self._read_pool_enabled:
            await self._read_pool.close()
        await self._connection.close()

    async def execute(self, query: str, params: Tuple = ()) -> sqlite3.Cursor:
        # execute() returns a live cursor, which is bound to its connection's
        # thread and cannot cross the read-pool thread boundary — so it always
        # runs on the writer connection. Use fetchone/fetchall for pooled reads.
        return await self._connection.execute(query, params)

    async def fetchone(self, query: str, params: Tuple = ()) -> Optional[sqlite3.Row]:
        # Inside a transaction(), reads must hit the writer connection to see
        # the open transaction's own uncommitted rows (read-your-writes); the
        # read pool is a separate connection and would miss them. Outside a
        # transaction, route to the read pool for concurrency.
        if _in_transaction.get() or not self._read_pool_enabled:
            return await self._connection.fetchone(query, params)
        return await self._read_pool.fetchone(query, params)

    async def fetchall(self, query: str, params: Tuple = ()) -> List[sqlite3.Row]:
        if _in_transaction.get() or not self._read_pool_enabled:
            return await self._connection.fetchall(query, params)
        return await self._read_pool.fetchall(query, params)

    async def get_embedding_metadata(self, key: str) -> Optional[str]:
        return await self._migrator.get_embedding_metadata(key)

    async def set_embedding_metadata(self, key: str, value: str) -> None:
        await self._migrator.set_embedding_metadata(key, value)

    # Runtime app-config overrides reuse the metadata key-value table under a
    # ``config.`` namespace so dashboard-set settings persist without a new
    # migration. See app.core.runtime_config for the precedence/resolver.
    async def get_app_config(self, key: str) -> Optional[str]:
        return await self._migrator.get_embedding_metadata(f"config.{key}")

    async def set_app_config(self, key: str, value: str) -> None:
        await self._migrator.set_embedding_metadata(f"config.{key}", value)

    async def delete_app_config(self, key: str) -> None:
        await self._migrator.delete_embedding_metadata(f"config.{key}")

    async def active_embedding_table(self) -> str:
        """현재 검색/쓰기 대상 벡터 테이블(blue-green active slot).

        모델 마이그레이션은 inactive slot에 재임베딩 후 이 포인터를 원자적으로
        전환한다. 메타데이터 미설정/구버전 DB는 PRIMARY(legacy 이름)로 동작한다.
        """
        if self._active_embedding_table is None:
            name = await self._migrator.get_embedding_metadata("active_embedding_table")
            self._active_embedding_table = (
                name if name in EMBEDDING_TABLE_SLOTS else EMBEDDING_TABLE_PRIMARY
            )
        return self._active_embedding_table

    async def inactive_embedding_table(self) -> str:
        """마이그레이션 대상(green) slot — active의 반대편."""
        active = await self.active_embedding_table()
        return (
            EMBEDDING_TABLE_SECONDARY
            if active == EMBEDDING_TABLE_PRIMARY
            else EMBEDDING_TABLE_PRIMARY
        )

    async def set_active_embedding_table(self, table: str) -> None:
        """active slot 포인터를 원자적으로 전환한다(blue-green swap)."""
        if table not in EMBEDDING_TABLE_SLOTS:
            raise ValueError(f"Invalid embedding table slot: {table}")
        await self._migrator.set_embedding_metadata("active_embedding_table", table)
        self._active_embedding_table = table

    async def migration_in_progress(self) -> bool:
        """재임베딩 진행 중 여부(DB 영속 — 서버 재시작에도 유지)."""
        val = await self._migrator.get_embedding_metadata("migration_in_progress")
        return val == "1"

    async def set_migration_in_progress(self, value: bool) -> None:
        await self._migrator.set_embedding_metadata(
            "migration_in_progress", "1" if value else "0"
        )

    async def check_embedding_model_consistency(
        self, current_model: str, current_dim: int
    ) -> dict:
        return await self._migrator.check_embedding_model_consistency(
            current_model, current_dim
        )

    async def _migrate_embeddings_to_vector_table(self) -> None:
        await self._migrator.migrate_embeddings_to_vector_table()

    async def vector_search(
        self, embedding: bytes, limit: int, filters: Optional[Dict[str, Any]] = None
    ) -> List[Tuple]:
        if not self.connection:
            raise RuntimeError("Database not connected")

        if SQLITE_VEC_AVAILABLE:
            try:
                active_table = await self.active_embedding_table()
                table_row = await self.fetchone(
                    "SELECT name FROM sqlite_master " "WHERE type='table' AND name=?",
                    (active_table,),
                )

                if table_row:
                    embedding_array = np.frombuffer(embedding, dtype=np.float32)
                    embedding_json = json.dumps(embedding_array.tolist())

                    has_filters = bool(
                        filters
                        and (filters.get("project_id") or filters.get("category"))
                    )
                    inner_limit = limit * 5 if has_filters else limit

                    # Table name is from a fixed slot allowlist (active_embedding_table),
                    # never user input — safe to interpolate.
                    base_query = f"""
                        SELECT m.*, ve.distance
                        FROM memories m
                        JOIN (
                            SELECT memory_id, distance
                            FROM {active_table}
                            WHERE embedding MATCH ?
                            ORDER BY distance
                            LIMIT ?
                        ) ve ON m.id = ve.memory_id
                    """
                    params = [embedding_json, inner_limit]

                    if filters:
                        filter_conditions = []
                        if filters.get("project_id"):
                            filter_conditions.append("m.project_id = ?")
                            params.append(filters["project_id"])
                        if filters.get("category"):
                            filter_conditions.append("m.category = ?")
                            params.append(filters["category"])

                        if filter_conditions:
                            base_query += f" WHERE {' AND '.join(filter_conditions)}"

                    base_query += f" ORDER BY ve.distance LIMIT {limit}"

                    results = await self.fetchall(base_query, tuple(params))

                    if results:
                        logger.info(f"Vector search found {len(results)} results")
                        return results
                    else:
                        logger.info(
                            "Vector search returned no results, falling back to text search"
                        )
                else:
                    logger.info("Vector table not found, falling back to text search")
            except Exception as e:
                logger.warning(
                    f"Vector search failed: {e}, falling back to text search"
                )

        logger.info("Using fallback text search (vector search not available)")
        return await self._fallback_search(limit, filters)

    async def _fallback_search(
        self, limit: int, filters: Optional[Dict[str, Any]] = None
    ) -> List[Tuple]:
        base_query = "SELECT * FROM memories WHERE 1=1"
        params = []

        if filters:
            if filters.get("project_id"):
                base_query += " AND project_id = ?"
                params.append(filters["project_id"])
            if filters.get("category"):
                base_query += " AND category = ?"
                params.append(filters["category"])

        base_query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        return await self.fetchall(base_query, tuple(params))

    async def get_recent_memories(
        self,
        limit: int,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_direction: str = "desc",
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[sqlite3.Row]:
        if not self.connection:
            raise RuntimeError("Database not connected")

        try:
            base_query = "SELECT * FROM memories WHERE 1=1"
            params = []

            if filters:
                if filters.get("project_id"):
                    base_query += " AND project_id = ?"
                    params.append(filters["project_id"])
                if filters.get("category"):
                    base_query += " AND category = ?"
                    params.append(filters["category"])
                if filters.get("source"):
                    base_query += " AND source = ?"
                    params.append(filters["source"])
                if filters.get("tag"):
                    base_query += " AND JSON_EXTRACT(tags, '$') LIKE ?"
                    params.append(f'%"{filters["tag"]}"%')

            valid_sort_columns = [
                "created_at",
                "updated_at",
                "category",
                "project_id",
                "source",
            ]
            if sort_by not in valid_sort_columns:
                sort_by = "created_at"

            sort_direction = sort_direction.upper()
            if sort_direction not in ["ASC", "DESC"]:
                sort_direction = "DESC"

            if sort_by == "size":
                base_query += f" ORDER BY LENGTH(content) {sort_direction}"
            elif sort_by == "project":
                base_query += f" ORDER BY project_id {sort_direction}"
            else:
                base_query += f" ORDER BY {sort_by} {sort_direction}"

            base_query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            return await self.fetchall(base_query, tuple(params))

        except Exception as e:
            logger.error(f"Get recent memories failed: {e}")
            raise

    async def count_memories(self, filters: Optional[Dict[str, Any]] = None) -> int:
        if not self.connection:
            raise RuntimeError("Database not connected")

        try:
            base_query = "SELECT COUNT(*) as count FROM memories WHERE 1=1"
            params = []

            if filters:
                if filters.get("project_id"):
                    base_query += " AND project_id = ?"
                    params.append(filters["project_id"])
                if filters.get("category"):
                    base_query += " AND category = ?"
                    params.append(filters["category"])
                if filters.get("source"):
                    base_query += " AND source = ?"
                    params.append(filters["source"])
                if filters.get("tag"):
                    base_query += " AND JSON_EXTRACT(tags, '$') LIKE ?"
                    params.append(f'%"{filters["tag"]}"%')

            result = await self.fetchone(base_query, tuple(params))
            return result["count"] if result else 0

        except Exception as e:
            logger.error(f"Count memories failed: {e}")
            raise

    async def add_memory(self, data: Dict[str, Any]) -> None:
        """memories 테이블에 메모리 레코드 삽입

        Args:
            data: Memory 모델의 dict (id, content, content_hash, project_id,
                  category, source, embedding, tags, created_at, updated_at)
        """
        await self.execute(
            """
            INSERT INTO memories
            (id, content, content_hash, project_id, category, source, client, embedding, tags, created_at, updated_at, content_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["id"],
                data["content"],
                data["content_hash"],
                data.get("project_id"),
                data.get("category", "task"),
                data.get("source", "unknown"),
                data.get("client"),
                data.get("embedding"),
                data.get("tags"),
                data["created_at"],
                data["updated_at"],
                len(data["content"]),  # denormalized; keeps content_bytes in sync
            ),
        )

    @asynccontextmanager
    async def transaction(self):
        async with self._connection.transaction():
            yield
