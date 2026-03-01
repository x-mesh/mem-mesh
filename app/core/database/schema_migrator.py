"""Automatic schema migration for mem-mesh.

This module handles automatic database schema migrations:
- Tracks schema version in database
- Auto-adds missing columns
- Runs versioned migration scripts

Similar to Prisma migrations but simpler for SQLite.
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Optional, Callable, Awaitable

if TYPE_CHECKING:
    from .connection import DatabaseConnection

logger = logging.getLogger(__name__)

# Current schema version - increment when adding new migrations
CURRENT_SCHEMA_VERSION = 4


class SchemaMigrator:
    """Handles automatic schema migrations.
    
    Features:
    - Version tracking in _schema_migrations table
    - Auto-detection and addition of missing columns
    - Ordered migration execution
    """

    def __init__(self, connection: "DatabaseConnection"):
        self.connection = connection
        self._migrations: Dict[int, Callable[["SchemaMigrator"], Awaitable[None]]] = {
            1: self._migration_v1_initial,
            2: self._migration_v2_work_tracking_columns,
            3: self._migration_v3_relation_tables,
            4: self._migration_v4_pin_columns_integrity,
        }

    async def migrate(self) -> None:
        """Run all pending migrations."""
        if not self.connection.connection:
            raise RuntimeError("Database not connected")

        # Ensure migrations table exists
        await self._ensure_migrations_table()
        
        current_version = await self._get_current_version()
        logger.info(f"Current schema version: {current_version}, target: {CURRENT_SCHEMA_VERSION}")

        if current_version >= CURRENT_SCHEMA_VERSION:
            logger.info("Schema is up to date")
            return

        # Run migrations in order
        for version in range(current_version + 1, CURRENT_SCHEMA_VERSION + 1):
            if version in self._migrations:
                logger.info(f"Running migration v{version}...")
                try:
                    await self._migrations[version](self)
                    await self._set_version(version)
                    self.connection.commit()
                    logger.info(f"Migration v{version} completed")
                except Exception as e:
                    logger.error(f"Migration v{version} failed: {e}")
                    raise

    async def _ensure_migrations_table(self) -> None:
        """Create migrations tracking table if not exists."""
        conn = self.connection.connection
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL,
                description TEXT
            )
        """)
        self.connection.commit()

    async def _get_current_version(self) -> int:
        """Get current schema version from database."""
        try:
            cursor = await self.connection.execute(
                "SELECT MAX(version) as version FROM _schema_migrations"
            )
            row = cursor.fetchone()
            return row["version"] if row and row["version"] else 0
        except Exception:
            return 0

    async def _set_version(self, version: int, description: str = "") -> None:
        """Record migration version."""
        await self.connection.execute(
            "DELETE FROM _schema_migrations WHERE version = ?", (version,)
        )
        await self.connection.execute(
            """
            INSERT INTO _schema_migrations (version, applied_at, description)
            VALUES (?, ?, ?)
            """,
            (version, datetime.now(timezone.utc).isoformat(), description)
        )

    async def _column_exists(self, table: str, column: str) -> bool:
        """Check if a column exists in a table."""
        try:
            cursor = await self.connection.execute(f"PRAGMA table_info({table})")
            columns = [row["name"] for row in cursor.fetchall()]
            return column in columns
        except Exception:
            return False

    async def _add_column_if_missing(
        self, 
        table: str, 
        column: str, 
        column_type: str,
        default: Optional[str] = None
    ) -> bool:
        """Add column to table if it doesn't exist.
        
        Returns True if column was added, False if already exists.
        """
        if await self._column_exists(table, column):
            logger.debug(f"Column {table}.{column} already exists")
            return False

        default_clause = f" DEFAULT {default}" if default is not None else ""
        sql = f"ALTER TABLE {table} ADD COLUMN {column} {column_type}{default_clause}"
        
        try:
            await self.connection.execute(sql)
            logger.info(f"Added column {table}.{column}")
            return True
        except Exception as e:
            logger.error(f"Failed to add column {table}.{column}: {e}")
            raise

    async def _table_exists(self, table: str) -> bool:
        """Check if a table exists."""
        cursor = await self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        )
        return cursor.fetchone() is not None

    # ========== Migration Definitions ==========

    async def _migration_v1_initial(self, migrator: "SchemaMigrator") -> None:
        """Initial migration - marks existing databases as v1."""
        # This migration just marks the baseline
        # All tables should already exist from initializer
        logger.info("Marking initial schema version")

    async def _migration_v2_work_tracking_columns(self, migrator: "SchemaMigrator") -> None:
        """Add work tracking columns that may be missing."""
        
        # pins table columns
        if await self._table_exists("pins"):
            await self._add_column_if_missing("pins", "promoted_to_memory_id", "TEXT", "NULL")
            await self._add_column_if_missing("pins", "auto_importance", "INTEGER", "0")
            await self._add_column_if_missing("pins", "estimated_tokens", "INTEGER", "0")
            await self._add_column_if_missing("pins", "user_id", "TEXT", "'default'")

        # sessions table columns
        if await self._table_exists("sessions"):
            await self._add_column_if_missing("sessions", "user_id", "TEXT", "'default'")
            await self._add_column_if_missing("sessions", "initial_context_tokens", "INTEGER", "0")
            await self._add_column_if_missing("sessions", "total_loaded_tokens", "INTEGER", "0")
            await self._add_column_if_missing("sessions", "total_saved_tokens", "INTEGER", "0")

        # projects table columns (if any new ones needed)
        if await self._table_exists("projects"):
            await self._add_column_if_missing("projects", "global_rules", "TEXT", "NULL")
            await self._add_column_if_missing("projects", "global_context", "TEXT", "NULL")

    async def _migration_v3_relation_tables(self, migrator: "SchemaMigrator") -> None:
        """Add memory_relations table for existing databases."""
        conn = self.connection.connection

        if not await self._table_exists("memory_relations"):
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_relations (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL DEFAULT 'related',
                    strength REAL NOT NULL DEFAULT 1.0,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (source_id) REFERENCES memories(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_id) REFERENCES memories(id) ON DELETE CASCADE
                )
            """)
            logger.info("Created memory_relations table via migration v3")

    async def _migration_v4_pin_columns_integrity(self, migrator: "SchemaMigrator") -> None:
        """Ensure all pin columns exist for databases that skipped earlier migrations."""
        if await self._table_exists("pins"):
            await self._add_column_if_missing("pins", "auto_importance", "INTEGER", "0")
            await self._add_column_if_missing("pins", "estimated_tokens", "INTEGER", "0")
            await self._add_column_if_missing("pins", "promoted_to_memory_id", "TEXT", "NULL")
            await self._add_column_if_missing("pins", "embedding", "BLOB", "NULL")
            await self._add_column_if_missing("pins", "user_id", "TEXT", "'default'")
            logger.info("Pin columns integrity check completed via migration v4")
