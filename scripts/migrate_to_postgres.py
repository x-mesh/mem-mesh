#!/usr/bin/env python3
"""
SQLite → PostgreSQL (pgvector) migration

Migrate existing SQLite data to PostgreSQL + pgvector.
"""

import asyncio
import sys
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.core.database.base import Database
from app.core.config import Settings


class PostgreSQLMigrator:
    """PostgreSQL migrator"""

    def __init__(self, pg_connection_string: str):
        """
        Args:
            pg_connection_string: PostgreSQL connection string
                e.g. "postgresql://user:pass@localhost:5432/memesh"
        """
        self.settings = Settings()
        self.pg_conn_str = pg_connection_string
        self.sqlite_db = None
        self.pg_conn = None

    async def setup(self):
        """Initialize"""
        # Connect to SQLite
        self.sqlite_db = Database(self.settings.database_path)
        await self.sqlite_db.connect()

        # Connect to PostgreSQL (using asyncpg)
        try:
            import asyncpg
            self.pg_conn = await asyncpg.connect(self.pg_conn_str)
        except ImportError:
            print("❌ asyncpg package is required: pip install asyncpg")
            sys.exit(1)

    async def cleanup(self):
        """Clean up"""
        if self.sqlite_db:
            await self.sqlite_db.close()
        if self.pg_conn:
            await self.pg_conn.close()

    async def create_tables(self):
        """Create PostgreSQL tables"""
        print("Creating PostgreSQL tables...")

        # Enable pgvector extension
        await self.pg_conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

        # memories table
        await self.pg_conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                project_id TEXT,
                category TEXT NOT NULL DEFAULT 'task',
                source TEXT NOT NULL,
                embedding vector(384),  -- pgvector type
                tags TEXT,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """)

        # Create basic indexes (vector index created after data insertion)
        await self.pg_conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_project_id
            ON memories(project_id)
        """)

        await self.pg_conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_created_at
            ON memories(created_at)
        """)

        await self.pg_conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_category
            ON memories(category)
        """)

        await self.pg_conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_content_hash
            ON memories(content_hash)
        """)

        print("  ✓ Tables created")

    async def create_vector_index(self):
        """Create vector index (call after data insertion)"""
        print("\nCreating vector index...")

        # Drop and recreate index (IVFFlat requires existing data)
        await self.pg_conn.execute("DROP INDEX IF EXISTS idx_memories_embedding")

        # Adjust lists parameter based on data count
        count = await self.pg_conn.fetchval(
            "SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL"
        )

        # Recommended lists = sqrt(n), minimum 1
        lists = max(1, int(count ** 0.5))
        print(f"  Data count: {count}, lists: {lists}")

        await self.pg_conn.execute(f"""
            CREATE INDEX idx_memories_embedding
            ON memories USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = {lists})
        """)

        print("  ✓ Vector index created")

    async def migrate_data(self, batch_size: int = 100):
        """Migrate data"""
        print("\nMigrating data...")

        # Fetch data from SQLite
        rows = await self.sqlite_db.fetchall(
            """
            SELECT
                m.id, m.content, m.content_hash, m.project_id,
                m.category, m.source, m.tags, m.created_at, m.updated_at,
                me.embedding
            FROM memories m
            LEFT JOIN memory_embeddings me ON m.id = me.memory_id
            WHERE m.project_id = 'mem-mesh'
            """
        )

        total = len(rows)
        print(f"  Migrating {total} memories in total")

        # Batch processing
        for i in range(0, total, batch_size):
            batch = rows[i:i + batch_size]

            # Insert into PostgreSQL
            for row in batch:
                # Convert embedding (bytes → list → string)
                embedding = None
                if row["embedding"]:
                    import struct
                    embedding_bytes = row["embedding"]
                    embedding_list = list(struct.unpack(
                        f'{len(embedding_bytes)//4}f',
                        embedding_bytes
                    ))
                    # pgvector requires string format: '[0.1, 0.2, ...]'
                    embedding = str(embedding_list)

                # Convert datetime (str → datetime, timezone-naive)
                from datetime import datetime
                created_at = datetime.fromisoformat(row["created_at"].replace('Z', '+00:00'))
                updated_at = datetime.fromisoformat(row["updated_at"].replace('Z', '+00:00'))
                # PostgreSQL TIMESTAMP requires timezone-naive
                created_at = created_at.replace(tzinfo=None)
                updated_at = updated_at.replace(tzinfo=None)

                await self.pg_conn.execute(
                    """
                    INSERT INTO memories
                    (id, content, content_hash, project_id, category, source,
                     embedding, tags, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7::vector, $8, $9, $10)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    row["id"], row["content"], row["content_hash"],
                    row["project_id"], row["category"], row["source"],
                    embedding, row["tags"], created_at, updated_at
                )

            print(f"  Progress: {min(i + batch_size, total)}/{total}")

        print("  ✓ Migration complete")

    async def verify(self):
        """Verify migration"""
        print("\nVerifying migration...")

        # SQLite count
        sqlite_count = await self.sqlite_db.fetchone(
            "SELECT COUNT(*) as count FROM memories WHERE project_id = 'mem-mesh'"
        )

        # PostgreSQL count
        pg_count = await self.pg_conn.fetchval(
            "SELECT COUNT(*) FROM memories WHERE project_id = 'mem-mesh'"
        )

        print(f"  SQLite:     {sqlite_count['count']}")
        print(f"  PostgreSQL: {pg_count}")

        if sqlite_count['count'] == pg_count:
            print("  ✓ Verification passed")
            return True
        else:
            print("  ❌ Verification failed: count mismatch")
            return False


async def main():
    """Main function"""
    import argparse

    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL migration")
    parser.add_argument(
        "--pg-url",
        required=True,
        help="PostgreSQL connection string (e.g. postgresql://user:pass@localhost:5432/memesh)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size"
    )
    args = parser.parse_args()

    migrator = PostgreSQLMigrator(args.pg_url)

    try:
        await migrator.setup()
        await migrator.create_tables()
        await migrator.migrate_data(args.batch_size)
        await migrator.create_vector_index()  # Create vector index after data insertion
        await migrator.verify()

        print("\n✅ Migration complete!")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await migrator.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
