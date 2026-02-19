#!/usr/bin/env python3
"""데이터베이스 스키마 마이그레이션: context-token-optimization

이 스크립트는 context-token-optimization 기능을 위한 데이터베이스 스키마 변경을 수행합니다:
1. pins 테이블에 토큰 추적 컬럼 추가
2. sessions 테이블에 토큰 추적 컬럼 추가
3. session_stats 신규 테이블 생성
4. token_usage 신규 테이블 생성
5. 필요한 인덱스 생성

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
    """context-token-optimization 기능을 위한 데이터베이스 마이그레이터"""
    
    def __init__(self, db_path: str, dry_run: bool = False):
        self.db_path = db_path
        self.dry_run = dry_run
        self.connection = DatabaseConnection(db_path)
        self.changes_made = []
    
    async def connect(self):
        """데이터베이스 연결"""
        await self.connection.connect()
        logger.info(f"Connected to database: {self.db_path}")
    
    async def close(self):
        """데이터베이스 연결 종료"""
        await self.connection.close()
        logger.info("Database connection closed")
    
    async def check_column_exists(self, table: str, column: str) -> bool:
        """테이블에 컬럼이 존재하는지 확인"""
        cursor = await self.connection.execute(
            f"PRAGMA table_info({table})"
        )
        columns = cursor.fetchall()
        return any(col['name'] == column for col in columns)
    
    async def check_table_exists(self, table: str) -> bool:
        """테이블이 존재하는지 확인"""
        cursor = await self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        )
        return cursor.fetchone() is not None
    
    async def check_index_exists(self, index: str) -> bool:
        """인덱스가 존재하는지 확인"""
        cursor = await self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (index,)
        )
        return cursor.fetchone() is not None
    
    async def migrate_pins_table(self):
        """pins 테이블에 토큰 추적 컬럼 추가"""
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
        """sessions 테이블에 토큰 추적 컬럼 추가"""
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
        """session_stats 테이블 생성"""
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
        """token_usage 테이블 생성"""
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
        """필요한 인덱스 생성"""
        logger.info("Creating indexes...")
        
        indexes = [
            # session_stats 인덱스
            ("idx_session_stats_session", "CREATE INDEX IF NOT EXISTS idx_session_stats_session ON session_stats(session_id)"),
            ("idx_session_stats_timestamp", "CREATE INDEX IF NOT EXISTS idx_session_stats_timestamp ON session_stats(timestamp)"),
            ("idx_session_stats_event_type", "CREATE INDEX IF NOT EXISTS idx_session_stats_event_type ON session_stats(event_type)"),
            
            # token_usage 인덱스
            ("idx_token_usage_project", "CREATE INDEX IF NOT EXISTS idx_token_usage_project ON token_usage(project_id)"),
            ("idx_token_usage_session", "CREATE INDEX IF NOT EXISTS idx_token_usage_session ON token_usage(session_id)"),
            ("idx_token_usage_created", "CREATE INDEX IF NOT EXISTS idx_token_usage_created ON token_usage(created_at)"),
            ("idx_token_usage_operation", "CREATE INDEX IF NOT EXISTS idx_token_usage_operation ON token_usage(operation_type)"),
            
            # pins 테이블 추가 인덱스
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
        """마이그레이션 결과 검증"""
        logger.info("\nVerifying migration...")
        
        # pins 테이블 컬럼 확인
        pins_columns = ["estimated_tokens", "promoted_to_memory_id", "auto_importance"]
        for col in pins_columns:
            exists = await self.check_column_exists("pins", col)
            status = "✓" if exists else "✗"
            logger.info(f"  {status} pins.{col}")
        
        # sessions 테이블 컬럼 확인
        sessions_columns = ["initial_context_tokens", "total_loaded_tokens", "total_saved_tokens"]
        for col in sessions_columns:
            exists = await self.check_column_exists("sessions", col)
            status = "✓" if exists else "✗"
            logger.info(f"  {status} sessions.{col}")
        
        # 테이블 확인
        for table in ["session_stats", "token_usage"]:
            exists = await self.check_table_exists(table)
            status = "✓" if exists else "✗"
            logger.info(f"  {status} table {table}")
        
        # 인덱스 확인
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
        """전체 마이그레이션 실행"""
        try:
            await self.connect()
            
            logger.info(f"\n{'='*60}")
            logger.info(f"Starting context-token-optimization migration")
            logger.info(f"Database: {self.db_path}")
            logger.info(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
            logger.info(f"{'='*60}\n")
            
            # 마이그레이션 단계 실행
            await self.migrate_pins_table()
            await self.migrate_sessions_table()
            await self.create_session_stats_table()
            await self.create_token_usage_table()
            await self.create_indexes()
            
            # 검증
            if not self.dry_run:
                await self.verify_migration()
            
            # 요약
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
    
    # 데이터베이스 경로 결정
    if args.db_path:
        db_path = args.db_path
    else:
        settings = Settings()
        db_path = settings.database_path
    
    logger.info(f"Using database: {db_path}")
    
    # 마이그레이터 생성 및 실행
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
