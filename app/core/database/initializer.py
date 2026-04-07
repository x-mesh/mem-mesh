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

    def __init__(self, connection: "DatabaseConnection", embedding_dim: int = 1024):
        self.connection = connection
        self.embedding_dim = embedding_dim

    async def initialize_schema(self) -> None:
        """Initialize all tables and indexes."""
        if not self.connection.connection:
            raise RuntimeError("Database not connected")

        try:
            # Step 1: Create core tables first (needed for migrations)
            await self._create_core_tables()
            await self._create_work_tracking_tables()
            await self._create_relation_tables()
            await self._create_monitoring_tables()
            await self._create_oauth_tables()

            # Step 2: Run schema migrations to add missing columns
            from .schema_migrator import SchemaMigrator

            migrator = SchemaMigrator(self.connection)
            await migrator.migrate()

            # Step 3: Create indexes (after columns exist)
            await self._create_indexes()
            await self._create_vector_tables()
            await self._create_fallback_tables()
            await self._create_fts_tables()

            self.connection.commit()
            logger.info("Database tables and indexes initialized")

        except Exception as e:
            logger.error(f"Failed to initialize tables: {e}")
            raise

    async def _create_core_tables(self) -> None:
        """Create core memory tables."""
        conn = self.connection.connection

        # Create memories table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                project_id TEXT,
                category TEXT NOT NULL DEFAULT 'task',
                source TEXT NOT NULL,
                client TEXT,
                embedding BLOB NOT NULL,
                tags TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Create embedding_metadata table (for storing model info)
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

        # Create projects table
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

        # Create sessions table (includes context-token-optimization + IDE session columns)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id),
                user_id TEXT NOT NULL DEFAULT 'default',
                ide_session_id TEXT,
                client_type TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                summary TEXT,
                initial_context_tokens INTEGER DEFAULT 0,
                total_loaded_tokens INTEGER DEFAULT 0,
                total_saved_tokens INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Create pins table (includes context-token-optimization columns)
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
                estimated_tokens INTEGER DEFAULT 0,
                promoted_to_memory_id TEXT,
                auto_importance INTEGER DEFAULT 0,
                client TEXT,
                is_staging INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Create session_stats table (context-token-optimization)
        conn.execute("""
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
        """)

        # Create token_usage table (context-token-optimization)
        conn.execute("""
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
        """)

    async def _create_relation_tables(self) -> None:
        """Create memory relations table."""
        conn = self.connection.connection

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

    async def _create_oauth_tables(self) -> None:
        """Create OAuth 2.1 related tables."""
        conn = self.connection.connection

        conn.execute("""
            CREATE TABLE IF NOT EXISTS oauth_clients (
                id TEXT PRIMARY KEY,
                client_id TEXT UNIQUE NOT NULL,
                client_secret_hash TEXT NOT NULL,
                client_name TEXT NOT NULL,
                client_type TEXT NOT NULL DEFAULT 'public',
                redirect_uris TEXT DEFAULT '[]',
                scopes TEXT DEFAULT '["read", "write"]',
                grant_types TEXT DEFAULT '["authorization_code", "refresh_token"]',
                access_token_ttl INTEGER DEFAULT 3600,
                refresh_token_ttl INTEGER DEFAULT 604800,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                access_token_hash TEXT NOT NULL,
                refresh_token TEXT,
                token_type TEXT DEFAULT 'Bearer',
                scopes TEXT DEFAULT '["read", "write"]',
                access_token_expires_at TEXT NOT NULL,
                refresh_token_expires_at TEXT,
                is_revoked INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (client_id) REFERENCES oauth_clients(client_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
                id TEXT PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                client_id TEXT NOT NULL,
                redirect_uri TEXT NOT NULL,
                code_challenge TEXT NOT NULL,
                code_challenge_method TEXT DEFAULT 'S256',
                scopes TEXT DEFAULT '["read", "write"]',
                state TEXT,
                expires_at TEXT NOT NULL,
                is_used INTEGER DEFAULT 0,
                used_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (client_id) REFERENCES oauth_clients(client_id)
            )
        """)

    async def _create_monitoring_tables(self) -> None:
        """Create monitoring system tables."""
        conn = self.connection.connection

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

        # Create embedding_metrics table
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

        # Create alerts table
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
            "CREATE INDEX IF NOT EXISTS idx_memories_client ON memories(client)",
        ]

        # Work tracking indexes
        work_tracking_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_sessions_project_status ON sessions(project_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_ide ON sessions(project_id, ide_session_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_client_type ON sessions(client_type)",
            "CREATE INDEX IF NOT EXISTS idx_pins_session ON pins(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_pins_project_status ON pins(project_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_pins_importance ON pins(importance DESC)",
            "CREATE INDEX IF NOT EXISTS idx_pins_user ON pins(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_pins_promoted ON pins(promoted_to_memory_id)",
            "CREATE INDEX IF NOT EXISTS idx_pins_auto_importance ON pins(auto_importance)",
        ]

        # Context-token-optimization indexes
        token_optimization_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_session_stats_session ON session_stats(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_session_stats_timestamp ON session_stats(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_session_stats_event_type ON session_stats(event_type)",
            "CREATE INDEX IF NOT EXISTS idx_token_usage_project ON token_usage(project_id)",
            "CREATE INDEX IF NOT EXISTS idx_token_usage_session ON token_usage(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_token_usage_created ON token_usage(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_token_usage_operation ON token_usage(operation_type)",
        ]

        # Monitoring indexes
        monitoring_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_search_metrics_timestamp ON search_metrics(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_search_metrics_project ON search_metrics(project_id)",
            "CREATE INDEX IF NOT EXISTS idx_search_metrics_query ON search_metrics(query)",
            "CREATE INDEX IF NOT EXISTS idx_embedding_metrics_timestamp ON embedding_metrics(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_alerts_status_timestamp ON alerts(status, timestamp)",
        ]

        # Relation indexes
        relation_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_relations_source ON memory_relations(source_id)",
            "CREATE INDEX IF NOT EXISTS idx_relations_target ON memory_relations(target_id)",
            "CREATE INDEX IF NOT EXISTS idx_relations_type ON memory_relations(relation_type)",
            "CREATE INDEX IF NOT EXISTS idx_relations_source_type ON memory_relations(source_id, relation_type)",
            "CREATE INDEX IF NOT EXISTS idx_relations_target_type ON memory_relations(target_id, relation_type)",
        ]

        oauth_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_oauth_clients_client_id ON oauth_clients(client_id)",
            "CREATE INDEX IF NOT EXISTS idx_oauth_tokens_client_id ON oauth_tokens(client_id)",
            "CREATE INDEX IF NOT EXISTS idx_oauth_tokens_access_hash ON oauth_tokens(access_token_hash)",
            "CREATE INDEX IF NOT EXISTS idx_oauth_tokens_refresh ON oauth_tokens(refresh_token)",
            "CREATE INDEX IF NOT EXISTS idx_oauth_codes_code ON oauth_authorization_codes(code)",
            "CREATE INDEX IF NOT EXISTS idx_oauth_codes_client ON oauth_authorization_codes(client_id)",
        ]

        all_indexes = (
            core_indexes
            + work_tracking_indexes
            + monitoring_indexes
            + relation_indexes
            + oauth_indexes
            + token_optimization_indexes
        )
        for index_sql in all_indexes:
            try:
                conn.execute(index_sql)
            except Exception as e:
                # Skip index creation if column doesn't exist yet
                # This can happen during initial setup before migrations run
                logger.debug(
                    f"Index creation skipped (may be created after migration): {e}"
                )

        logger.info("Database indexes created")

    async def _create_vector_tables(self) -> None:
        """Create sqlite-vec virtual tables if available."""
        if not self.connection.is_vec_available:
            return

        conn = self.connection.connection

        try:
            # Test whether vec0 function is available
            test_result = conn.execute("SELECT vec_version()").fetchone()
            if test_result:
                # Create table for actual vector search
                conn.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_embeddings USING vec0(
                        memory_id TEXT PRIMARY KEY,
                        embedding FLOAT[{self.embedding_dim}]
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

        # Always create fallback table (used by MemoryService)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories_vec_fallback (
                memory_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL
            )
        """)
        logger.info("Created fallback vector table")

    async def _create_fts_tables(self) -> None:
        """Create FTS5 virtual tables for full-text search."""
        conn = self.connection.connection

        # 1. Create memories_fts table (index content column)
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    id UNINDEXED,
                    content,
                    project_id UNINDEXED,
                    category UNINDEXED,
                    created_at UNINDEXED,
                    tokenize='unicode61 remove_diacritics 2'
                )
            """)

            # 2. Migrate existing data (synchronize)
            # Ideally only run when FTS table is empty for performance,
            # INSERT OR IGNORE can cause duplicates if no unique constraint on id.
            # FTS5 uses rowid as PK; the id column is just a regular column.
            # So use DELETE then INSERT to prevent duplicates, or separate logic.
            # Here we simply INSERT; triggers prevent duplicates once set up (at app startup)
            # Safe approach: only INSERT if id is not already in memories_fts
            conn.execute("""
                INSERT INTO memories_fts(id, content, project_id, category, created_at)
                SELECT id, content, project_id, category, created_at FROM memories
                WHERE id NOT IN (SELECT id FROM memories_fts)
            """)

            # 3. Create triggers (automatic synchronization)
            # INSERT
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(id, content, project_id, category, created_at)
                    VALUES (new.id, new.content, new.project_id, new.category, new.created_at);
                END;
            """)
            # DELETE
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    DELETE FROM memories_fts WHERE id = old.id;
                END;
            """)
            # UPDATE
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                    UPDATE memories_fts SET 
                        content = new.content,
                        project_id = new.project_id,
                        category = new.category,
                        created_at = new.created_at
                    WHERE id = old.id;
                END;
            """)

            logger.info("FTS tables and triggers initialized")

        except Exception as e:
            logger.warning(f"Failed to create FTS tables (might be unsupported): {e}")
