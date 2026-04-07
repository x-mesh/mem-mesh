#!/usr/bin/env python3
"""Database schema migration: context-token-optimization

This script performs database schema changes for the context-token-optimization feature:
1. Add token tracking columns to the pins table
2. Add token tracking columns to the sessions table
3. Create new session_stats table
4. Create new token_usage table
5. Create required indexes

Requirements: 10.1, 10.2, 10.3
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database.connection import DatabaseConnection
from app.core.config import Settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ContextTokenOptimizationMigrator:
    """Database migrator for the context-token-optimization feature"""

    def __init__(self, db_path: str, dry_run: bool = False):
        self.db_path = db_path
        self.dry_run = dry_run
        self.connection = DatabaseConnection(db_path)
        self.changes_made = []

    async def connect(self):
        """Connect to the database"""
        await self.connection.connect()
        logger.info(f"Connected to database: {self.db_path}")

    async def close(self):
        """Close the database connection"""
        await self.connection.close()
        logger.info("Database connection closed")

    async def check_column_exists(self, table: str, column: str) -> bool:
        """Check if a column exists in a table"""
        cursor = await self.connection.execute(
            f"PRAGMA table_info({table})"
        )
        columns = cursor.fetchall()
        return any(col['name'] == column for col in columns)

    async def check_table_exists(self, table: str) -> bool:
        """Check if a table exists"""
        cursor = await self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        )
        return cursor.fetchone() is not None

    async def check_index_exists(self, index: str) -> bool:
        """Check if an index exists"""
        cursor = await self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (index,)
        )
        return cursor.fetchone() is not None

    async def migrate_pins_table(self):
        """Add token tracking columns to the pins table"""
        logger.info("Migrating pins table...")

        columns_to_add = [
            ("estimated_tokens", "INTEGER DEFAULT 0"),
            ("promoted_to_memory_id", "TEXT"),
            ("auto_importance", "INTEGER DEFAULT 0"),  # BOOLEAN as INTEGER
        ]

        for column_name, column_def in columns_to_add:
            if await self.check_column_exists("pins", column_name):
                logger.info(f"  Column 'pins.{column_name}' already exists, skipping")
                continue

            sql = f"ALTER TABLE pins ADD COLUMN {column_name} {column_def}"

            if self.dry_run:
                logger.info(f"  [DRY RUN] Would execute: {sql}")
                self.changes_made.append(f"ADD pins.{column_name}")
            else:
                await self.connection.execute(sql)
                self.connection.commit()
                logger.info(f"  ✓ Added column 'pins.{column_name}'")
                self.changes_made.append(f"ADD pins.{column_name}")

    async def migrate_sessions_table(self):
        """Add token tracking columns to the sessions table"""
        logger.info("Migrating sessions table...")

        columns_to_add = [
            ("initial_context_tokens", "INTEGER DEFAULT 0"),
            ("total_loaded_tokens", "INTEGER DEFAULT 0"),
            ("total_saved_tokens", "INTEGER DEFAULT 0"),
        ]

        for column_name, column_def in columns_to_add:
            if await self.check_column_exists("sessions", column_name):
                logger.info(f"  Column 'sessions.{column_name}' already exists, skipping")
                continue

            sql = f"ALTER TABLE sessions ADD COLUMN {column_name} {column_def}"

            if self.dry_run:
                logger.info(f"  [DRY RUN] Would execute: {sql}")
                self.changes_made.append(f"ADD sessions.{column_name}")
            else:
                await self.connection.execute(sql)
                self.connection.commit()
                logger.info(f"  ✓ Added column 'sessions.{column_name}'")
                self.changes_made.append(f"ADD sessions.{column_name}")

    async def create_session_stats_table(self):
        """Create the session_stats table"""
        logger.info("Creating session_stats table...")

        if await self.check_table_exists("session_stats"):
            logger.info("  Table 'session_stats' already exists, skipping")
            return

        sql = """
            CREATE TABLE IF NOT EXISTS session_stats (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                tokens_loaded INTEGER NOT NULL,
                tokens_saved INTEGER NOT NULL,
                context_depth INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """

        if self.dry_run:
            logger.info(f"  [DRY RUN] Would execute: {sql}")
            self.changes_made.append("CREATE session_stats")
        else:
            await self.connection.execute(sql)
            self.connection.commit()
            logger.info("  ✓ Created table 'session_stats'")
            self.changes_made.append("CREATE session_stats")

    async def create_token_usage_table(self):
        """Create the token_usage table"""
        logger.info("Creating token_usage table...")

        if await self.check_table_exists("token_usage"):
            logger.info("  Table 'token_usage' already exists, skipping")
            return

        sql = """
            CREATE TABLE IF NOT EXISTS token_usage (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                session_id TEXT,
                operation_type TEXT NOT NULL,
                query TEXT,
                tokens_used INTEGER NOT NULL,
                tokens_saved INTEGER DEFAULT 0,
                optimization_applied INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
            )
        """

        if self.dry_run:
            logger.info(f"  [DRY RUN] Would execute: {sql}")
            self.changes_made.append("CREATE token_usage")
        else:
            await self.connection.execute(sql)
            self.connection.commit()
            logger.info("  ✓ Created table 'token_usage'")
            self.changes_made.append("CREATE token_usage")

    async def create_indexes(self):
        """Create required indexes"""
        logger.info("Creating indexes...")

        indexes = [
            # session_stats indexes
            ("idx_session_stats_session", "CREATE INDEX IF NOT EXISTS idx_session_stats_session ON session_stats(session_id)"),
            ("idx_session_stats_timestamp", "CREATE INDEX IF NOT EXISTS idx_session_stats_timestamp ON session_stats(timestamp)"),
            ("idx_session_stats_event_type", "CREATE INDEX IF NOT EXISTS idx_session_stats_event_type ON session_stats(event_type)"),

            # token_usage indexes
            ("idx_token_usage_project", "CREATE INDEX IF NOT EXISTS idx_token_usage_project ON token_usage(project_id)"),
            ("idx_token_usage_session", "CREATE INDEX IF NOT EXISTS idx_token_usage_session ON token_usage(session_id)"),
            ("idx_token_usage_created", "CREATE INDEX IF NOT EXISTS idx_token_usage_created ON token_usage(created_at)"),
            ("idx_token_usage_operation", "CREATE INDEX IF NOT EXISTS idx_token_usage_operation ON token_usage(operation_type)"),

            # Additional indexes for pins table
            ("idx_pins_promoted", "CREATE INDEX IF NOT EXISTS idx_pins_promoted ON pins(promoted_to_memory_id)"),
            ("idx_pins_auto_importance", "CREATE INDEX IF NOT EXISTS idx_pins_auto_importance ON pins(auto_importance)"),
        ]

        for index_name, sql in indexes:
            if await self.check_index_exists(index_name):
                logger.info(f"  Index '{index_name}' already exists, skipping")
                continue

            if self.dry_run:
                logger.info(f"  [DRY RUN] Would execute: {sql}")
                self.changes_made.append(f"CREATE INDEX {index_name}")
            else:
                await self.connection.execute(sql)
                self.connection.commit()
                logger.info(f"  ✓ Created index '{index_name}'")
                self.changes_made.append(f"CREATE INDEX {index_name}")

    async def verify_migration(self):
        """Verify migration results"""
        logger.info("\nVerifying migration...")

        # Check pins table columns
        pins_columns = ["estimated_tokens", "promoted_to_memory_id", "auto_importance"]
        for col in pins_columns:
            exists = await self.check_column_exists("pins", col)
            status = "✓" if exists else "✗"
            logger.info(f"  {status} pins.{col}")

        # Check sessions table columns
        sessions_columns = ["initial_context_tokens", "total_loaded_tokens", "total_saved_tokens"]
        for col in sessions_columns:
            exists = await self.check_column_exists("sessions", col)
            status = "✓" if exists else "✗"
            logger.info(f"  {status} sessions.{col}")

        # Check tables
        for table in ["session_stats", "token_usage"]:
            exists = await self.check_table_exists(table)
            status = "✓" if exists else "✗"
            logger.info(f"  {status} table {table}")

        # Check indexes
        indexes = [
            "idx_session_stats_session",
            "idx_session_stats_timestamp",
            "idx_token_usage_project",
            "idx_token_usage_session",
            "idx_pins_promoted",
        ]
        for idx in indexes:
            exists = await self.check_index_exists(idx)
            status = "✓" if exists else "✗"
            logger.info(f"  {status} index {idx}")

    async def run(self):
        """Run the full migration"""
        try:
            await self.connect()

            logger.info(f"\n{'='*60}")
            logger.info(f"Starting context-token-optimization migration")
            logger.info(f"Database: {self.db_path}")
            logger.info(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
            logger.info(f"{'='*60}\n")

            # Run migration steps
            await self.migrate_pins_table()
            await self.migrate_sessions_table()
            await self.create_session_stats_table()
            await self.create_token_usage_table()
            await self.create_indexes()

            # Verify
            if not self.dry_run:
                await self.verify_migration()

            # Summary
            logger.info(f"\n{'='*60}")
            logger.info(f"Migration {'simulation' if self.dry_run else 'completed'}")
            logger.info(f"Changes made: {len(self.changes_made)}")
            for change in self.changes_made:
                logger.info(f"  - {change}")
            logger.info(f"{'='*60}\n")

            if self.dry_run:
                logger.info("This was a DRY RUN. No changes were made to the database.")
                logger.info("Run without --dry-run to apply changes.")

        except Exception as e:
            logger.error(f"Migration failed: {e}", exc_info=True)
            raise
        finally:
            await self.close()


async def main():
    parser = argparse.ArgumentParser(
        description="Migrate database schema for context-token-optimization feature"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        help="Path to SQLite database file (default: from settings)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration without making changes",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check current schema status",
    )

    args = parser.parse_args()

    # Determine database path
    if args.db_path:
        db_path = args.db_path
    else:
        settings = Settings()
        db_path = settings.database_path

    logger.info(f"Using database: {db_path}")

    # Create and run migrator
    migrator = ContextTokenOptimizationMigrator(db_path, dry_run=args.dry_run or args.check_only)

    if args.check_only:
        logger.info("Running in CHECK-ONLY mode")
        await migrator.connect()
        await migrator.verify_migration()
        await migrator.close()
    else:
        await migrator.run()


if __name__ == "__main__":
    asyncio.run(main())
