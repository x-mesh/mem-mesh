#!/usr/bin/env python3
"""
SQLite → PostgreSQL (pgvector) 마이그레이션

기존 SQLite 데이터를 PostgreSQL + pgvector로 마이그레이션
"""

import asyncio
import sys
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.core.database.base import Database
from app.core.config import Settings


class PostgreSQLMigrator:
    """PostgreSQL 마이그레이션"""
    
    def __init__(self, pg_connection_string: str):
        """
        Args:
            pg_connection_string: PostgreSQL 연결 문자열
                예: "postgresql://user:pass@localhost:5432/memesh"
        """
        self.settings = Settings()
        self.pg_conn_str = pg_connection_string
        self.sqlite_db = None
        self.pg_conn = None
    
    async def setup(self):
        """초기화"""
        # SQLite 연결
        self.sqlite_db = Database(self.settings.database_path)
        await self.sqlite_db.connect()
        
        # PostgreSQL 연결 (asyncpg 사용)
        try:
            import asyncpg
            self.pg_conn = await asyncpg.connect(self.pg_conn_str)
        except ImportError:
            print("❌ asyncpg 패키지가 필요합니다: pip install asyncpg")
            sys.exit(1)
    
    async def cleanup(self):
        """정리"""
        if self.sqlite_db:
            await self.sqlite_db.close()
        if self.pg_conn:
            await self.pg_conn.close()
    
    async def create_tables(self):
        """PostgreSQL 테이블 생성"""
        print("PostgreSQL 테이블 생성 중...")
        
        # pgvector 확장 활성화
        await self.pg_conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        
        # memories 테이블
        await self.pg_conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                project_id TEXT,
                category TEXT NOT NULL DEFAULT 'task',
                source TEXT NOT NULL,
                embedding vector(384),  -- pgvector 타입
                tags TEXT,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """)
        
        # 기본 인덱스 생성 (벡터 인덱스는 데이터 삽입 후 생성)
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
        
        print("  ✓ 테이블 생성 완료")
    
    async def create_vector_index(self):
        """벡터 인덱스 생성 (데이터 삽입 후 호출)"""
        print("\n벡터 인덱스 생성 중...")
        
        # 기존 인덱스 삭제 후 재생성 (IVFFlat은 데이터가 있어야 함)
        await self.pg_conn.execute("DROP INDEX IF EXISTS idx_memories_embedding")
        
        # 데이터 수에 따라 lists 파라미터 조정
        count = await self.pg_conn.fetchval(
            "SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL"
        )
        
        # lists = sqrt(n) 권장, 최소 1
        lists = max(1, int(count ** 0.5))
        print(f"  데이터 수: {count}, lists: {lists}")
        
        await self.pg_conn.execute(f"""
            CREATE INDEX idx_memories_embedding 
            ON memories USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = {lists})
        """)
        
        print("  ✓ 벡터 인덱스 생성 완료")
    
    async def migrate_data(self, batch_size: int = 100):
        """데이터 마이그레이션"""
        print("\n데이터 마이그레이션 중...")
        
        # SQLite에서 데이터 조회
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
        print(f"  총 {total}개 메모리 마이그레이션")
        
        # 배치 처리
        for i in range(0, total, batch_size):
            batch = rows[i:i + batch_size]
            
            # PostgreSQL에 삽입
            for row in batch:
                # 임베딩 변환 (bytes → list → string)
                embedding = None
                if row["embedding"]:
                    import struct
                    embedding_bytes = row["embedding"]
                    embedding_list = list(struct.unpack(
                        f'{len(embedding_bytes)//4}f',
                        embedding_bytes
                    ))
                    # pgvector는 문자열 형식 필요: '[0.1, 0.2, ...]'
                    embedding = str(embedding_list)
                
                # datetime 변환 (str → datetime, timezone-naive로 변환)
                from datetime import datetime
                created_at = datetime.fromisoformat(row["created_at"].replace('Z', '+00:00'))
                updated_at = datetime.fromisoformat(row["updated_at"].replace('Z', '+00:00'))
                # PostgreSQL TIMESTAMP는 timezone-naive 필요
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
            
            print(f"  진행: {min(i + batch_size, total)}/{total}")
        
        print("  ✓ 마이그레이션 완료")
    
    async def verify(self):
        """마이그레이션 검증"""
        print("\n마이그레이션 검증 중...")
        
        # SQLite 카운트
        sqlite_count = await self.sqlite_db.fetchone(
            "SELECT COUNT(*) as count FROM memories WHERE project_id = 'mem-mesh'"
        )
        
        # PostgreSQL 카운트
        pg_count = await self.pg_conn.fetchval(
            "SELECT COUNT(*) FROM memories WHERE project_id = 'mem-mesh'"
        )
        
        print(f"  SQLite:     {sqlite_count['count']}개")
        print(f"  PostgreSQL: {pg_count}개")
        
        if sqlite_count['count'] == pg_count:
            print("  ✓ 검증 성공")
            return True
        else:
            print("  ❌ 검증 실패: 개수 불일치")
            return False


async def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL 마이그레이션")
    parser.add_argument(
        "--pg-url",
        required=True,
        help="PostgreSQL 연결 문자열 (예: postgresql://user:pass@localhost:5432/memesh)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="배치 크기"
    )
    args = parser.parse_args()
    
    migrator = PostgreSQLMigrator(args.pg_url)
    
    try:
        await migrator.setup()
        await migrator.create_tables()
        await migrator.migrate_data(args.batch_size)
        await migrator.create_vector_index()  # 데이터 삽입 후 벡터 인덱스 생성
        await migrator.verify()
        
        print("\n✅ 마이그레이션 완료!")
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await migrator.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
