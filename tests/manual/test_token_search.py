#!/usr/bin/env python3
"""
토큰 검색 품질 테스트 - 문제 진단
"""

import asyncio

from app.core.config import Settings
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.enhanced_search import EnhancedSearchService
from app.core.services.search import SearchService


async def test_token_search():
    """토큰 관련 검색 테스트"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(preload=False)
    basic_search = SearchService(db, embedding_service)
    enhanced_search = EnhancedSearchService(
        db,
        embedding_service,
        enable_quality_scoring=True,
        enable_feedback=False,
        enable_dynamic_embedding=False,
    )

    print("=" * 60)
    print("토큰 검색 테스트 - 문제 진단")
    print("=" * 60)

    # 여러 검색어 테스트
    test_queries = ["토큰", "token", "토큰 최적화", "token optimization"]

    for query in test_queries:
        print(f"\n🔍 검색어: '{query}'")
        print("-" * 40)

        # 1. Basic Search - 하이브리드 모드
        print("\n1️⃣ Basic Search (hybrid mode):")
        try:
            response = await basic_search.search(
                query=query, limit=5, search_mode="hybrid"
            )

            print(f"   결과 수: {len(response.results)}")
            for i, r in enumerate(response.results[:3], 1):
                print(f"   {i}. [{r.category}] {r.content[:80]}...")
                print(f"      점수: {r.similarity_score:.3f}, 프로젝트: {r.project_id}")
        except Exception as e:
            print(f"   오류: {e}")

        # 2. Basic Search - 텍스트 전용 모드
        print("\n2️⃣ Basic Search (text mode):")
        try:
            response = await basic_search.search(
                query=query, limit=5, search_mode="text"
            )

            print(f"   결과 수: {len(response.results)}")
            for i, r in enumerate(response.results[:3], 1):
                print(f"   {i}. [{r.category}] {r.content[:80]}...")
                print(f"      프로젝트: {r.project_id}")
        except Exception as e:
            print(f"   오류: {e}")

        # 3. Enhanced Search - 스마트 모드
        print("\n3️⃣ Enhanced Search (smart mode):")
        try:
            response = await enhanced_search.search(
                query=query, limit=5, search_mode="smart", performance_mode="balanced"
            )

            print(f"   결과 수: {len(response.results)}")
            for i, r in enumerate(response.results[:3], 1):
                print(f"   {i}. [{r.category}] {r.content[:80]}...")
                if hasattr(r, "quality_score"):
                    print(
                        f"      품질점수: {r.quality_score:.3f}, 프로젝트: {r.project_id}"
                    )
                else:
                    print(
                        f"      점수: {r.similarity_score:.3f}, 프로젝트: {r.project_id}"
                    )

            if hasattr(response, "metadata"):
                print(
                    f"   의도 분석: {response.metadata.get('intent', {}).get('type', 'unknown')}"
                )
        except Exception as e:
            print(f"   오류: {e}")

    # 프로젝트별 필터링 테스트
    print("\n" + "=" * 60)
    print("프로젝트 필터링 테스트")
    print("=" * 60)

    projects = [
        "mem-mesh-optimization",
        "mem-mesh-search-quality",
        "mem-mesh-thread-summary-kr",
    ]

    for project_id in projects:
        print(f"\n📁 프로젝트: {project_id}")
        response = await basic_search.search(
            query="토큰", project_id=project_id, limit=3, search_mode="hybrid"
        )
        print(f"   결과 수: {len(response.results)}")
        if response.results:
            print(f"   첫 결과: {response.results[0].content[:100]}...")

    # 직접 SQL로 확인
    print("\n" + "=" * 60)
    print("직접 SQL 쿼리 테스트")
    print("=" * 60)

    cursor = await db.execute("""
        SELECT content, project_id, category
        FROM memories
        WHERE content LIKE '%토큰%' OR content LIKE '%token%'
        LIMIT 10
        """)
    rows = cursor.fetchall()

    print(f"\nSQL LIKE 검색 결과: {len(rows)}개")
    for i, row in enumerate(rows[:5], 1):
        print(f"{i}. [{row[2]}] 프로젝트: {row[1]}")
        print(f"   {row[0][:100]}...")

    # 임베딩 테스트
    print("\n" + "=" * 60)
    print("임베딩 생성 테스트")
    print("=" * 60)

    test_texts = [
        "토큰 최적화",
        "token optimization",
        "토큰을 줄이는 방법",
        "reducing tokens",
    ]

    for text in test_texts:
        embedding = await embedding_service.get_embedding(text)
        print(f"'{text}' 임베딩 크기: {len(embedding)}")
        print(f"  첫 5개 값: {embedding[:5]}")

    # 유사도 비교
    print("\n유사도 비교:")
    emb1 = await embedding_service.get_embedding("토큰")
    emb2 = await embedding_service.get_embedding("token")
    emb3 = await embedding_service.get_embedding("최적화")
    emb4 = await embedding_service.get_embedding("검색")

    import numpy as np

    def cosine_similarity(a, b):
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

    print(f"'토큰' vs 'token': {cosine_similarity(emb1, emb2):.3f}")
    print(f"'토큰' vs '최적화': {cosine_similarity(emb1, emb3):.3f}")
    print(f"'토큰' vs '검색': {cosine_similarity(emb1, emb4):.3f}")


if __name__ == "__main__":
    asyncio.run(test_token_search())
