"""Database facade for mem-mesh - backward compatible interface.

This module provides the Database class that delegates to specialized modules:
- connection.py: Connection management, WAL mode, extension loading
- initializer.py: Table creation, schema setup
- migrator.py: Embedding migrations, metadata management

Requirements: 4.1, 4.4 - SQLite WAL mode and busy_timeout configuration
"""

import json
import logging
from typing import Any, Optional, Dict, List, Tuple
from contextlib import asynccontextmanager

import numpy as np

from .connection import DatabaseConnection, SQLITE_VEC_AVAILABLE, SQLITE3_MODULE
from .initializer import DatabaseInitializer
from .migrator import DatabaseMigrator

try:
    import pysqlite3.dbapi2 as sqlite3
except ImportError:
    import sqlite3

logger = logging.getLogger(__name__)

__all__ = ["Database", "SQLITE_VEC_AVAILABLE", "SQLITE3_MODULE"]


class Database:
    """SQLite + sqlite-vec database facade.

    Provides backward-compatible interface while delegating to specialized modules.

    Requirements:
    - 4.1: WAL mode enabled
    - 4.4: busy_timeout configuration
    """

    def __init__(self, db_path: str, busy_timeout: int = 5000, embedding_dim: int = 384):
        self.db_path = db_path
        self.busy_timeout = busy_timeout
        self.embedding_dim = embedding_dim
        self._connection = DatabaseConnection(db_path, busy_timeout)
        self._initializer = DatabaseInitializer(self._connection, embedding_dim)
        self._migrator = DatabaseMigrator(self._connection)

    @property
    def connection(self) -> Optional[sqlite3.Connection]:
        return self._connection.connection

    @property
    def _lock(self):
        return self._connection._lock

    async def connect(self) -> None:
        vec_loaded = await self._connection.connect()
        await self.init_tables()
        logger.info(f"Database connected: {self.db_path}")

    async def init_tables(self) -> None:
        await self._initializer.initialize_schema()
        if self._connection.is_vec_available:
            await self._migrator.migrate_embeddings_to_vector_table()

    async def close(self) -> None:
        await self._connection.close()

    async def execute(self, query: str, params: Tuple = ()) -> sqlite3.Cursor:
        return await self._connection.execute(query, params)

    async def fetchone(self, query: str, params: Tuple = ()) -> Optional[sqlite3.Row]:
        return await self._connection.fetchone(query, params)

    async def fetchall(self, query: str, params: Tuple = ()) -> List[sqlite3.Row]:
        return await self._connection.fetchall(query, params)

    async def get_embedding_metadata(self, key: str) -> Optional[str]:
        return await self._migrator.get_embedding_metadata(key)

    async def set_embedding_metadata(self, key: str, value: str) -> None:
        await self._migrator.set_embedding_metadata(key, value)

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
                cursor = await self.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='memory_embeddings'
                """)

                if cursor.fetchone():
                    embedding_array = np.frombuffer(embedding, dtype=np.float32)
                    embedding_json = json.dumps(embedding_array.tolist())

                    has_filters = bool(
                        filters
                        and (filters.get("project_id") or filters.get("category"))
                    )
                    inner_limit = limit * 5 if has_filters else limit

                    base_query = """
                        SELECT m.*, ve.distance 
                        FROM memories m
                        JOIN (
                            SELECT memory_id, distance 
                            FROM memory_embeddings 
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

                    cursor = await self.execute(base_query, tuple(params))
                    results = cursor.fetchall()

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

        cursor = await self.execute(base_query, tuple(params))
        return cursor.fetchall()

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

            cursor = await self.execute(base_query, tuple(params))
            return cursor.fetchall()

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

            cursor = await self.execute(base_query, tuple(params))
            result = cursor.fetchone()
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
            (id, content, content_hash, project_id, category, source, embedding, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["id"],
                data["content"],
                data["content_hash"],
                data.get("project_id"),
                data.get("category", "task"),
                data.get("source", "unknown"),
                data.get("embedding"),
                data.get("tags"),
                data["created_at"],
                data["updated_at"],
            ),
        )


    @asynccontextmanager
    async def transaction(self):
        async with self._connection.transaction():
            yield

    def __del__(self):
        if self._connection.connection:
            self._connection.connection.close()
