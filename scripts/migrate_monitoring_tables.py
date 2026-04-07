#!/usr/bin/env python3
"""Monitoring tables migration script

Creates tables for search performance monitoring:
- search_metrics: search metrics
- embedding_metrics: embedding performance metrics
- alerts: alerts
"""

import asyncio
import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database.base import Database
from app.core.config import get_settings
from app.core.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


async def create_monitoring_tables():
    """Create monitoring tables"""

    db = Database(settings.database_path)
    await db.connect()

    try:
        # search_metrics table
        logger.info("Creating search_metrics table...")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS search_metrics (
                id TEXT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                query TEXT NOT NULL,
                query_length INTEGER NOT NULL,
                project_id TEXT,
                category TEXT,

                -- search results
                result_count INTEGER NOT NULL,
                avg_similarity_score REAL,
                top_similarity_score REAL,

                -- performance
                response_time_ms INTEGER NOT NULL,
                embedding_time_ms INTEGER,
                search_time_ms INTEGER,

                -- compression
                response_format TEXT,
                original_size_bytes INTEGER,
                compressed_size_bytes INTEGER,

                -- metadata
                user_agent TEXT,
                source TEXT NOT NULL
            )
        """)

        # Create indexes
        logger.info("Creating indexes for search_metrics...")
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_search_metrics_timestamp
            ON search_metrics(timestamp)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_search_metrics_project
            ON search_metrics(project_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_search_metrics_query
            ON search_metrics(query)
        """)

        # embedding_metrics table
        logger.info("Creating embedding_metrics table...")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS embedding_metrics (
                id TEXT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                operation TEXT NOT NULL,

                -- performance
                count INTEGER NOT NULL,
                total_time_ms INTEGER NOT NULL,
                avg_time_per_embedding_ms REAL NOT NULL,

                -- cache
                cache_hit BOOLEAN NOT NULL,

                -- resources
                memory_usage_mb REAL,
                model_name TEXT NOT NULL
            )
        """)

        # Create indexes
        logger.info("Creating indexes for embedding_metrics...")
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_embedding_metrics_timestamp
            ON embedding_metrics(timestamp)
        """)

        # alerts table
        logger.info("Creating alerts table...")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                metric_value REAL NOT NULL,
                threshold_value REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                resolved_at DATETIME,
                resolved_by TEXT
            )
        """)

        # Create indexes
        logger.info("Creating indexes for alerts...")
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_status_timestamp
            ON alerts(status, timestamp)
        """)

        logger.info("✅ All monitoring tables created successfully!")

        # Verify tables
        tables = await db.fetchall("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN ('search_metrics', 'embedding_metrics', 'alerts')
        """)

        logger.info(f"Created tables: {[t['name'] for t in tables]}")

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        raise
    finally:
        await db.close()


async def verify_tables():
    """Verify tables were created"""

    db = Database(settings.database_path)
    await db.connect()

    try:
        # Check schema for each table
        for table in ['search_metrics', 'embedding_metrics', 'alerts']:
            logger.info(f"\n{table} schema:")
            schema = await db.fetchall(f"PRAGMA table_info({table})")
            for col in schema:
                logger.info(f"  - {col['name']}: {col['type']}")

            # Check indexes
            indexes = await db.fetchall(f"PRAGMA index_list({table})")
            if indexes:
                logger.info(f"  Indexes: {[idx['name'] for idx in indexes]}")

    finally:
        await db.close()


async def main():
    """Main function"""

    logger.info("Starting monitoring tables migration...")
    logger.info(f"Database path: {settings.database_path}")

    # Create tables
    await create_monitoring_tables()

    # Verify
    await verify_tables()

    logger.info("\n✅ Migration completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
