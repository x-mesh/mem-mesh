#!/usr/bin/env python3
"""
Query Expander 테스트 - 한국어/영어 확장 검증
"""

import asyncio
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.search import SearchService
from app.core.services.query_expander import QueryExpander
from app.core.config import Settings


async def test_query_expander():
    """Query Expander 테스트"""

    print("="*60)
    print("Query Expander 테스트")
    print("="*60)

    # Query Expander 테스트
    expander = QueryExpander()

    test_queries = [
        "토큰",
        "토큰 최적화",
        "검색 품질",
        "캐시 메모리",
        "token optimization",
        "search quality"
    ]

    print("\n1️⃣ Query Expansion 테스트")
    print("-"*40)
    for query in test_queries:
        expanded = expander.expand_query(query)
        print(f"원본: '{query}'")
        print(f"확장: '{expanded}'")
        print(f"  단어 수: {len(query.split())} → {len(expanded.split())}")
        print()

    # 실제 검색 테스트
    print("\n2️⃣ 실제 검색 테스트 (Query Expansion 적용)")
    print("-"*40)

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(preload=False)
    search_service = SearchService(db, embedding_service)

    # 테스트 검색어
    test_searches = [
        ("토큰", "mem-mesh-optimization"),
        ("최적화", "mem-mesh-optimization"),
        ("검색", "mem-mesh-search-quality"),
        ("품질", "mem-mesh-search-quality")
    ]

    for query, expected_project in test_searches:
        print(f"\n🔍 검색어: '{query}' (기대 프로젝트: {expected_project})")

        # 검색 실행
        response = await search_service.search(
            query=query,
            limit=5,
            search_mode='hybrid'
        )

        print(f"   결과 수: {len(response.results)}")

        # 프로젝트별 결과 수 계산
        project_counts = {}
        for r in response.results:
            proj = r.project_id or "None"
            project_counts[proj] = project_counts.get(proj, 0) + 1

        print("   프로젝트별 분포:")
        for proj, count in sorted(project_counts.items(), key=lambda x: x[1], reverse=True)[:3]:
            print(f"     - {proj}: {count}개")

        # 상위 3개 결과 표시
        for i, r in enumerate(response.results[:3], 1):
            print(f"   {i}. [{r.category}] {r.content[:60]}...")
            print(f"      점수: {r.similarity_score:.3f}, 프로젝트: {r.project_id}")

    # 언어 감지 테스트
    print("\n3️⃣ 언어 감지 테스트")
    print("-"*40)
    test_texts = [
        "토큰 최적화",
        "token optimization",
        "토큰 token 최적화 optimization",
        "검색 search 품질 quality"
    ]

    for text in test_texts:
        lang = expander.get_language(text)
        is_korean = expander.is_korean(text)
        is_english = expander.is_english(text)
        print(f"'{text}'")
        print(f"  언어: {lang}, 한국어: {is_korean}, 영어: {is_english}")

    # 연관 검색어 제안
    print("\n4️⃣ 연관 검색어 제안")
    print("-"*40)
    for query in ["토큰", "최적화", "cache", "memory"]:
        suggestions = expander.suggest_terms(query)
        print(f"'{query}' → 제안: {suggestions}")


if __name__ == "__main__":
    asyncio.run(test_query_expander())