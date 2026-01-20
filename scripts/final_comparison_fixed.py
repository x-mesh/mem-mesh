#!/usr/bin/env python3
"""
최종 검색 품질 비교 - 수정 버전
"""

import os
import asyncio
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.search import SearchService
from app.core.services.simple_improved_search import SimpleImprovedSearch
from app.core.config import Settings

# 환경 변수 명시적 설정
os.environ['MEM_MESH_EMBEDDING_MODEL'] = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'


async def final_comparison():
    """최종 비교"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    # 명시적으로 다국어 모델 지정
    embedding_service = EmbeddingService(
        model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
        preload=False
    )
    embedding_service.load_model()

    # 기본 검색 서비스
    basic_search = SearchService(db, embedding_service)

    # 개선된 검색 서비스
    improved_search = SimpleImprovedSearch(db, embedding_service)

    print("=" * 80)
    print("🏆 최종 검색 품질 비교 (수정 버전)")
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
        # 기본 검색 (프로젝트 필터 사용)
        basic_resp = await basic_search.search(
            query=query,
            project_id=expected,
            limit=5,
            search_mode='hybrid'
        )

        basic_correct = sum(1 for r in basic_resp.results[:5] if r.project_id == expected)
        basic_results[query] = (basic_correct, len(basic_resp.results))

        # 개선 검색 (프로젝트 필터 사용)
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

    # 프로젝트 필터 없이 테스트
    print("\n" + "=" * 80)
    print("📊 프로젝트 필터 없이 검색 (실제 검색 품질)")
    print("=" * 80)

    no_filter_results = {}

    for query, expected in test_cases[:6]:  # 처음 6개만 테스트
        print(f"\n검색어: '{query}'")

        # 프로젝트 필터 없이 검색
        results = await improved_search.search(query, limit=5)

        correct = 0
        for i, r in enumerate(results.results[:5]):
            is_correct = r.project_id == expected
            if is_correct:
                correct += 1

            marker = "✅" if is_correct else "❌"
            print(f"  {i+1}. {marker} [{r.category}] {r.content[:40]}...")

        accuracy = (correct / min(5, len(results.results))) * 100 if results.results else 0
        print(f"  정확도: {accuracy:.0f}%")
        no_filter_results[query] = accuracy

    # 개선 요약
    print("\n" + "=" * 80)
    print("📊 개선 요약")
    print("=" * 80)

    if avg_improved == 100 and avg_basic == 100:
        print("🎉 **프로젝트 필터 사용 시:** 기본 검색과 개선 검색 모두 100% 정확도!")
    elif avg_diff > 0:
        print(f"✨ **프로젝트 필터 사용 시:** 평균 {avg_diff:.1f}% 향상")

    if no_filter_results:
        no_filter_avg = sum(no_filter_results.values()) / len(no_filter_results)
        print(f"\n📌 **프로젝트 필터 없이:** 평균 {no_filter_avg:.1f}% 정확도")
        print("   (실제 사용자가 경험하는 검색 품질)")

    # 성공 요인
    print("\n💡 핵심 개선사항:")
    print("1. 영어 전용 모델 → 다국어 모델 전환")
    print("   (all-MiniLM-L6-v2 → paraphrase-multilingual-MiniLM-L12-v2)")
    print("2. 한국어↔영어 쿼리 확장 (300+ 용어 사전)")
    print("3. 텍스트 매칭 + 벡터 검색 하이브리드 접근")
    print("4. 프로젝트별 컨텍스트 필터링")

    print("\n🔍 검색 정확도 향상 과정:")
    print("• 초기 (영어 모델): 한국어 검색 0% 정확도")
    print("• 다국어 모델 전환: 기본적인 한국어 이해 가능")
    print("• Query Expander 적용: 동의어/번역어 확장")
    print("• 하이브리드 검색: 텍스트+벡터 결합")
    print(f"• 최종 결과: 프로젝트 필터 시 {avg_improved:.0f}%, 필터 없이 {no_filter_avg:.0f}%")


if __name__ == "__main__":
    asyncio.run(final_comparison())