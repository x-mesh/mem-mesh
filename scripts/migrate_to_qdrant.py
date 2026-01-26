#!/usr/bin/env python3
"""
SQLite → Qdrant 마이그레이션

기존 SQLite 데이터를 Qdrant로 마이그레이션
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
    """Qdrant 마이그레이션"""
    
    def __init__(self, qdrant_url: str, collection_name: str = "mem-mesh"):
        """
        Args:
            qdrant_url: Qdrant 서버 URL (예: http://localhost:6333)
            collection_name: 컬렉션 이름
        """
        self.settings = Settings()
        self.qdrant_url = qdrant_url
        self.collection_name = collection_name
        self.sqlite_db = None
        self.qdrant_client = None
    
    async def setup(self):
        """초기화"""
        # SQLite 연결
        self.sqlite_db = Database(self.settings.database_path)
        await self.sqlite_db.connect()
        
        # Qdrant 클라이언트
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams
            
            self.qdrant_client = QdrantClient(url=self.qdrant_url)
            self.Distance = Distance
            self.VectorParams = VectorParams
        except ImportError:
            print("❌ qdrant-client 패키지가 필요합니다: pip install qdrant-client")
            sys.exit(1)
    
    async def cleanup(self):
        """정리"""
        if self.sqlite_db:
            await self.sqlite_db.close()
    
    async def create_collection(self):
        """Qdrant 컬렉션 생성"""
        print(f"Qdrant 컬렉션 생성 중: {self.collection_name}")
        
        # 기존 컬렉션 삭제 (선택사항)
        try:
            self.qdrant_client.delete_collection(self.collection_name)
            print("  기존 컬렉션 삭제됨")
        except Exception:
            pass
        
        # 새 컬렉션 생성
        self.qdrant_client.create_collection(
            collection_name=self.collection_name,
            vectors_config=self.VectorParams(
                size=384,  # 임베딩 차원
                distance=self.Distance.COSINE
            )
        )
        
        print("  ✓ 컬렉션 생성 완료")
    
    async def migrate_data(self, batch_size: int = 100):
        """데이터 마이그레이션"""
        print("\n데이터 마이그레이션 중...")
        
        from qdrant_client.models import PointStruct
        
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
            points = []
            
            for row in batch:
                # 임베딩 변환 (bytes → list)
                embedding = None
                if row["embedding"]:
                    embedding_bytes = row["embedding"]
                    embedding = list(struct.unpack(
                        f'{len(embedding_bytes)//4}f',
                        embedding_bytes
                    ))
                
                if embedding:
                    # Qdrant Point 생성
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
                            "updated_at": row["updated_at"]
                        }
                    )
                    points.append(point)
            
            # Qdrant에 업로드
            if points:
                self.qdrant_client.upsert(
                    collection_name=self.collection_name,
                    points=points
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
        
        # Qdrant 카운트
        collection_info = self.qdrant_client.get_collection(self.collection_name)
        qdrant_count = collection_info.points_count
        
        print(f"  SQLite:  {sqlite_count['count']}개")
        print(f"  Qdrant:  {qdrant_count}개")
        
        if sqlite_count['count'] == qdrant_count:
            print("  ✓ 검증 성공")
            return True
        else:
            print("  ❌ 검증 실패: 개수 불일치")
            return False
    
    async def test_search(self, query: str = "MCP 설정"):
        """검색 테스트"""
        print(f"\n검색 테스트: '{query}'")
        
        from app.core.embeddings.service import EmbeddingService
        
        # 임베딩 생성
        embedding_service = EmbeddingService(self.settings)
        await embedding_service.initialize()
        
        try:
            query_embedding = await embedding_service.generate_embedding(query)
            
            # Qdrant 검색
            results = self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding.tolist(),
                limit=5
            )
            
            print(f"  결과: {len(results)}개")
            for i, result in enumerate(results, 1):
                print(f"  {i}. [{result.score:.3f}] {result.payload['content'][:80]}...")
        
        finally:
            await embedding_service.cleanup()


async def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description="SQLite → Qdrant 마이그레이션")
    parser.add_argument(
        "--qdrant-url",
        default="http://localhost:6333",
        help="Qdrant 서버 URL"
    )
    parser.add_argument(
        "--collection",
        default="mem-mesh",
        help="컬렉션 이름"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="배치 크기"
    )
    parser.add_argument(
        "--test-search",
        action="store_true",
        help="마이그레이션 후 검색 테스트"
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
        
        print("\n✅ 마이그레이션 완료!")
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await migrator.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
