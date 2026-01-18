#!/usr/bin/env python3
"""
디버깅: 검색 문제 분석
"""

import asyncio
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.simple_improved_search import SimpleImprovedSearch
from app.core.config import Settings


async def debug_search():
    """검색 디버그"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    # 다국어 모델 명시
    embedding_service = EmbeddingService(
        model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
        preload=False
    )
    embedding_service.load_model()

    # 개선된 검색
    search = SimpleImprovedSearch(db, embedding_service)

    print("=" * 60)
    print("🔍 검색 디버그")
    print("=" * 60)

    # '토큰' 검색 (프로젝트 필터 없이)
    query = "토큰"
    print(f"\n검색어: '{query}' (프로젝트 필터 없음)")
    print("-" * 40)

    results = await search.search(query, limit=10)

    print(f"총 {len(results.results)}개 결과:")
    for i, r in enumerate(results.results[:10]):
        print(f"\n{i+1}. [{r.category}] {r.content[:50]}...")
        print(f"   프로젝트: {r.project_id}")
        print(f"   점수: {r.similarity_score:.4f}")
        print(f"   태그: {r.tags}")

    # 예상 프로젝트의 메모리 확인
    print("\n" + "=" * 60)
    print("📋 'mem-mesh-optimization' 프로젝트 메모리 확인")
    print("=" * 60)

    conn = db.connection
    cursor = conn.execute("""
        SELECT content, category
        FROM memories
        WHERE project_id = 'mem-mesh-optimization'
        AND (content LIKE '%토큰%' OR content LIKE '%token%')
        LIMIT 5
    """)
    token_memories = cursor.fetchall()

    for i, (content, category) in enumerate(token_memories):
        print(f"\n{i+1}. [{category}] {content[:100]}...")

    # 확장된 쿼리로 검색
    print("\n" + "=" * 60)
    print("🔍 확장 쿼리 테스트")
    print("=" * 60)

    expanded_queries = ["token", "토큰", "token optimization", "토큰 최적화"]

    for eq in expanded_queries:
        print(f"\n쿼리: '{eq}'")
        results = await search.search(eq, limit=3)

        # mem-mesh-optimization 결과 카운트
        opt_count = sum(1 for r in results.results if r.project_id == 'mem-mesh-optimization')
        print(f"  mem-mesh-optimization 결과: {opt_count}/{len(results.results)}")

        if results.results:
            print(f"  첫 번째 결과: [{results.results[0].category}] {results.results[0].content[:30]}...")
            print(f"  프로젝트: {results.results[0].project_id}")


if __name__ == "__main__":
    asyncio.run(debug_search())