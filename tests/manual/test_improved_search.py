#!/usr/bin/env python3
"""
개선된 검색 서비스 테스트
"""

import asyncio
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.search import SearchService
from app.core.services.improved_search import ImprovedSearchService
from app.core.config import Settings


async def test_improved_search():
    """개선된 검색 테스트"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(preload=False)
    embedding_service.load_model()

    # 기본 검색 서비스
    basic_search = SearchService(db, embedding_service)

    # 개선된 검색 서비스
    improved_search = ImprovedSearchService(db, embedding_service)

    print("=" * 60)
    print("🔍 개선된 검색 서비스 테스트")
    print("=" * 60)
    print(f"모델: {embedding_service.model_name}")
    print(f"차원: {embedding_service.dimension}")
    print()

    # 테스트 쿼리
    test_queries = [
        ("토큰", "mem-mesh-optimization"),
        ("토큰 최적화", "mem-mesh-optimization"),
        ("검색 품질", "mem-mesh-search-quality"),
        ("캐싱", "mem-mesh-optimization"),
        ("임베딩", "mem-mesh-search-quality"),
        ("배치", "mem-mesh-optimization"),
        ("의도 분석", "mem-mesh-search-quality"),
        ("Query Expander", "mem-mesh-search-issue")
    ]

    # 각 서비스별 결과 저장
    basic_scores = []
    improved_scores = []

    for query, expected_project in test_queries:
        print(f"\n{'='*60}")
        print(f"📝 검색어: '{query}' (기대 프로젝트: {expected_project})")
        print("-" * 60)

        # 1. 기본 검색
        print("\n1️⃣ 기본 검색 (SearchService):")
        basic_results = await basic_search.search(
            query=query,
            limit=5,
            search_mode='hybrid'
        )

        basic_correct = 0
        for i, r in enumerate(basic_results.results[:5]):
            is_correct = r.project_id == expected_project
            if is_correct:
                basic_correct += 1
            marker = "✅" if is_correct else "❌"
            print(f"  {i+1}. {marker} [{r.category}] {r.content[:50]}...")
            if i < 3:  # 상위 3개만 자세히
                print(f"     점수: {r.similarity_score:.3f}, 프로젝트: {r.project_id}")

        basic_accuracy = (basic_correct / 5) * 100 if basic_results.results else 0
        basic_scores.append(basic_accuracy)
        print(f"  📊 정확도: {basic_accuracy:.0f}%")

        # 2. 개선된 검색
        print("\n2️⃣ 개선된 검색 (ImprovedSearchService):")
        improved_results = await improved_search.search(
            query=query,
            limit=5,
            search_mode='smart'
        )

        improved_correct = 0
        for i, r in enumerate(improved_results.results[:5]):
            is_correct = r.project_id == expected_project
            if is_correct:
                improved_correct += 1
            marker = "✅" if is_correct else "❌"
            print(f"  {i+1}. {marker} [{r.category}] {r.content[:50]}...")
            if i < 3:  # 상위 3개만 자세히
                print(f"     점수: {r.similarity_score:.3f}, 프로젝트: {r.project_id}")

        improved_accuracy = (improved_correct / 5) * 100 if improved_results.results else 0
        improved_scores.append(improved_accuracy)
        print(f"  📊 정확도: {improved_accuracy:.0f}%")

        # 메타데이터 출력
        if hasattr(improved_results, 'metadata') and improved_results.metadata:
            meta = improved_results.metadata
            print(f"  📈 소스: 텍스트={meta.get('text_count', 0)}, "
                  f"벡터={meta.get('vector_count', 0)}, "
                  f"둘다={meta.get('both_count', 0)}")

        # 3. 개선 비교
        improvement = improved_accuracy - basic_accuracy
        if improvement > 0:
            print(f"\n  ✨ 개선: {improvement:+.0f}%")
        elif improvement == 0:
            print(f"\n  ➡️ 동일")
        else:
            print(f"\n  ⚠️ 악화: {improvement:.0f}%")

    # 전체 요약
    print("\n" + "=" * 60)
    print("📊 전체 결과 요약")
    print("=" * 60)

    print("\n검색어별 정확도:")
    print("┌─────────────────────┬──────────┬──────────┬───────────┐")
    print("│ 검색어              │   기본   │  개선됨  │   차이    │")
    print("├─────────────────────┼──────────┼──────────┼───────────┤")

    for i, (query, _) in enumerate(test_queries):
        diff = improved_scores[i] - basic_scores[i]
        diff_str = f"{diff:+.0f}%" if diff != 0 else "0%"
        print(f"│ {query:19} │  {basic_scores[i]:5.0f}%  │  {improved_scores[i]:5.0f}%  │  {diff_str:8} │")

    print("├─────────────────────┼──────────┼──────────┼───────────┤")

    avg_basic = sum(basic_scores) / len(basic_scores)
    avg_improved = sum(improved_scores) / len(improved_scores)
    avg_diff = avg_improved - avg_basic

    print(f"│ {'평균':19} │  {avg_basic:5.1f}%  │  {avg_improved:5.1f}%  │  {avg_diff:+6.1f}%  │")
    print("└─────────────────────┴──────────┴──────────┴───────────┘")

    # 최종 평가
    print("\n" + "=" * 60)
    print("✨ 최종 평가")
    print("=" * 60)

    if avg_diff > 0:
        print(f"🎉 평균 {avg_diff:.1f}% 개선되었습니다!")
        print(f"   기본 검색: {avg_basic:.1f}%")
        print(f"   개선 검색: {avg_improved:.1f}%")
    else:
        print(f"⚠️ 개선이 필요합니다.")

    # 가장 개선된 항목
    improvements = [(test_queries[i][0], improved_scores[i] - basic_scores[i])
                   for i in range(len(test_queries))]
    improvements.sort(key=lambda x: x[1], reverse=True)

    if improvements[0][1] > 0:
        print(f"\n🏆 가장 개선된 검색어:")
        for query, improvement in improvements[:3]:
            if improvement > 0:
                print(f"   '{query}': +{improvement:.0f}%")


if __name__ == "__main__":
    asyncio.run(test_improved_search())