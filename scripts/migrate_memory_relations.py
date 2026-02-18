#!/usr/bin/env python3
"""
Memory Relations 테이블 마이그레이션 스크립트.

메모리 간 관계를 저장하는 테이블을 생성합니다.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database.base import Database
from app.core.config import Settings


MIGRATION_SQL = """
-- Memory Relations 테이블
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

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_relations_source ON memory_relations(source_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON memory_relations(target_id);
CREATE INDEX IF NOT EXISTS idx_relations_type ON memory_relations(relation_type);
CREATE INDEX IF NOT EXISTS idx_relations_strength ON memory_relations(strength DESC);
"""


async def check_table_exists(db: Database) -> bool:
    """테이블 존재 여부 확인"""
    result = await db.fetchone(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_relations'"
    )
    return result is not None


async def migrate(db_path: str, dry_run: bool = False):
    """마이그레이션 실행"""
    db = Database(db_path)
    await db.connect()
    
    try:
        exists = await check_table_exists(db)
        
        if exists:
            print("✅ memory_relations 테이블이 이미 존재합니다.")
            
            # 레코드 수 확인
            result = await db.fetchone("SELECT COUNT(*) as cnt FROM memory_relations")
            print(f"   현재 레코드 수: {result['cnt']}")
            return
        
        if dry_run:
            print("🔍 [DRY-RUN] 다음 SQL이 실행됩니다:")
            print(MIGRATION_SQL)
            return
        
        print("🚀 memory_relations 테이블 생성 중...")
        
        # SQL 실행 (각 문장 개별 실행)
        for statement in MIGRATION_SQL.strip().split(';'):
            statement = statement.strip()
            if statement and not statement.startswith('--'):
                # 주석 라인 제거
                lines = [l for l in statement.split('\n') if not l.strip().startswith('--')]
                clean_statement = '\n'.join(lines).strip()
                if clean_statement:
                    print(f"   실행: {clean_statement[:60]}...")
                    await db.execute(clean_statement)
        
        print("✅ 마이그레이션 완료!")
        
        # 확인
        exists = await check_table_exists(db)
        if exists:
            print("   테이블 생성 확인됨")
        
    finally:
        await db.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Memory Relations 테이블 마이그레이션")
    parser.add_argument("--dry-run", action="store_true", help="실제 실행 없이 SQL만 출력")
    parser.add_argument("--db", default=None, help="데이터베이스 경로")
    
    args = parser.parse_args()
    
    settings = Settings()
    db_path = args.db or settings.database_path
    
    print(f"📁 Database: {db_path}")
    
    asyncio.run(migrate(db_path, args.dry_run))


if __name__ == "__main__":
    main()
