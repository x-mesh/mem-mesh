#!/usr/bin/env python3
"""
임베딩 모델 변경 시 전체 메모리 재임베딩 마이그레이션 스크립트

사용법:
    python scripts/migrate_embeddings.py [options]

옵션:
    --db-path: 데이터베이스 경로 (기본: data/memories.db)
    --new-model: 새 임베딩 모델 (기본: .env의 MEM_MESH_EMBEDDING_MODEL)
    --batch-size: 배치 크기 (기본: 100)
    --dry-run: 실제 변경 없이 미리보기
    --force: 모델이 같아도 강제 재임베딩
    --check-only: 현재 상태만 확인 (마이그레이션 없음)

예시:
    # 현재 상태 확인
    python scripts/migrate_embeddings.py --check-only
    
    # 새 모델로 마이그레이션 (dry-run)
    python scripts/migrate_embeddings.py --new-model all-MiniLM-L6-v2 --dry-run
    
    # 실제 마이그레이션 실행
    python scripts/migrate_embeddings.py --new-model all-MiniLM-L6-v2
    
    # 강제 재임베딩 (같은 모델이라도)
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

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EmbeddingMigrator:
    """임베딩 마이그레이션 클래스"""
    
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
        """데이터베이스 및 임베딩 서비스 초기화"""
        from app.core.database.base import Database
        from app.core.embeddings.service import EmbeddingService
        
        logger.info(f"데이터베이스 연결: {self.db_path}")
        self.db = Database(self.db_path)
        await self.db.connect()
        
        logger.info(f"임베딩 모델 로드: {self.new_model}")
        self.embedding_service = EmbeddingService(self.new_model, preload=True)
        
        logger.info("초기화 완료")
    
    async def shutdown(self) -> None:
        """리소스 정리"""
        if self.db:
            await self.db.close()
    
    async def check_status(self) -> dict:
        """현재 상태 확인"""
        # 저장된 모델 정보 조회
        stored_model = await self.db.get_embedding_metadata("embedding_model")
        stored_dim = await self.db.get_embedding_metadata("embedding_dimension")
        
        # 메모리 수 조회
        cursor = await self.db.execute("SELECT COUNT(*) as count FROM memories")
        total_memories = cursor.fetchone()['count']
        
        # 벡터 테이블 수 조회
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
        """마이그레이션 실행"""
        status = await self.check_status()
        
        print("\n" + "="*60)
        print("📊 현재 상태")
        print("="*60)
        print(f"  DB 저장 모델: {status['stored_model'] or '(없음)'}")
        print(f"  DB 저장 차원: {status['stored_dimension'] or '(없음)'}")
        print(f"  새 모델: {status['new_model']}")
        print(f"  새 차원: {status['new_dimension']}")
        print(f"  총 메모리 수: {status['total_memories']}")
        print(f"  벡터 테이블 수: {status['vector_table_count']}")
        print("="*60 + "\n")
        
        # 마이그레이션 필요 여부 확인
        if not self.force and not status['needs_migration'] and status['stored_model']:
            print("✅ 모델이 동일합니다. 마이그레이션이 필요하지 않습니다.")
            print("   강제 재임베딩을 원하면 --force 옵션을 사용하세요.")
            return self.stats
        
        if status['total_memories'] == 0:
            print("✅ 마이그레이션할 메모리가 없습니다.")
            return self.stats
        
        self.stats["total_memories"] = status['total_memories']
        
        if self.dry_run:
            print("🔍 DRY RUN 모드 - 실제 변경 없이 미리보기만 수행합니다.\n")
        
        # 배치 단위로 마이그레이션
        offset = 0
        batch_num = 0
        
        while True:
            # 메모리 배치 조회
            cursor = await self.db.execute(
                "SELECT id, content FROM memories ORDER BY created_at LIMIT ? OFFSET ?",
                (self.batch_size, offset)
            )
            memories = cursor.fetchall()
            
            if not memories:
                break
            
            batch_num += 1
            print(f"📦 배치 {batch_num} 처리 중... ({offset + 1} ~ {offset + len(memories)})")
            
            for memory in memories:
                try:
                    memory_id = memory['id']
                    content = memory['content']
                    
                    if self.dry_run:
                        # dry-run: 임베딩만 생성하고 저장하지 않음
                        embedding = self.embedding_service.embed(content[:2000])
                        self.stats["migrated"] += 1
                    else:
                        # 실제 마이그레이션
                        await self._migrate_single_memory(memory_id, content)
                        self.stats["migrated"] += 1
                    
                except Exception as e:
                    logger.error(f"메모리 {memory['id']} 마이그레이션 실패: {e}")
                    self.stats["failed"] += 1
            
            offset += self.batch_size
            
            # 진행률 출력
            progress = (offset / status['total_memories']) * 100
            print(f"   진행률: {min(progress, 100):.1f}% ({self.stats['migrated']} 완료, {self.stats['failed']} 실패)")
        
        # 메타데이터 업데이트
        if not self.dry_run:
            await self.db.set_embedding_metadata("embedding_model", self.new_model)
            await self.db.set_embedding_metadata("embedding_dimension", str(self.embedding_service.dimension))
            await self.db.set_embedding_metadata("last_migration", datetime.utcnow().isoformat() + 'Z')
            print("\n✅ 메타데이터 업데이트 완료")
        
        print("\n" + "="*60)
        print("📊 마이그레이션 결과")
        print("="*60)
        print(f"  총 메모리: {self.stats['total_memories']}")
        print(f"  성공: {self.stats['migrated']}")
        print(f"  실패: {self.stats['failed']}")
        print(f"  스킵: {self.stats['skipped']}")
        print("="*60 + "\n")
        
        return self.stats
    
    async def _migrate_single_memory(self, memory_id: str, content: str) -> None:
        """단일 메모리 마이그레이션"""
        # 새 임베딩 생성
        embedding = self.embedding_service.embed(content[:2000])
        embedding_bytes = self.embedding_service.to_bytes(embedding)
        
        # memories 테이블 업데이트
        await self.db.execute(
            "UPDATE memories SET embedding = ?, updated_at = ? WHERE id = ?",
            (embedding_bytes, datetime.utcnow().isoformat() + 'Z', memory_id)
        )
        
        # 벡터 테이블 업데이트
        cursor = await self.db.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='memory_embeddings'
        """)
        
        if cursor.fetchone():
            # JSON 형식으로 변환
            embedding_json = json.dumps(embedding)
            # sqlite-vec 가상 테이블은 INSERT OR REPLACE가 안 되므로 DELETE 후 INSERT
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
        description="임베딩 모델 변경 시 전체 메모리 재임베딩 마이그레이션"
    )
    parser.add_argument(
        "--db-path",
        default="data/memories.db",
        help="데이터베이스 경로 (기본: data/memories.db)"
    )
    parser.add_argument(
        "--new-model",
        default=None,
        help="새 임베딩 모델 (기본: .env의 MEM_MESH_EMBEDDING_MODEL)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="배치 크기 (기본: 100)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 변경 없이 미리보기"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="모델이 같아도 강제 재임베딩"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="현재 상태만 확인 (마이그레이션 없음)"
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
            print("📊 현재 상태")
            print("="*60)
            print(f"  DB 저장 모델: {status['stored_model'] or '(없음)'}")
            print(f"  DB 저장 차원: {status['stored_dimension'] or '(없음)'}")
            print(f"  현재 설정 모델: {status['new_model']}")
            print(f"  현재 설정 차원: {status['new_dimension']}")
            print(f"  총 메모리 수: {status['total_memories']}")
            print(f"  벡터 테이블 수: {status['vector_table_count']}")
            print(f"  마이그레이션 필요: {'예' if status['needs_migration'] else '아니오'}")
            print("="*60 + "\n")
        else:
            await migrator.migrate()
        
    finally:
        await migrator.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
