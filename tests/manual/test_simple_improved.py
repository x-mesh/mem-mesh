#!/usr/bin/env python3
"""
간단한 개선 검색 테스트
"""

import asyncio
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.search import SearchService
from app.core.services.simple_improved_search import SimpleImprovedSearch
from app.core.config import Settings


async def test_simple_improved():
    """간단한 개선 검색 테스트"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(preload=False)
    embedding_service.load_model()

    # 기본 검색
    SearchService(db, embedding_service)

    # 간단한 개선 검색
    simple_search = SimpleImprovedSearch(db, embedding_service)

    print("=" * 60)
    print("🔍 간단한 개선 검색 테스트")
    print("=" * 60)

    test_queries = [
        ("토큰", "mem-mesh-optimization"),
        ("토큰 최적화", "mem-mesh-optimization"),
        ("검색 품질", "mem-mesh-search-quality"),
        ("캐싱", "mem-mesh-optimization"),
        ("임베딩", "mem-mesh-search-quality")
    ]

    for query, expected_project in test_queries:
        print(f"\n📝 검색어: '{query}' (기대: {expected_project})")
        print("-" * 40)

        # 간단한 개선 검색
        results = await simple_search.search(query, limit=5, project_filter=expected_project)

        correct = 0
        for i, r in enumerate(results.results[:5]):
            is_correct = r.project_id == expected_project
            if is_correct:
                correct += 1

            marker = "✅" if is_correct else "❌"
            print(f"  {i+1}. {marker} [{r.category}] {r.content[:60]}...")
            print(f"     점수: {r.similarity_score:.3f}, 프로젝트: {r.project_id}")

        accuracy = (correct / min(5, len(results.results))) * 100 if results.results else 0
        print(f"  📊 정확도: {accuracy:.0f}%")

    # 프로젝트 필터 없이도 테스트
    print("\n" + "=" * 60)
    print("프로젝트 필터 없이 테스트")
    print("=" * 60)

    for query, expected_project in test_queries[:3]:
        print(f"\n📝 검색어: '{query}' (기대: {expected_project})")

        results = await simple_search.search(query, limit=5)

        found_projects = {}
        for r in results.results:
            proj = r.project_id or "None"
            found_projects[proj] = found_projects.get(proj, 0) + 1

        # 가장 많이 나온 프로젝트
        if found_projects:
            top_project = max(found_projects.items(), key=lambda x: x[1])
            print(f"  최다 프로젝트: {top_project[0]} ({top_project[1]}개)")

        # 기대 프로젝트 개수
        expected_count = found_projects.get(expected_project, 0)
        print(f"  기대 프로젝트 결과: {expected_count}/5개")

        # 상위 2개만 표시
        for i, r in enumerate(results.results[:2]):
            print(f"  {i+1}. [{r.category}] {r.content[:50]}...")
            print(f"     프로젝트: {r.project_id}")


if __name__ == "__main__":
    asyncio.run(test_simple_improved())