#!/usr/bin/env python3
"""
Migration script to re-embed all memories when the embedding model changes.

Usage:
    python scripts/migrate_embeddings.py [options]

Options:
    --db-path: Database path (default: data/memories.db)
    --new-model: New embedding model (default: MEM_MESH_EMBEDDING_MODEL from .env)
    --batch-size: Batch size (default: 100)
    --dry-run: Preview without making actual changes
    --force: Force re-embedding even if the model is the same
    --check-only: Only check current status (no migration)

Examples:
    # Check current status
    python scripts/migrate_embeddings.py --check-only

    # Migrate to new model (dry-run)
    python scripts/migrate_embeddings.py --new-model all-MiniLM-L6-v2 --dry-run

    # Run actual migration
    python scripts/migrate_embeddings.py --new-model all-MiniLM-L6-v2

    # Force re-embedding (even with same model)
    python scripts/migrate_embeddings.py --force
"""
import sys
import os
import json
import asyncio
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EmbeddingMigrator:
    """Embedding migration class"""

    def __init__(
        self,
        db_path: str = "data/memories.db",
        new_model: Optional[str] = None,
        batch_size: int = 100,
        dry_run: bool = False,
        force: bool = False
    ):
        self.db_path = db_path
        self.new_model = new_model or os.getenv("MEM_MESH_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.force = force

        self.db = None
        self.embedding_service = None

        self.stats = {
            "total_memories": 0,
            "migrated": 0,
            "failed": 0,
            "skipped": 0
        }

    async def initialize(self) -> None:
        """Initialize database and embedding service"""
        from app.core.database.base import Database
        from app.core.embeddings.service import EmbeddingService

        logger.info(f"Connecting to database: {self.db_path}")
        self.db = Database(self.db_path)
        await self.db.connect()

        logger.info(f"Loading embedding model: {self.new_model}")
        self.embedding_service = EmbeddingService(self.new_model, preload=True)

        logger.info("Initialization complete")

    async def shutdown(self) -> None:
        """Clean up resources"""
        if self.db:
            await self.db.close()

    async def check_status(self) -> dict:
        """Check current status"""
        # Query stored model info
        stored_model = await self.db.get_embedding_metadata("embedding_model")
        stored_dim = await self.db.get_embedding_metadata("embedding_dimension")

        # Query memory count
        cursor = await self.db.execute("SELECT COUNT(*) as count FROM memories")
        total_memories = cursor.fetchone()['count']

        # Query vector table count
        cursor = await self.db.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='memory_embeddings'
        """)
        has_vector_table = cursor.fetchone() is not None

        vector_count = 0
        if has_vector_table:
            cursor = await self.db.execute("SELECT COUNT(*) as count FROM memory_embeddings")
            vector_count = cursor.fetchone()['count']

        return {
            "stored_model": stored_model,
            "stored_dimension": int(stored_dim) if stored_dim else None,
            "new_model": self.new_model,
            "new_dimension": self.embedding_service.dimension if self.embedding_service else None,
            "total_memories": total_memories,
            "vector_table_count": vector_count,
            "has_vector_table": has_vector_table,
            "needs_migration": stored_model != self.new_model if stored_model else False
        }

    async def migrate(self) -> dict:
        """Run migration"""
        status = await self.check_status()

        print("\n" + "="*60)
        print("📊 Current Status")
        print("="*60)
        print(f"  Stored model: {status['stored_model'] or '(none)'}")
        print(f"  Stored dimension: {status['stored_dimension'] or '(none)'}")
        print(f"  New model: {status['new_model']}")
        print(f"  New dimension: {status['new_dimension']}")
        print(f"  Total memories: {status['total_memories']}")
        print(f"  Vector table count: {status['vector_table_count']}")
        print("="*60 + "\n")

        # Check if migration is needed
        if not self.force and not status['needs_migration'] and status['stored_model']:
            print("✅ Model is the same. Migration is not needed.")
            print("   Use --force to force re-embedding.")
            return self.stats

        if status['total_memories'] == 0:
            print("✅ No memories to migrate.")
            return self.stats

        self.stats["total_memories"] = status['total_memories']

        if self.dry_run:
            print("🔍 DRY RUN mode - previewing without making actual changes.\n")

        # Migrate in batches
        offset = 0
        batch_num = 0

        while True:
            # Fetch memory batch
            cursor = await self.db.execute(
                "SELECT id, content FROM memories ORDER BY created_at LIMIT ? OFFSET ?",
                (self.batch_size, offset)
            )
            memories = cursor.fetchall()

            if not memories:
                break

            batch_num += 1
            print(f"📦 Processing batch {batch_num}... ({offset + 1} ~ {offset + len(memories)})")

            for memory in memories:
                try:
                    memory_id = memory['id']
                    content = memory['content']

                    if self.dry_run:
                        # dry-run: generate embedding but do not save
                        embedding = self.embedding_service.embed(content[:2000])
                        self.stats["migrated"] += 1
                    else:
                        # Actual migration
                        await self._migrate_single_memory(memory_id, content)
                        self.stats["migrated"] += 1

                except Exception as e:
                    logger.error(f"Failed to migrate memory {memory['id']}: {e}")
                    self.stats["failed"] += 1

            offset += self.batch_size

            # Print progress
            progress = (offset / status['total_memories']) * 100
            print(f"   Progress: {min(progress, 100):.1f}% ({self.stats['migrated']} done, {self.stats['failed']} failed)")

        # Update metadata
        if not self.dry_run:
            await self.db.set_embedding_metadata("embedding_model", self.new_model)
            await self.db.set_embedding_metadata("embedding_dimension", str(self.embedding_service.dimension))
            await self.db.set_embedding_metadata("last_migration", datetime.utcnow().isoformat() + 'Z')
            print("\n✅ Metadata updated")

        print("\n" + "="*60)
        print("📊 Migration Results")
        print("="*60)
        print(f"  Total memories: {self.stats['total_memories']}")
        print(f"  Succeeded: {self.stats['migrated']}")
        print(f"  Failed: {self.stats['failed']}")
        print(f"  Skipped: {self.stats['skipped']}")
        print("="*60 + "\n")

        return self.stats

    async def _migrate_single_memory(self, memory_id: str, content: str) -> None:
        """Migrate a single memory"""
        # Generate new embedding
        embedding = self.embedding_service.embed(content[:2000])
        embedding_bytes = self.embedding_service.to_bytes(embedding)

        # Update memories table
        await self.db.execute(
            "UPDATE memories SET embedding = ?, updated_at = ? WHERE id = ?",
            (embedding_bytes, datetime.utcnow().isoformat() + 'Z', memory_id)
        )

        # Update vector table
        cursor = await self.db.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='memory_embeddings'
        """)

        if cursor.fetchone():
            # Convert to JSON format
            embedding_json = json.dumps(embedding)
            # sqlite-vec virtual table does not support INSERT OR REPLACE — DELETE then INSERT
            await self.db.execute(
                "DELETE FROM memory_embeddings WHERE memory_id = ?",
                (memory_id,)
            )
            await self.db.execute(
                "INSERT INTO memory_embeddings (memory_id, embedding) VALUES (?, ?)",
                (memory_id, embedding_json)
            )

        self.db.connection.commit()


async def main():
    parser = argparse.ArgumentParser(
        description="Migration script to re-embed all memories when the embedding model changes"
    )
    parser.add_argument(
        "--db-path",
        default="data/memories.db",
        help="Database path (default: data/memories.db)"
    )
    parser.add_argument(
        "--new-model",
        default=None,
        help="New embedding model (default: MEM_MESH_EMBEDDING_MODEL from .env)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size (default: 100)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without making actual changes"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-embedding even if the model is the same"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check current status (no migration)"
    )

    args = parser.parse_args()

    migrator = EmbeddingMigrator(
        db_path=args.db_path,
        new_model=args.new_model,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        force=args.force
    )

    try:
        await migrator.initialize()

        if args.check_only:
            status = await migrator.check_status()
            print("\n" + "="*60)
            print("📊 Current Status")
            print("="*60)
            print(f"  Stored model: {status['stored_model'] or '(none)'}")
            print(f"  Stored dimension: {status['stored_dimension'] or '(none)'}")
            print(f"  Configured model: {status['new_model']}")
            print(f"  Configured dimension: {status['new_dimension']}")
            print(f"  Total memories: {status['total_memories']}")
            print(f"  Vector table count: {status['vector_table_count']}")
            print(f"  Migration needed: {'Yes' if status['needs_migration'] else 'No'}")
            print("="*60 + "\n")
        else:
            await migrator.migrate()

    finally:
        await migrator.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
