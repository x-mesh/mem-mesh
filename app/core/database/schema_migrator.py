"""Automatic schema migration for mem-mesh.

This module handles automatic database schema migrations:
- Tracks schema version in database
- Auto-adds missing columns
- Runs versioned migration scripts

Similar to Prisma migrations but simpler for SQLite.
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Awaitable, Callable, Dict, Optional

if TYPE_CHECKING:
    from .connection import DatabaseConnection

logger = logging.getLogger(__name__)

# Current schema version - increment when adding new migrations
CURRENT_SCHEMA_VERSION = 14


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
            5: self._migration_v5_client_column,
            6: self._migration_v6_session_ide_columns,
            7: self._migration_v7_pin_client_column,
            8: self._migration_v8_pin_staging_column,
            9: self._migration_v9_content_bytes,
            10: self._migration_v10_access_tracking,
            11: self._migration_v11_reconcile,
            12: self._migration_v12_injection_anchors,
            13: self._migration_v13_injection_utilization,
            14: self._migration_v14_stale_status,
        }

    async def migrate(self) -> None:
        """Run all pending migrations."""
        if not self.connection.connection:
            raise RuntimeError("Database not connected")

        # Ensure migrations table exists
        await self._ensure_migrations_table()

        current_version = await self._get_current_version()
        logger.info(
            f"Current schema version: {current_version}, target: {CURRENT_SCHEMA_VERSION}"
        )

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
        except Exception as e:
            logger.debug(f"Failed to get schema version, assuming 0: {e}")
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
            (version, datetime.now(timezone.utc).isoformat(), description),
        )

    async def _column_exists(self, table: str, column: str) -> bool:
        """Check if a column exists in a table."""
        try:
            cursor = await self.connection.execute(f"PRAGMA table_info({table})")
            columns = [row["name"] for row in cursor.fetchall()]
            return column in columns
        except Exception as e:
            logger.debug(f"Failed to check column existence: {e}")
            return False

    async def _add_column_if_missing(
        self, table: str, column: str, column_type: str, default: Optional[str] = None
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
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        return cursor.fetchone() is not None

    # ========== Migration Definitions ==========

    async def _migration_v1_initial(self, migrator: "SchemaMigrator") -> None:
        """Initial migration - marks existing databases as v1."""
        # This migration just marks the baseline
        # All tables should already exist from initializer
        logger.info("Marking initial schema version")

    async def _migration_v2_work_tracking_columns(
        self, migrator: "SchemaMigrator"
    ) -> None:
        """Add work tracking columns that may be missing."""

        # pins table columns
        if await self._table_exists("pins"):
            await self._add_column_if_missing(
                "pins", "promoted_to_memory_id", "TEXT", "NULL"
            )
            await self._add_column_if_missing("pins", "auto_importance", "INTEGER", "0")
            await self._add_column_if_missing(
                "pins", "estimated_tokens", "INTEGER", "0"
            )
            await self._add_column_if_missing("pins", "user_id", "TEXT", "'default'")

        # sessions table columns
        if await self._table_exists("sessions"):
            await self._add_column_if_missing(
                "sessions", "user_id", "TEXT", "'default'"
            )
            await self._add_column_if_missing(
                "sessions", "initial_context_tokens", "INTEGER", "0"
            )
            await self._add_column_if_missing(
                "sessions", "total_loaded_tokens", "INTEGER", "0"
            )
            await self._add_column_if_missing(
                "sessions", "total_saved_tokens", "INTEGER", "0"
            )

        # projects table columns (if any new ones needed)
        if await self._table_exists("projects"):
            await self._add_column_if_missing(
                "projects", "global_rules", "TEXT", "NULL"
            )
            await self._add_column_if_missing(
                "projects", "global_context", "TEXT", "NULL"
            )

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

    async def _migration_v4_pin_columns_integrity(
        self, migrator: "SchemaMigrator"
    ) -> None:
        """Ensure all pin columns exist for databases that skipped earlier migrations."""
        if await self._table_exists("pins"):
            await self._add_column_if_missing("pins", "auto_importance", "INTEGER", "0")
            await self._add_column_if_missing(
                "pins", "estimated_tokens", "INTEGER", "0"
            )
            await self._add_column_if_missing(
                "pins", "promoted_to_memory_id", "TEXT", "NULL"
            )
            await self._add_column_if_missing("pins", "embedding", "BLOB", "NULL")
            await self._add_column_if_missing("pins", "user_id", "TEXT", "'default'")
            logger.info("Pin columns integrity check completed via migration v4")

    async def _migration_v5_client_column(self, migrator: "SchemaMigrator") -> None:
        """Add client column to memories table for tracking creation tool."""
        if await self._table_exists("memories"):
            await self._add_column_if_missing("memories", "client", "TEXT", "NULL")
            logger.info("Added client column to memories table via migration v5")

    async def _migration_v6_session_ide_columns(
        self, migrator: "SchemaMigrator"
    ) -> None:
        """Add IDE session tracking columns to sessions table.

        - ide_session_id: Maps to the IDE's native session ID (e.g. Claude Code session_id)
        - client_type: Identifies the IDE/tool (e.g. 'claude-ai', 'Cursor', 'Windsurf')
        """
        if await self._table_exists("sessions"):
            await self._add_column_if_missing(
                "sessions", "ide_session_id", "TEXT", "NULL"
            )
            await self._add_column_if_missing("sessions", "client_type", "TEXT", "NULL")
            logger.info(
                "Added ide_session_id, client_type columns to sessions table "
                "via migration v6"
            )

    async def _migration_v7_pin_client_column(self, migrator: "SchemaMigrator") -> None:
        """Add client column to pins table for tracking creation source."""
        if await self._table_exists("pins"):
            await self._add_column_if_missing("pins", "client", "TEXT", "NULL")
            logger.info("Added client column to pins table via migration v7")

    async def _migration_v8_pin_staging_column(
        self, migrator: "SchemaMigrator"
    ) -> None:
        """Add is_staging column to pins table for staging pin support."""
        if await self._table_exists("pins"):
            await self._add_column_if_missing("pins", "is_staging", "INTEGER", "0")
            logger.info("Added is_staging column to pins table via migration v8")

    async def _migration_v9_content_bytes(self, migrator: "SchemaMigrator") -> None:
        """Add denormalized content_bytes (= LENGTH(content)) to memories.

        Per-project size aggregates can then SUM(content_bytes) instead of
        SUM(LENGTH(content)). The latter forced a full table scan that paged in
        the inline ~4KB embedding BLOB on every row (~159ms on a 16k-row DB);
        summing the narrow integer column avoids touching the payload. Backfills
        existing rows; the column is kept in sync by add_memory on insert
        (memories are immutable — updates are delete+insert).
        """
        if await self._table_exists("memories"):
            await self._add_column_if_missing(
                "memories", "content_bytes", "INTEGER", "NULL"
            )
            # Idempotent backfill: only fills rows that don't have it yet.
            await self.connection.execute(
                "UPDATE memories SET content_bytes = LENGTH(content) "
                "WHERE content_bytes IS NULL"
            )
            logger.info("Added + backfilled content_bytes on memories via migration v9")

    async def _migration_v10_access_tracking(self, migrator: "SchemaMigrator") -> None:
        """Add recall-tracking columns to memories for usage analytics.

        - access_count: number of times the memory was surfaced by a search.
        - last_accessed_at: ISO8601 timestamp of the most recent surfacing.

        These power the Analytics "recall" panel (most-recalled memories, dead
        memories that were stored but never retrieved). The columns default so
        existing rows and add_memory inserts (which omit them) stay valid; the
        search hot path increments them best-effort on every non-empty query.
        """
        if await self._table_exists("memories"):
            await self._add_column_if_missing(
                "memories", "access_count", "INTEGER", "0"
            )
            await self._add_column_if_missing(
                "memories", "last_accessed_at", "TEXT", "NULL"
            )
            # Idempotent backfill: NULL access_count -> 0 so analytics SQL can
            # treat "never recalled" uniformly without COALESCE everywhere.
            await self.connection.execute(
                "UPDATE memories SET access_count = 0 WHERE access_count IS NULL"
            )
            logger.info(
                "Added access_count/last_accessed_at on memories via migration v10"
            )

    async def _migration_v11_reconcile(self, migrator: "SchemaMigrator") -> None:
        """Write-time reconcile foundation (SSOT #3).

        - memories.status: 'canonical' (default, search-visible) | 'deprecated'
          (superseded, hidden after human approval). Backfill-safe default so
          existing rows and add_memory inserts stay valid.
        - reconcile_queue: mirrors relay_queue_item's lease columns (status/
          attempts/next_attempt_at/locked_by/locked_at/last_error) for the async
          reconcile worker. UNIQUE(new_memory_id, old_memory_id) holds the
          many-to-many conflict set (one new vs N old) — a per-pair row, not
          UNIQUE(new_memory_id) which would silent-drop the 2nd+ candidate (C1).
          new/old content_hash snapshots let the worker revalidate at apply time
          and skip rows whose memories were edited/deleted in between (C2 TOCTOU).
        """
        if await self._table_exists("memories"):
            await self._add_column_if_missing(
                "memories", "status", "TEXT", "'canonical'"
            )
            await self.connection.execute(
                "UPDATE memories SET status = 'canonical' WHERE status IS NULL"
            )
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS reconcile_queue (
                id TEXT PRIMARY KEY,
                new_memory_id TEXT NOT NULL,
                old_memory_id TEXT NOT NULL,
                project_id TEXT,
                similarity REAL,
                new_content_hash TEXT,
                old_content_hash TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL DEFAULT 0,
                locked_by TEXT,
                locked_at REAL,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(new_memory_id, old_memory_id),
                FOREIGN KEY (new_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                FOREIGN KEY (old_memory_id) REFERENCES memories(id) ON DELETE CASCADE
            )
            """)
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_reconcile_queue_claim "
            "ON reconcile_queue(status, next_attempt_at, created_at)"
        )
        logger.info("Added memories.status + reconcile_queue via migration v11")

    async def _migration_v12_injection_anchors(
        self, migrator: "SchemaMigrator"
    ) -> None:
        """Injection instrumentation (M2) + memory anchors (M3) foundation.

        - injected_memories: records every memory surfaced into an IDE session,
          keyed by (ide_session_id, memory_id), so injection effectiveness can be
          measured per turn/position. Written by the injection path (t8), queried
          by the effectiveness analytics (t11). No FK to memories: an injected
          memory may be deleted later, but its injection event should still count.
        - memories.anchors: JSON blob {commit_hash, file_paths, branch} pinning a
          memory to the code state it was captured against. NULL default so
          existing rows and add_memory inserts (which omit it) stay valid.
        """
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS injected_memories (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                ide_session_id TEXT NOT NULL,
                memory_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL DEFAULT 0,
                position INTEGER NOT NULL DEFAULT 0,
                injected_via TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """)
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_injected_memories_session "
            "ON injected_memories(ide_session_id, memory_id)"
        )
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_injected_memories_project_created "
            "ON injected_memories(project_id, created_at)"
        )
        if await self._table_exists("memories"):
            await self._add_column_if_missing("memories", "anchors", "TEXT", "NULL")
        logger.info(
            "Added injected_memories table + memories.anchors via migration v12"
        )

    async def _migration_v13_injection_utilization(
        self, migrator: "SchemaMigrator"
    ) -> None:
        """Injection *utilization* verdict columns on injected_memories (t9).

        v12 recorded what was *injected*; this records whether it was *utilized*.
        The Stop-time judge (HookService.judge_injected) writes one verdict per
        injected row so the weekly review can report an injection hit rate even
        for users with no LLM judge configured — a conservative deterministic
        proxy is better than no signal.

        - utilized: NULL = not yet judged, 0 = judged unused, 1 = judged used.
          NULL default so the v12 rows already on disk stay unjudged until the
          next Stop sweeps them.
        - judged_at: ISO8601 timestamp the verdict was written.
        - judge_method: how the verdict was reached — 'id_ref' | 'keyword' |
          'activity_only' | 'none' (deterministic), reserved for a future
          'llm' method.

        Added via _add_column_if_missing (not folded into the v12 DDL) so a dev
        DB already migrated to v12 gains the columns without a table rebuild.
        """
        if await self._table_exists("injected_memories"):
            await self._add_column_if_missing(
                "injected_memories", "utilized", "INTEGER", "NULL"
            )
            await self._add_column_if_missing(
                "injected_memories", "judged_at", "TEXT", "NULL"
            )
            await self._add_column_if_missing(
                "injected_memories", "judge_method", "TEXT", "NULL"
            )
            logger.info(
                "Added utilized/judged_at/judge_method on injected_memories "
                "via migration v13"
            )

    async def _migration_v14_stale_status(self, migrator: "SchemaMigrator") -> None:
        """Anchor-verification stale columns on memories (t12 — 2-stage stale).

        The server has no git access, so it can only compute a weak *age* signal
        from anchors + created_at at read time (no column needed for that). The
        strong signal is a client that locally verified a memory's anchors
        (file_paths exist, commit reachable) and reported the verdict via the
        ``report_anchor_status`` tool — that verdict is persisted here.

        - stale_status: NULL = never client-verified, 'fresh' = verified intact,
          'stale' = verified rotten (files gone / commit unreachable). A 'stale'
          memory is excluded from auto-injection; 'fresh' clears the weak
          aged-anchor warning. NULL default so v12/v13 rows already on disk stay
          unverified until the next report.
        - stale_checked_at: ISO8601 timestamp the verdict was written.

        Added via _add_column_if_missing (idempotent) so a fresh DB that already
        got the columns from the initializer, and an existing DB that did not,
        both converge without a table rebuild.
        """
        if await self._table_exists("memories"):
            await self._add_column_if_missing(
                "memories", "stale_status", "TEXT", "NULL"
            )
            await self._add_column_if_missing(
                "memories", "stale_checked_at", "TEXT", "NULL"
            )
            logger.info(
                "Added stale_status/stale_checked_at on memories via migration v14"
            )
