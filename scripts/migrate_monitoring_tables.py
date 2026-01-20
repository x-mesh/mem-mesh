#!/usr/bin/env python3
"""모니터링 테이블 마이그레이션 스크립트

검색 성능 모니터링을 위한 테이블 생성:
- search_metrics: 검색 메트릭
- embedding_metrics: 임베딩 성능 메트릭
- alerts: 알림
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database.base import Database
from app.core.config import get_settings
from app.core.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


async def create_monitoring_tables():
    """모니터링 테이블 생성"""
    
    db = Database(settings.database_path)
    await db.connect()
    
    try:
        # search_metrics 테이블
        logger.info("Creating search_metrics table...")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS search_metrics (
                id TEXT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                query TEXT NOT NULL,
                query_length INTEGER NOT NULL,
                project_id TEXT,
                category TEXT,
                
                -- 검색 결과
                result_count INTEGER NOT NULL,
                avg_similarity_score REAL,
                top_similarity_score REAL,
                
                -- 성능
                response_time_ms INTEGER NOT NULL,
                embedding_time_ms INTEGER,
                search_time_ms INTEGER,
                
                -- 압축
                response_format TEXT,
                original_size_bytes INTEGER,
                compressed_size_bytes INTEGER,
                
                -- 메타데이터
                user_agent TEXT,
                source TEXT NOT NULL
            )
        """)
        
        # 인덱스 생성
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
        
        # embedding_metrics 테이블
        logger.info("Creating embedding_metrics table...")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS embedding_metrics (
                id TEXT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                operation TEXT NOT NULL,
                
                -- 성능
                count INTEGER NOT NULL,
                total_time_ms INTEGER NOT NULL,
                avg_time_per_embedding_ms REAL NOT NULL,
                
                -- 캐시
                cache_hit BOOLEAN NOT NULL,
                
                -- 리소스
                memory_usage_mb REAL,
                model_name TEXT NOT NULL
            )
        """)
        
        # 인덱스 생성
        logger.info("Creating indexes for embedding_metrics...")
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_embedding_metrics_timestamp 
            ON embedding_metrics(timestamp)
        """)
        
        # alerts 테이블
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
                resolved_at DATETIME
            )
        """)
        
        # 인덱스 생성
        logger.info("Creating indexes for alerts...")
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_status_timestamp 
            ON alerts(status, timestamp)
        """)
        
        logger.info("✅ All monitoring tables created successfully!")
        
        # 테이블 확인
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
    """테이블 생성 확인"""
    
    db = Database(settings.database_path)
    await db.connect()
    
    try:
        # 각 테이블의 스키마 확인
        for table in ['search_metrics', 'embedding_metrics', 'alerts']:
            logger.info(f"\n{table} schema:")
            schema = await db.fetchall(f"PRAGMA table_info({table})")
            for col in schema:
                logger.info(f"  - {col['name']}: {col['type']}")
            
            # 인덱스 확인
            indexes = await db.fetchall(f"PRAGMA index_list({table})")
            if indexes:
                logger.info(f"  Indexes: {[idx['name'] for idx in indexes]}")
        
    finally:
        await db.close()


async def main():
    """메인 함수"""
    
    logger.info("Starting monitoring tables migration...")
    logger.info(f"Database path: {settings.database_path}")
    
    # 테이블 생성
    await create_monitoring_tables()
    
    # 검증
    await verify_tables()
    
    logger.info("\n✅ Migration completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
