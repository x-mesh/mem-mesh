"""Database migration and embedding metadata management for mem-mesh.

This module handles embedding migrations and model consistency checks.
"""

import json
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Iterable, Optional

import numpy as np

if TYPE_CHECKING:
    from .connection import DatabaseConnection

logger = logging.getLogger(__name__)

_CURATED_VECTOR_TABLES = {
    "curated_results_vec_active",
    "curated_results_vec_next",
}
_RAW_VECTOR_TABLES = {
    "memory_embeddings",
    "memory_embeddings_b",
}


class DatabaseMigrator:
    """Handles database migrations and embedding metadata.

    Manages embedding model consistency and data migrations.
    """

    def __init__(self, connection: "DatabaseConnection"):
        self.connection = connection

    @staticmethod
    def _validate_curated_table(table_name: str) -> None:
        if table_name not in _CURATED_VECTOR_TABLES:
            raise ValueError(f"Invalid curated vector table: {table_name}")

    async def _table_sql(self, table_name: str) -> Optional[str]:
        self._validate_curated_table(table_name)
        return await self._allowed_table_sql(table_name)

    async def _raw_table_sql(self, table_name: str) -> Optional[str]:
        if table_name not in _RAW_VECTOR_TABLES:
            raise ValueError(f"Invalid raw vector table: {table_name}")
        return await self._allowed_table_sql(table_name)

    async def _allowed_table_sql(self, table_name: str) -> Optional[str]:
        row = await self.connection.fetchone(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )
        return str(row["sql"]) if row and row["sql"] else None

    @staticmethod
    def _declared_dimension(sql: Optional[str]) -> Optional[int]:
        if not sql:
            return None
        match = re.search(r"FLOAT\s*\[\s*(\d+)\s*\]", sql, re.IGNORECASE)
        return int(match.group(1)) if match else None

    @staticmethod
    def _value_dimension(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, memoryview):
            value = value.tobytes()
        if isinstance(value, (bytes, bytearray)):
            if len(value) % 4:
                return None
            return len(value) // 4
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                return None
            return len(parsed) if isinstance(parsed, list) else None
        try:
            return len(value)
        except TypeError:
            return None

    @staticmethod
    def _vector_insert_value(value: Any, use_vec: bool) -> Any:
        if isinstance(value, memoryview):
            value = value.tobytes()
        if use_vec:
            if isinstance(value, (bytes, bytearray)):
                values = np.frombuffer(value, dtype=np.float32).tolist()
            elif isinstance(value, str):
                values = json.loads(value)
            else:
                values = [float(item) for item in value]
            return json.dumps(values)
        if isinstance(value, str):
            return value.encode("utf-8")
        return value

    async def _recreate_curated_table(
        self, table_name: str, dimension: int, use_vec: Optional[bool] = None
    ) -> None:
        self._validate_curated_table(table_name)
        existing_sql = await self._table_sql(table_name)
        if use_vec is None:
            use_vec = bool(existing_sql and "USING VEC0" in existing_sql.upper())
            if existing_sql is None:
                use_vec = bool(self.connection.is_vec_available)
        await self.connection.execute(f"DROP TABLE IF EXISTS {table_name}")
        if use_vec:
            await self.connection.execute(
                f"CREATE VIRTUAL TABLE {table_name} USING vec0("
                f"result_id TEXT PRIMARY KEY, embedding FLOAT[{int(dimension)}])"
            )
        else:
            await self.connection.execute(
                f"CREATE TABLE {table_name} ("
                "result_id TEXT PRIMARY KEY, embedding BLOB NOT NULL)"
            )
        self.connection.commit()

    async def prepare_curated_next(self, dimension: int) -> None:
        await self._recreate_curated_table("curated_results_vec_next", dimension)

    async def invalidate_curated_next(self) -> None:
        if await self._table_sql("curated_results_vec_next") is not None:
            await self.connection.execute("DELETE FROM curated_results_vec_next")
            self.connection.commit()

    async def write_curated_next(
        self, result_id: str, embedding: Iterable[float]
    ) -> None:
        table_name = "curated_results_vec_next"
        sql = await self._table_sql(table_name)
        if sql is None:
            raise RuntimeError("curated next vector table is missing")
        values = [float(item) for item in embedding]
        use_vec = "USING VEC0" in sql.upper()
        await self.connection.execute(
            f"DELETE FROM {table_name} WHERE result_id = ?", (result_id,)
        )
        await self.connection.execute(
            f"INSERT INTO {table_name}(result_id, embedding) VALUES (?, ?)",
            (
                result_id,
                (
                    json.dumps(values)
                    if use_vec
                    else np.asarray(values, dtype=np.float32).tobytes()
                ),
            ),
        )

    async def validate_curated_next(
        self, expected_result_ids: Iterable[str], dimension: int
    ) -> bool:
        table_name = "curated_results_vec_next"
        sql = await self._table_sql(table_name)
        if sql is None:
            return False
        declared_dimension = self._declared_dimension(sql)
        if declared_dimension is not None and declared_dimension != int(dimension):
            return False
        rows = await self.connection.fetchall(
            f"SELECT result_id, embedding FROM {table_name}"
        )
        expected = {str(result_id) for result_id in expected_result_ids}
        actual = [str(row["result_id"]) for row in rows]
        if len(actual) != len(set(actual)) or len(actual) != len(expected):
            return False
        if set(actual) != expected:
            return False
        return all(
            self._value_dimension(row["embedding"]) == int(dimension) for row in rows
        )

    async def validate_raw_slot(
        self, table_name: str, expected_memory_ids: Iterable[str], dimension: int
    ) -> bool:
        sql = await self._raw_table_sql(table_name)
        if sql is None:
            return False
        declared_dimension = self._declared_dimension(sql)
        if declared_dimension is not None and declared_dimension != int(dimension):
            return False
        rows = await self.connection.fetchall(
            f"SELECT memory_id, embedding FROM {table_name}"
        )
        expected = {str(memory_id) for memory_id in expected_memory_ids}
        actual = [str(row["memory_id"]) for row in rows]
        if len(actual) != len(set(actual)) or len(actual) != len(expected):
            return False
        if set(actual) != expected:
            return False
        return all(
            self._value_dimension(row["embedding"]) == int(dimension) for row in rows
        )

    async def snapshot_curated_active(self) -> Dict[str, Any]:
        table_name = "curated_results_vec_active"
        sql = await self._table_sql(table_name)
        if sql is None:
            return {"exists": False, "sql": None, "rows": [], "dimension": None}
        rows = await self.connection.fetchall(
            f"SELECT result_id, embedding FROM {table_name}"
        )
        return {
            "exists": True,
            "sql": sql,
            "rows": [dict(row) for row in rows],
            "dimension": self._declared_dimension(sql),
            "use_vec": "USING VEC0" in sql.upper(),
        }

    async def promote_curated_next(self, dimension: int) -> Dict[str, Any]:
        async with self.connection.transaction():
            snapshot = await self.snapshot_curated_active()
            next_sql = await self._table_sql("curated_results_vec_next")
            if next_sql is None:
                raise RuntimeError("curated next vector table is missing")
            await self._recreate_curated_table(
                "curated_results_vec_active",
                dimension,
                use_vec="USING VEC0" in next_sql.upper(),
            )
            active_sql = await self._table_sql("curated_results_vec_active")
            use_vec = bool(active_sql and "USING VEC0" in active_sql.upper())
            rows = await self.connection.fetchall(
                "SELECT result_id, embedding FROM curated_results_vec_next"
            )
            for row in rows:
                await self.connection.execute(
                    "DELETE FROM curated_results_vec_active WHERE result_id = ?",
                    (row["result_id"],),
                )
                await self.connection.execute(
                    "INSERT INTO curated_results_vec_active(result_id, embedding) VALUES (?, ?)",
                    (
                        row["result_id"],
                        self._vector_insert_value(row["embedding"], use_vec),
                    ),
                )
            self.connection.commit()
            return snapshot

    async def restore_curated_active(self, snapshot: Dict[str, Any]) -> None:
        if not snapshot.get("exists"):
            await self.connection.execute(
                "DROP TABLE IF EXISTS curated_results_vec_active"
            )
            self.connection.commit()
            return
        rows = snapshot.get("rows") or []
        dimension = snapshot.get("dimension")
        if dimension is None:
            dimension = max(
                (self._value_dimension(row.get("embedding")) or 1 for row in rows),
                default=1,
            )
        await self._recreate_curated_table(
            "curated_results_vec_active",
            int(dimension),
            use_vec=bool(snapshot.get("use_vec")),
        )
        for row in rows:
            await self.connection.execute(
                "INSERT INTO curated_results_vec_active(result_id, embedding) VALUES (?, ?)",
                (
                    row["result_id"],
                    self._vector_insert_value(
                        row["embedding"], bool(snapshot.get("use_vec"))
                    ),
                ),
            )
        self.connection.commit()

    async def get_embedding_metadata(self, key: str) -> Optional[str]:
        """Get embedding metadata value by key."""
        try:
            row = await self.connection.fetchone(
                "SELECT value FROM embedding_metadata WHERE key = ?", (key,)
            )
            return row["value"] if row else None
        except Exception as e:
            logger.error(f"Failed to get embedding metadata: {e}")
            return None

    async def set_embedding_metadata(self, key: str, value: str) -> None:
        """Set embedding metadata value.

        Single atomic upsert (key is PRIMARY KEY) instead of DELETE + INSERT:
        in autocommit mode the old DELETE committed on its own, so a crash
        before the INSERT permanently lost the key — after which startup treated
        the model as unknown and silently re-stamped the current one, masking a
        real model/dim mismatch. (red-team C5)
        """
        try:
            await self.connection.execute(
                """
                INSERT INTO embedding_metadata (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, datetime.utcnow().isoformat() + "Z"),
            )
            self.connection.commit()
            logger.info(f"Embedding metadata set: {key}={value}")
        except Exception as e:
            logger.error(f"Failed to set embedding metadata: {e}")
            raise

    async def delete_embedding_metadata(self, key: str) -> None:
        """Delete a metadata row by key (no-op if absent)."""
        try:
            await self.connection.execute(
                "DELETE FROM embedding_metadata WHERE key = ?", (key,)
            )
            self.connection.commit()
        except Exception as e:
            logger.error(f"Failed to delete embedding metadata: {e}")
            raise

    async def check_embedding_model_consistency(
        self, current_model: str, current_dim: int
    ) -> dict:
        """Check if current embedding model matches stored metadata.

        Returns:
            dict with keys: consistent, stored_model, stored_dim, current_model,
            current_dim, needs_migration, message
        """
        stored_model = await self.get_embedding_metadata("embedding_model")
        stored_dim_str = await self.get_embedding_metadata("embedding_dimension")
        stored_dim = int(stored_dim_str) if stored_dim_str else None

        result = {
            "consistent": True,
            "stored_model": stored_model,
            "stored_dim": stored_dim,
            "current_model": current_model,
            "current_dim": current_dim,
            "needs_migration": False,
            "message": "",
        }

        if stored_model is None:
            cursor = await self.connection.execute(
                "SELECT COUNT(*) as count FROM memories"
            )
            count = cursor.fetchone()["count"]

            if count > 0:
                result["message"] = (
                    f"Existing {count} memories found without model metadata. "
                    f"Setting current model ({current_model})."
                )
                logger.warning(result["message"])
                await self.set_embedding_metadata("embedding_model", current_model)
                await self.set_embedding_metadata(
                    "embedding_dimension", str(current_dim)
                )
            else:
                result["message"] = (
                    f"New database. Embedding model: {current_model} (dim: {current_dim})"
                )
                await self.set_embedding_metadata("embedding_model", current_model)
                await self.set_embedding_metadata(
                    "embedding_dimension", str(current_dim)
                )

            return result

        if stored_model != current_model:
            result["consistent"] = False
            result["needs_migration"] = True
            result["message"] = (
                f"Embedding model mismatch! DB: {stored_model}, Current: {current_model}. "
                f"Migration required: python scripts/migrate_embeddings.py"
            )
            logger.warning(result["message"])
        elif stored_dim and stored_dim != current_dim:
            result["consistent"] = False
            result["needs_migration"] = True
            result["message"] = (
                f"Embedding dimension mismatch! DB: {stored_dim}, Current: {current_dim}. "
                f"Migration required."
            )
            logger.warning(result["message"])
        else:
            result["message"] = (
                f"Embedding model consistent: {current_model} (dim: {current_dim})"
            )
            logger.info(result["message"])

        return result

    async def migrate_embeddings_to_vector_table(self) -> int:
        """Migrate existing embeddings to sqlite-vec vector table.

        Skips migration if:
        - No memories with embeddings exist
        - Vector table already has entries
        - BLOB dimension doesn't match vector table dimension (pending model migration)

        Returns:
            Number of embeddings migrated
        """
        try:
            cursor = await self.connection.execute(
                "SELECT id, embedding FROM memories WHERE embedding IS NOT NULL"
            )
            memories = cursor.fetchall()

            if not memories:
                logger.info("No memories with embeddings found for migration")
                return 0

            # Active blue-green slot (mirrors base.EMBEDDING_TABLE_*; migrator is
            # imported by base, so it can't import back without a cycle).
            active_table = await self.get_embedding_metadata("active_embedding_table")
            if active_table not in ("memory_embeddings", "memory_embeddings_b"):
                active_table = "memory_embeddings"

            cursor = await self.connection.execute(
                f"SELECT COUNT(*) as count FROM {active_table}"
            )
            existing_count = cursor.fetchone()["count"]

            if existing_count > 0:
                logger.info(
                    f"Vector table already has {existing_count} embeddings, skipping migration"
                )
                return 0

            # Check dimension compatibility: BLOB dim vs vector table dim
            # If a model migration is pending, BLOB dim won't match the new table dim
            first_blob = memories[0]["embedding"]
            blob_dim = len(np.frombuffer(first_blob, dtype=np.float32))
            table_dim_str = await self.get_embedding_metadata("embedding_dimension")
            target_dim_str = await self.get_embedding_metadata(
                "target_embedding_dimension"
            )
            target_dim = int(target_dim_str) if target_dim_str else None
            if target_dim and target_dim != blob_dim:
                logger.info(
                    f"Skipping auto-migration: BLOB dim ({blob_dim}) != target dim ({target_dim}), "
                    f"model migration pending"
                )
                return 0
            table_dim = int(table_dim_str) if table_dim_str else blob_dim
            if blob_dim != table_dim:
                logger.info(
                    f"Skipping auto-migration: BLOB dim ({blob_dim}) != table dim ({table_dim}), "
                    f"model migration required"
                )
                return 0

            migrated_count = 0
            for memory in memories:
                try:
                    embedding_array = np.frombuffer(
                        memory["embedding"], dtype=np.float32
                    )
                    embedding_json = json.dumps(embedding_array.tolist())

                    # sqlite-vec virtual tables don't support INSERT OR REPLACE
                    await self.connection.execute(
                        f"DELETE FROM {active_table} WHERE memory_id = ?",
                        (memory["id"],),
                    )
                    await self.connection.execute(
                        f"INSERT INTO {active_table} (memory_id, embedding) VALUES (?, ?)",
                        (memory["id"], embedding_json),
                    )
                    migrated_count += 1

                except Exception as e:
                    logger.warning(
                        f"Failed to migrate embedding for memory {memory['id']}: {e}"
                    )
                    continue

            self.connection.commit()
            logger.info(
                f"Successfully migrated {migrated_count} embeddings to vector table"
            )
            return migrated_count

        except Exception as e:
            logger.error(f"Embedding migration failed: {e}")
            return 0
