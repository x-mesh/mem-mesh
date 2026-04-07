#!/usr/bin/env python3
"""
Migration script for the Memory Relations table.

Creates a table to store relationships between memories.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database.base import Database
from app.core.config import Settings


MIGRATION_SQL = """
-- Memory Relations table
CREATE TABLE IF NOT EXISTS memory_relations (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    strength REAL NOT NULL DEFAULT 1.0,
    metadata TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES memories(id) ON DELETE CASCADE,
    UNIQUE(source_id, target_id, relation_type)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_relations_source ON memory_relations(source_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON memory_relations(target_id);
CREATE INDEX IF NOT EXISTS idx_relations_type ON memory_relations(relation_type);
CREATE INDEX IF NOT EXISTS idx_relations_strength ON memory_relations(strength DESC);
"""


async def check_table_exists(db: Database) -> bool:
    """Check whether the table exists"""
    result = await db.fetchone(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_relations'"
    )
    return result is not None


async def migrate(db_path: str, dry_run: bool = False):
    """Run migration"""
    db = Database(db_path)
    await db.connect()

    try:
        exists = await check_table_exists(db)

        if exists:
            print("✅ memory_relations table already exists.")

            # Check record count
            result = await db.fetchone("SELECT COUNT(*) as cnt FROM memory_relations")
            print(f"   Current record count: {result['cnt']}")
            return

        if dry_run:
            print("🔍 [DRY-RUN] The following SQL would be executed:")
            print(MIGRATION_SQL)
            return

        print("🚀 Creating memory_relations table...")

        # Execute SQL statements individually
        for statement in MIGRATION_SQL.strip().split(';'):
            statement = statement.strip()
            if statement and not statement.startswith('--'):
                # Remove comment lines
                lines = [l for l in statement.split('\n') if not l.strip().startswith('--')]
                clean_statement = '\n'.join(lines).strip()
                if clean_statement:
                    print(f"   Executing: {clean_statement[:60]}...")
                    await db.execute(clean_statement)

        print("✅ Migration complete!")

        # Confirm
        exists = await check_table_exists(db)
        if exists:
            print("   Table creation confirmed")

    finally:
        await db.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Memory Relations table migration")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL only without executing")
    parser.add_argument("--db", default=None, help="Database path")

    args = parser.parse_args()

    settings = Settings()
    db_path = args.db or settings.database_path

    print(f"📁 Database: {db_path}")

    asyncio.run(migrate(db_path, args.dry_run))


if __name__ == "__main__":
    main()
