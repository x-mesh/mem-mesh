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
    "category_filter_clause",
    "anchored_path_filter_clause",
]


def category_filter_clause(cat, column: str = "category"):
    """SQL condition + params for a category filter that may be a single string
    (``category = ?``) or a list/tuple/set of categories (``category IN (?, ...)``).
    Returns (condition_without_AND, params_list). Empty ('', []) when no filter.
    """
    if not cat:
        return "", []
    if isinstance(cat, (list, tuple, set)):
        cats = [c for c in cat if c]
        if not cats:
            return "", []
        placeholders = ",".join("?" * len(cats))
        return f"{column} IN ({placeholders})", list(cats)
    return f"{column} = ?", [cat]


def anchored_path_filter_clause(prefix, column: str = "anchors"):
    """SQL condition + params matching memories whose ``anchors.file_paths``
    contains ``prefix`` exactly or any path under it (directory boundary):
    'app/core' matches 'app/core/x.py' but NOT 'app/core_utils/x.py'.

    Uses ``json_each`` on the anchors JSON TEXT column. Guarded with
    ``json_valid`` because ``json_each`` aborts the whole query on corrupt
    JSON (legacy rows may hold malformed values). Stored values get their
    backslashes normalized in SQL (legacy rows from Windows clients predate
    write-side normalization), and the prefix match uses ``substr`` — not
    LIKE — so matching stays case-sensitive, in parity with the Python
    mirror ``_matches_anchored_path``.
    Returns (condition_without_AND, params_list). Empty ('', []) when no filter.
    """
    if not prefix:
        return "", []
    normalized = str(prefix).replace("\\", "/").strip().rstrip("/")
    if not normalized:
        return "", []
    value_expr = "REPLACE(json_each.value, '\\', '/')"
    condition = (
        f"({column} IS NOT NULL AND json_valid({column}) AND EXISTS ("
        f"SELECT 1 FROM json_each({column}, '$.file_paths') "
        f"WHERE {value_expr} = ? OR substr({value_expr}, 1, ?) = ?))"
    )
    return condition, [normalized, len(normalized) + 1, normalized + "/"]


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
                        and (
                            filters.get("project_id")
                            or filters.get("category")
                            or filters.get("anchored_path")
                        )
                    )
                    # anchored_path is highly selective (anchored memories are a
                    # small fraction of rows) — widen the KNN candidate pool
                    # further so the post-JOIN filter doesn't starve the top-K.
                    if filters and filters.get("anchored_path"):
                        inner_limit = limit * 20
                    else:
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

                    # Reconcile: hide deprecated (superseded) memories from search.
                    # Applied unconditionally, not only when other filters exist.
                    filter_conditions = [
                        "COALESCE(m.status, 'canonical') = 'canonical'"
                    ]
                    if filters:
                        if filters.get("project_id"):
                            filter_conditions.append("m.project_id = ?")
                            params.append(filters["project_id"])
                        if filters.get("category"):
                            _cond, _cp = category_filter_clause(
                                filters["category"], column="m.category"
                            )
                            if _cond:
                                filter_conditions.append(_cond)
                                params.extend(_cp)
                        if filters.get("anchored_path"):
                            _cond, _cp = anchored_path_filter_clause(
                                filters["anchored_path"], column="m.anchors"
                            )
                            if _cond:
                                filter_conditions.append(_cond)
                                params.extend(_cp)

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
        # Mirror the vec path's reconcile filter: this fallback runs when
        # sqlite-vec is unavailable or the vector table is empty, and it must
        # not surface deprecated (superseded) memories either.
        base_query = (
            "SELECT * FROM memories WHERE 1=1 "
            "AND COALESCE(status, 'canonical') = 'canonical'"
        )
        params = []

        if filters:
            if filters.get("project_id"):
                base_query += " AND project_id = ?"
                params.append(filters["project_id"])
            if filters.get("category"):
                _cond, _cp = category_filter_clause(filters["category"])
                if _cond:
                    base_query += " AND " + _cond
                    params.extend(_cp)
            if filters.get("anchored_path"):
                _cond, _cp = anchored_path_filter_clause(filters["anchored_path"])
                if _cond:
                    base_query += " AND " + _cond
                    params.extend(_cp)

        base_query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        return await self.fetchall(base_query, tuple(params))

    async def _table_exists(self, name: str) -> bool:
        row = await self.fetchone(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        return row is not None

    async def _tag_filter_sql(self, tag: str) -> Tuple[str, list]:
        """AND-clause matching ``tag`` in source tags (memories.tags) OR the
        enrichment topic tags (memory_enrichment.tags), so a faceted enrichment
        tag filters correctly. The enrichment leg is added only when its (lazy)
        table exists."""
        like = f'%"{tag}"%'
        if await self._table_exists("memory_enrichment"):
            return (
                " AND (JSON_EXTRACT(tags, '$') LIKE ? OR EXISTS ("
                "SELECT 1 FROM memory_enrichment e "
                "WHERE e.memory_id = memories.id "
                "AND JSON_EXTRACT(e.tags, '$') LIKE ?))",
                [like, like],
            )
        return (" AND JSON_EXTRACT(tags, '$') LIKE ?", [like])

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
            base_query = (
                "SELECT * FROM memories WHERE 1=1 "
                "AND COALESCE(status, 'canonical') = 'canonical'"
            )
            params = []

            if filters:
                if filters.get("project_id"):
                    base_query += " AND project_id = ?"
                    params.append(filters["project_id"])
                if filters.get("category"):
                    _cond, _cp = category_filter_clause(filters["category"])
                    if _cond:
                        base_query += " AND " + _cond
                        params.extend(_cp)
                if filters.get("source"):
                    base_query += " AND source = ?"
                    params.append(filters["source"])
                if filters.get("tag"):
                    _tc, _tp = await self._tag_filter_sql(filters["tag"])
                    base_query += _tc
                    params.extend(_tp)
                if filters.get("anchored_path"):
                    _cond, _cp = anchored_path_filter_clause(filters["anchored_path"])
                    if _cond:
                        base_query += " AND " + _cond
                        params.extend(_cp)

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
            base_query = (
                "SELECT COUNT(*) as count FROM memories WHERE 1=1 "
                "AND COALESCE(status, 'canonical') = 'canonical'"
            )
            params = []

            if filters:
                if filters.get("project_id"):
                    base_query += " AND project_id = ?"
                    params.append(filters["project_id"])
                if filters.get("category"):
                    _cond, _cp = category_filter_clause(filters["category"])
                    if _cond:
                        base_query += " AND " + _cond
                        params.extend(_cp)
                if filters.get("source"):
                    base_query += " AND source = ?"
                    params.append(filters["source"])
                if filters.get("tag"):
                    _tc, _tp = await self._tag_filter_sql(filters["tag"])
                    base_query += _tc
                    params.extend(_tp)
                if filters.get("anchored_path"):
                    _cond, _cp = anchored_path_filter_clause(filters["anchored_path"])
                    if _cond:
                        base_query += " AND " + _cond
                        params.extend(_cp)

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
            (id, content, content_hash, project_id, category, status, source, client, embedding, tags, anchors, created_at, updated_at, content_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["id"],
                data["content"],
                data["content_hash"],
                data.get("project_id"),
                data.get("category", "task"),
                data.get("status", "canonical"),
                data.get("source", "unknown"),
                data.get("client"),
                data.get("embedding"),
                data.get("tags"),
                data.get("anchors"),
                data["created_at"],
                data["updated_at"],
                len(data["content"]),  # denormalized; keeps content_bytes in sync
            ),
        )

    @asynccontextmanager
    async def transaction(self):
        async with self._connection.transaction():
            yield
