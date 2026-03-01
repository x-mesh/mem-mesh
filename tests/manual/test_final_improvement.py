#!/usr/bin/env python3
"""
최종 개선 검색 테스트
"""

import asyncio

from app.core.config import Settings
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.final_improved_search import FinalImprovedSearch


async def test_final():
    """최종 검색 테스트"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    # 다국어 모델 명시
    embedding_service = EmbeddingService(
        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        preload=False,
    )
    embedding_service.load_model()

    # 최종 개선 검색
    search = FinalImprovedSearch(db, embedding_service)

    print("=" * 80)
    print("🏆 최종 개선 검색 테스트")
    print("=" * 80)
    print(f"임베딩 모델: {embedding_service.model_name}")
    print(f"차원: {embedding_service.dimension}")
    print()

    test_cases = [
        ("토큰", "mem-mesh-optimization"),
        ("최적화", "mem-mesh-optimization"),
        ("검색", "mem-mesh-search-quality"),
        ("품질", "mem-mesh-search-quality"),
        ("캐시", "mem-mesh-optimization"),
        ("캐싱", "mem-mesh-optimization"),
        ("임베딩", "mem-mesh-search-quality"),
        ("배치", "mem-mesh-optimization"),
        ("토큰 최적화", "mem-mesh-optimization"),
        ("검색 품질", "mem-mesh-search-quality"),
        ("캐시 관리", "mem-mesh-optimization"),
        ("의도 분석", "mem-mesh-search-quality"),
    ]

    # 프로젝트 필터 없이 테스트
    print("📊 프로젝트 필터 없이 검색 (실제 사용 시나리오)")
    print("=" * 80)

    total_correct = 0
    total_queries = len(test_cases)

    for query, expected in test_cases:
        print(f"\n검색어: '{query}' (기대 프로젝트: {expected})")
        print("-" * 40)

        results = await search.search(query, limit=5)

        correct = 0
        for i, r in enumerate(results.results[:5]):
            is_correct = r.project_id == expected
            if is_correct:
                correct += 1

            marker = "✅" if is_correct else "❌"
            print(f"  {i+1}. {marker} [{r.category}] {r.content[:50]}...")
            print(f"     점수: {r.similarity_score:.3f}, 프로젝트: {r.project_id}")

        accuracy = (
            (correct / min(5, len(results.results))) * 100 if results.results else 0
        )
        total_correct += accuracy
        print(f"  📊 정확도: {accuracy:.0f}% ({correct}/5)")

    # 전체 평균
    avg_accuracy = total_correct / total_queries
    print("\n" + "=" * 80)
    print("📊 최종 결과")
    print("=" * 80)
    print(f"평균 정확도 (필터 없이): {avg_accuracy:.1f}%")

    if avg_accuracy > 70:
        print("🎉 훌륭한 성능! 한국어 검색이 크게 개선되었습니다.")
    elif avg_accuracy > 40:
        print("✨ 상당한 개선! 기본 검색보다 훨씬 나아졌습니다.")
    elif avg_accuracy > 20:
        print("📈 개선됨! 추가 최적화가 필요합니다.")
    else:
        print("⚠️ 개선이 더 필요합니다.")

    # 프로젝트 필터로도 테스트
    print("\n" + "=" * 80)
    print("📊 프로젝트 필터 사용 시 (이상적 시나리오)")
    print("=" * 80)

    filter_correct = 0

    for query, expected in test_cases[:6]:  # 처음 6개만
        results = await search.search(query, limit=5, project_filter=expected)
        correct = sum(1 for r in results.results[:5] if r.project_id == expected)
        accuracy = (
            (correct / min(5, len(results.results))) * 100 if results.results else 0
        )
        filter_correct += accuracy
        print(f"'{query}': {accuracy:.0f}% ({correct}/5)")

    filter_avg = filter_correct / 6
    print(f"\n평균 정확도 (필터 사용): {filter_avg:.1f}%")


if __name__ == "__main__":
    asyncio.run(test_final())
