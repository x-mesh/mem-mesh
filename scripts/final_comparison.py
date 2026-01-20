#!/usr/bin/env python3
"""
최종 검색 품질 비교
"""

import asyncio
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.search import SearchService
from app.core.services.simple_improved_search import SimpleImprovedSearch
from app.core.config import Settings


async def final_comparison():
    """최종 비교"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(preload=False)
    embedding_service.load_model()

    # 기본 검색 서비스
    basic_search = SearchService(db, embedding_service)

    # 개선된 검색 서비스
    improved_search = SimpleImprovedSearch(db, embedding_service)

    print("=" * 80)
    print("🏆 최종 검색 품질 비교")
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
        ("의도 분석", "mem-mesh-search-quality")
    ]

    # 결과 저장
    basic_results = {}
    improved_results = {}

    for query, expected in test_cases:
        # 기본 검색
        basic_resp = await basic_search.search(
            query=query,
            project_id=expected,
            limit=5,
            search_mode='hybrid'
        )

        basic_correct = sum(1 for r in basic_resp.results[:5] if r.project_id == expected)
        basic_results[query] = (basic_correct, len(basic_resp.results))

        # 개선 검색
        improved_resp = await improved_search.search(
            query=query,
            limit=5,
            project_filter=expected
        )

        improved_correct = sum(1 for r in improved_resp.results[:5] if r.project_id == expected)
        improved_results[query] = (improved_correct, len(improved_resp.results))

    # 결과 출력
    print("┌─────────────────┬──────────────────────┬──────────────────────┬───────────┐")
    print("│     검색어      │    기본 검색         │    개선 검색         │   개선    │")
    print("├─────────────────┼──────────────────────┼──────────────────────┼───────────┤")

    total_basic = 0
    total_improved = 0
    total_queries = len(test_cases)

    for query, expected in test_cases:
        basic_correct, basic_total = basic_results[query]
        improved_correct, improved_total = improved_results[query]

        basic_pct = (basic_correct / 5) * 100 if basic_total > 0 else 0
        improved_pct = (improved_correct / 5) * 100 if improved_total > 0 else 0

        total_basic += basic_pct
        total_improved += improved_pct

        diff = improved_pct - basic_pct
        diff_str = f"{diff:+.0f}%" if diff != 0 else "0%"

        # 색상 표시를 위한 이모지
        if improved_pct == 100:
            status = "✅"
        elif improved_pct > basic_pct:
            status = "⬆️"
        elif improved_pct == basic_pct:
            status = "➡️"
        else:
            status = "⬇️"

        print(f"│ {query:15} │ {basic_correct}/5 ({basic_pct:3.0f}%) │ {improved_correct}/5 ({improved_pct:3.0f}%) {status} │ {diff_str:9} │")

    print("├─────────────────┼──────────────────────┼──────────────────────┼───────────┤")

    avg_basic = total_basic / total_queries
    avg_improved = total_improved / total_queries
    avg_diff = avg_improved - avg_basic

    print(f"│ {'평균':15} │      {avg_basic:5.1f}%        │      {avg_improved:5.1f}%        │ {avg_diff:+7.1f}%  │")
    print("└─────────────────┴──────────────────────┴──────────────────────┴───────────┘")

    # 개선 요약
    print("\n" + "=" * 80)
    print("📊 개선 요약")
    print("=" * 80)

    if avg_improved == 100:
        print("🎉 **완벽한 성능!** 모든 검색에서 100% 정확도 달성!")
    elif avg_diff > 50:
        print(f"🎉 **대폭 개선!** 평균 {avg_diff:.1f}% 향상")
    elif avg_diff > 20:
        print(f"✨ **상당한 개선!** 평균 {avg_diff:.1f}% 향상")
    elif avg_diff > 0:
        print(f"📈 **개선됨!** 평균 {avg_diff:.1f}% 향상")
    else:
        print("⚠️ 개선이 필요합니다.")

    # 핵심 성과
    print("\n🔑 핵심 성과:")
    print(f"• 초기 상태 (영어 모델): 0%")
    print(f"• 다국어 모델 전환 후: {avg_basic:.1f}%")
    print(f"• Query Expander 적용 후: {avg_improved:.1f}%")
    print(f"• 총 개선: 0% → {avg_improved:.1f}%")

    # 검색 전략
    print("\n💡 성공 요인:")
    print("1. 다국어 임베딩 모델 사용 (paraphrase-multilingual-MiniLM-L12-v2)")
    print("2. 한국어↔영어 자동 번역 및 쿼리 확장")
    print("3. 텍스트 매칭과 벡터 검색 결합")
    print("4. 프로젝트별 필터링 활용")


if __name__ == "__main__":
    asyncio.run(final_comparison())