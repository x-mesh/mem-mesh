#!/usr/bin/env python3
"""
SQLite → Qdrant migration

Migrate existing SQLite data to Qdrant.
"""

import asyncio
import sys
from pathlib import Path
from typing import List, Dict, Any
import struct

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.core.database.base import Database
from app.core.config import Settings


class QdrantMigrator:
    """Qdrant migrator"""

    def __init__(self, qdrant_url: str, collection_name: str = "mem-mesh"):
        """
        Args:
            qdrant_url: Qdrant server URL (e.g. http://localhost:6333)
            collection_name: Collection name
        """
        self.settings = Settings()
        self.qdrant_url = qdrant_url
        self.collection_name = collection_name
        self.sqlite_db = None
        self.qdrant_client = None

    async def setup(self):
        """Initialize"""
        # Connect to SQLite
        self.sqlite_db = Database(self.settings.database_path)
        await self.sqlite_db.connect()

        # Qdrant client
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            self.qdrant_client = QdrantClient(url=self.qdrant_url)
            self.Distance = Distance
            self.VectorParams = VectorParams
        except ImportError:
            print("❌ qdrant-client package is required: pip install qdrant-client")
            sys.exit(1)

    async def cleanup(self):
        """Clean up"""
        if self.sqlite_db:
            await self.sqlite_db.close()

    async def create_collection(self):
        """Create Qdrant collection"""
        print(f"Creating Qdrant collection: {self.collection_name}")

        # Delete existing collection (optional)
        try:
            self.qdrant_client.delete_collection(self.collection_name)
            print("  Existing collection deleted")
        except Exception:
            pass

        # Create new collection
        self.qdrant_client.create_collection(
            collection_name=self.collection_name,
            vectors_config=self.VectorParams(
                size=384,  # Embedding dimensions
                distance=self.Distance.COSINE
            )
        )

        print("  ✓ Collection created")

    async def migrate_data(self, batch_size: int = 100):
        """Migrate data"""
        print("\nMigrating data...")

        from qdrant_client.models import PointStruct

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
            points = []

            for row in batch:
                # Convert embedding (bytes → list)
                embedding = None
                if row["embedding"]:
                    embedding_bytes = row["embedding"]
                    embedding = list(struct.unpack(
                        f'{len(embedding_bytes)//4}f',
                        embedding_bytes
                    ))

                # Use zero vector if no embedding available
                if not embedding:
                    embedding = [0.0] * 384

                # Create Qdrant Point
                point = PointStruct(
                    id=row["id"],
                    vector=embedding,
                    payload={
                        "content": row["content"],
                        "content_hash": row["content_hash"],
                        "project_id": row["project_id"],
                        "category": row["category"],
                        "source": row["source"],
                        "tags": row["tags"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "has_embedding": row["embedding"] is not None
                    }
                )
                points.append(point)

            # Upload to Qdrant
            if points:
                self.qdrant_client.upsert(
                    collection_name=self.collection_name,
                    points=points
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

        # Qdrant count
        collection_info = self.qdrant_client.get_collection(self.collection_name)
        qdrant_count = collection_info.points_count

        print(f"  SQLite:  {sqlite_count['count']}")
        print(f"  Qdrant:  {qdrant_count}")

        if sqlite_count['count'] == qdrant_count:
            print("  ✓ Verification passed")
            return True
        else:
            print("  ❌ Verification failed: count mismatch")
            return False

    async def test_search(self, query: str = "MCP configuration"):
        """Test search"""
        print(f"\nSearch test: '{query}'")

        from app.core.embeddings.service import EmbeddingService

        # Generate embedding
        embedding_service = EmbeddingService(self.settings)
        await embedding_service.initialize()

        try:
            query_embedding = await embedding_service.generate_embedding(query)

            # Qdrant search
            results = self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding.tolist(),
                limit=5
            )

            print(f"  Results: {len(results)}")
            for i, result in enumerate(results, 1):
                print(f"  {i}. [{result.score:.3f}] {result.payload['content'][:80]}...")

        finally:
            await embedding_service.cleanup()


async def main():
    """Main function"""
    import argparse

    parser = argparse.ArgumentParser(description="SQLite → Qdrant migration")
    parser.add_argument(
        "--qdrant-url",
        default="http://localhost:6333",
        help="Qdrant server URL"
    )
    parser.add_argument(
        "--collection",
        default="mem-mesh",
        help="Collection name"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size"
    )
    parser.add_argument(
        "--test-search",
        action="store_true",
        help="Run search test after migration"
    )
    args = parser.parse_args()

    migrator = QdrantMigrator(args.qdrant_url, args.collection)

    try:
        await migrator.setup()
        await migrator.create_collection()
        await migrator.migrate_data(args.batch_size)
        await migrator.verify()

        if args.test_search:
            await migrator.test_search()

        print("\n✅ Migration complete!")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await migrator.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
