"""Database migration and embedding metadata management for mem-mesh.

This module handles embedding migrations and model consistency checks.
"""

import json
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .connection import DatabaseConnection

logger = logging.getLogger(__name__)


class DatabaseMigrator:
    """Handles database migrations and embedding metadata.

    Manages embedding model consistency and data migrations.
    """

    def __init__(self, connection: "DatabaseConnection"):
        self.connection = connection

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
        """Set embedding metadata value."""
        try:
            await self.connection.execute(
                "DELETE FROM embedding_metadata WHERE key = ?", (key,)
            )
            await self.connection.execute(
                """
                INSERT INTO embedding_metadata (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, datetime.utcnow().isoformat() + "Z"),
            )
            self.connection.commit()
            logger.info(f"Embedding metadata set: {key}={value}")
        except Exception as e:
            logger.error(f"Failed to set embedding metadata: {e}")
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

            cursor = await self.connection.execute(
                "SELECT COUNT(*) as count FROM memory_embeddings"
            )
            existing_count = cursor.fetchone()["count"]

            if existing_count > 0:
                logger.info(
                    f"Vector table already has {existing_count} embeddings, skipping migration"
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
                        "DELETE FROM memory_embeddings WHERE memory_id = ?",
                        (memory["id"],),
                    )
                    await self.connection.execute(
                        "INSERT INTO memory_embeddings (memory_id, embedding) VALUES (?, ?)",
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
