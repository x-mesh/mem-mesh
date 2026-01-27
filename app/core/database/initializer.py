"""Database table initialization for mem-mesh.

This module handles table creation, schema setup, and index management.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .connection import DatabaseConnection

logger = logging.getLogger(__name__)


class DatabaseInitializer:
    """Handles database schema initialization.

    Creates all required tables and indexes for mem-mesh.
    """

    def __init__(self, connection: "DatabaseConnection"):
        self.connection = connection

    async def initialize_schema(self) -> None:
        """Initialize all tables and indexes."""
        if not self.connection.connection:
            raise RuntimeError("Database not connected")

        try:
            await self._create_core_tables()
            await self._create_work_tracking_tables()
            await self._create_monitoring_tables()
            await self._create_indexes()
            await self._create_vector_tables()
            await self._create_fallback_tables()

            self.connection.commit()
            logger.info("Database tables and indexes initialized")

        except Exception as e:
            logger.error(f"Failed to initialize tables: {e}")
            raise

    async def _create_core_tables(self) -> None:
        """Create core memory tables."""
        conn = self.connection.connection

        # memories 테이블 생성
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                project_id TEXT,
                category TEXT NOT NULL DEFAULT 'task',
                source TEXT NOT NULL,
                embedding BLOB NOT NULL,
                tags TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # embedding_metadata 테이블 생성 (모델 정보 저장용)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embedding_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

    async def _create_work_tracking_tables(self) -> None:
        """Create work tracking system tables."""
        conn = self.connection.connection

        # projects 테이블 생성
        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                tech_stack TEXT,
                global_rules TEXT,
                global_context TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # sessions 테이블 생성
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id),
                user_id TEXT NOT NULL DEFAULT 'default',
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                summary TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # pins 테이블 생성
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pins (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                project_id TEXT NOT NULL REFERENCES projects(id),
                user_id TEXT NOT NULL DEFAULT 'default',
                content TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 3,
                status TEXT NOT NULL DEFAULT 'open',
                tags TEXT,
                embedding BLOB,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

    async def _create_monitoring_tables(self) -> None:
        """Create monitoring system tables."""
        conn = self.connection.connection

        # search_metrics 테이블 생성
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_metrics (
                id TEXT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                query TEXT NOT NULL,
                query_length INTEGER NOT NULL,
                project_id TEXT,
                category TEXT,
                result_count INTEGER NOT NULL,
                avg_similarity_score REAL,
                top_similarity_score REAL,
                response_time_ms INTEGER NOT NULL,
                embedding_time_ms INTEGER,
                search_time_ms INTEGER,
                response_format TEXT,
                original_size_bytes INTEGER,
                compressed_size_bytes INTEGER,
                user_agent TEXT,
                source TEXT NOT NULL
            )
        """)

        # embedding_metrics 테이블 생성
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embedding_metrics (
                id TEXT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                operation TEXT NOT NULL,
                count INTEGER NOT NULL,
                total_time_ms INTEGER NOT NULL,
                avg_time_per_embedding_ms REAL NOT NULL,
                cache_hit BOOLEAN NOT NULL,
                memory_usage_mb REAL,
                model_name TEXT NOT NULL
            )
        """)

        # alerts 테이블 생성
        conn.execute("""
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

    async def _create_indexes(self) -> None:
        """Create all database indexes."""
        conn = self.connection.connection

        # Core indexes
        core_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_memories_project_id ON memories(project_id)",
            "CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)",
            "CREATE INDEX IF NOT EXISTS idx_memories_content_hash ON memories(content_hash)",
        ]

        # Work tracking indexes
        work_tracking_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_sessions_project_status ON sessions(project_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_pins_session ON pins(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_pins_project_status ON pins(project_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_pins_importance ON pins(importance DESC)",
            "CREATE INDEX IF NOT EXISTS idx_pins_user ON pins(user_id)",
        ]

        # Monitoring indexes
        monitoring_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_search_metrics_timestamp ON search_metrics(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_search_metrics_project ON search_metrics(project_id)",
            "CREATE INDEX IF NOT EXISTS idx_search_metrics_query ON search_metrics(query)",
            "CREATE INDEX IF NOT EXISTS idx_embedding_metrics_timestamp ON embedding_metrics(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_alerts_status_timestamp ON alerts(status, timestamp)",
        ]

        all_indexes = core_indexes + work_tracking_indexes + monitoring_indexes
        for index_sql in all_indexes:
            conn.execute(index_sql)

        logger.info("Database indexes created")

    async def _create_vector_tables(self) -> None:
        """Create sqlite-vec virtual tables if available."""
        if not self.connection.is_vec_available:
            return

        conn = self.connection.connection

        try:
            # vec0 함수가 사용 가능한지 테스트
            test_result = conn.execute("SELECT vec_version()").fetchone()
            if test_result:
                # 실제 vector 검색용 테이블 생성
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_embeddings USING vec0(
                        memory_id TEXT PRIMARY KEY,
                        embedding FLOAT[384]
                    )
                """)
                logger.info(
                    "Vector table 'memory_embeddings' created successfully with sqlite-vec"
                )
            else:
                raise Exception("vec_version() not available")
        except Exception as e:
            logger.warning(f"Failed to create vector table: {e}")

    async def _create_fallback_tables(self) -> None:
        """Create fallback tables for when sqlite-vec is not available."""
        conn = self.connection.connection

        # Fallback 테이블은 항상 생성 (MemoryService에서 사용)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories_vec_fallback (
                memory_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL
            )
        """)
        logger.info("Created fallback vector table")
