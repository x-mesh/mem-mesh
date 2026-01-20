#!/usr/bin/env python3
"""
데이터베이스의 임베딩이 다국어 모델로 제대로 변경되었는지 확인
"""

import asyncio
import numpy as np
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.config import Settings


async def verify_embeddings():
    """임베딩 검증"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(preload=False)
    embedding_service.load_model()

    print(f"모델: {embedding_service.model_name}")
    print(f"차원: {embedding_service.dimension}")
    print("="*60)

    # 한국어 검색어의 임베딩 생성
    query_emb = embedding_service.embed("토큰")

    # 데이터베이스에서 특정 메모리 가져오기
    cursor = await db.execute(
        """
        SELECT id, content, embedding
        FROM memories
        WHERE project_id = 'mem-mesh-optimization'
        AND content LIKE '%Token Optimization Strategy%'
        LIMIT 1
        """
    )
    row = cursor.fetchone()

    if row:
        memory_id = row[0]
        content = row[1]
        stored_emb = embedding_service.from_bytes(row[2])

        print(f"메모리 ID: {memory_id}")
        print(f"내용: {content[:100]}...")
        print(f"저장된 임베딩 차원: {len(stored_emb)}")
        print(f"쿼리 임베딩 차원: {len(query_emb)}")

        # 유사도 계산
        def cosine_similarity(a, b):
            return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

        # 다양한 쿼리로 테스트
        test_queries = [
            "토큰",
            "token",
            "토큰 최적화",
            "Token Optimization"
        ]

        print("\n유사도 테스트:")
        for q in test_queries:
            q_emb = embedding_service.embed(q)
            sim = cosine_similarity(q_emb, stored_emb)
            print(f"  '{q}' → {sim:.3f}")

        # 현재 임베딩이 올바른지 확인
        print("\n임베딩 재생성 비교:")
        new_emb = embedding_service.embed(content)
        sim_new = cosine_similarity(stored_emb, new_emb)
        print(f"  저장된 임베딩 vs 새로 생성한 임베딩: {sim_new:.3f}")

        if sim_new < 0.99:
            print("  ⚠️ 임베딩이 일치하지 않습니다! 재생성이 필요할 수 있습니다.")
        else:
            print("  ✅ 임베딩이 일치합니다.")

    # 한국어 메모리 테스트
    cursor = await db.execute(
        """
        SELECT id, content, embedding
        FROM memories
        WHERE project_id = 'mem-mesh-thread-summary-kr'
        AND content LIKE '%토큰%'
        LIMIT 1
        """
    )
    row = cursor.fetchone()

    if row:
        print("\n" + "="*60)
        print("한국어 메모리 테스트:")
        content = row[1]
        stored_emb = embedding_service.from_bytes(row[2])

        print(f"내용: {content[:100]}...")

        for q in ["토큰", "token", "최적화", "optimization"]:
            q_emb = embedding_service.embed(q)
            sim = cosine_similarity(q_emb, stored_emb)
            print(f"  '{q}' → {sim:.3f}")


if __name__ == "__main__":
    asyncio.run(verify_embeddings())