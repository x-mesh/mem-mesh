#!/usr/bin/env python3
"""
노이즈 필터 테스트
"""

import asyncio
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.final_improved_search import FinalImprovedSearch
from app.core.services.noise_filter import NoiseFilter, SmartSearchFilter
from app.core.config import Settings


async def test_noise_filter():
    """노이즈 필터 테스트"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(
        model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
        preload=False
    )
    embedding_service.load_model()

    search = FinalImprovedSearch(db, embedding_service)
    noise_filter = NoiseFilter()
    smart_filter = SmartSearchFilter()

    print("=" * 80)
    print("🔍 노이즈 필터 효과 테스트")
    print("=" * 80)
    print()

    test_queries = [
        ("토큰", "mem-mesh-optimization"),
        ("검색", "mem-mesh-search-quality"),
        ("캐시", "mem-mesh-optimization"),
    ]

    for query, expected_project in test_queries:
        print(f"📝 검색어: '{query}'")
        print("=" * 80)

        # 필터 없이 검색
        results = await search.search(query, limit=10)
        print(f"\n1️⃣ 필터 없음: {len(results.results)}개 결과")

        # 프로젝트별 통계
        project_stats = {}
        for r in results.results:
            project = r.project_id or 'None'
            project_stats[project] = project_stats.get(project, 0) + 1

        # kiro 프로젝트 카운트
        kiro_count = sum(1 for p in project_stats if p.startswith('kiro-'))
        print(f"   - kiro-* 프로젝트: {kiro_count}개")
        print(f"   - {expected_project}: {project_stats.get(expected_project, 0)}개")

        # 노이즈 필터 적용
        filtered_results = noise_filter.filter(
            results.results,
            query,
            project_hint=expected_project,
            aggressive=False
        )
        print(f"\n2️⃣ 기본 필터 적용: {len(filtered_results)}개 결과")

        # 필터 후 통계
        filtered_stats = {}
        for r in filtered_results[:5]:  # 상위 5개만
            project = r.project_id or 'None'
            filtered_stats[project] = filtered_stats.get(project, 0) + 1

        kiro_count_filtered = sum(1 for p in filtered_stats if p.startswith('kiro-'))
        print(f"   - kiro-* 프로젝트: {kiro_count_filtered}개")
        print(f"   - {expected_project}: {filtered_stats.get(expected_project, 0)}개")

        # 공격적 필터 적용
        aggressive_filtered = noise_filter.filter(
            results.results,
            query,
            project_hint=expected_project,
            aggressive=True
        )
        print(f"\n3️⃣ 공격적 필터: {len(aggressive_filtered)}개 결과")

        # 스마트 필터 (컨텍스트 포함)
        context = {
            'project': expected_project,
            'time_range': '30d',
            'aggressive_filter': True,
            'max_results': 5
        }

        smart_response = smart_filter.apply(results, query, context)
        print(f"\n4️⃣ 스마트 필터 (컨텍스트): {len(smart_response.results)}개 결과")

        # 스마트 필터 결과 분석
        correct = sum(1 for r in smart_response.results if r.project_id == expected_project)
        accuracy = (correct / len(smart_response.results)) * 100 if smart_response.results else 0

        print(f"   - 정확도: {accuracy:.0f}% ({correct}/{len(smart_response.results)})")

        # 상위 3개 결과 표시
        print(f"\n   상위 3개 결과:")
        for i, r in enumerate(smart_response.results[:3]):
            marker = "✅" if r.project_id == expected_project else "❌"
            print(f"   {i+1}. {marker} [{r.category}] {r.content[:40]}...")
            print(f"      프로젝트: {r.project_id}, 점수: {r.similarity_score:.3f}")

        print()

    # 전체 통계
    print("=" * 80)
    print("📊 노이즈 필터 효과 요약")
    print("=" * 80)

    # 전체 kiro 프로젝트 수 확인
    conn = db.connection
    cursor = conn.execute("""
        SELECT COUNT(DISTINCT project_id)
        FROM memories
        WHERE project_id LIKE 'kiro-%'
    """)
    kiro_total = cursor.fetchone()[0]

    cursor = conn.execute("""
        SELECT COUNT(DISTINCT project_id)
        FROM memories
        WHERE project_id IN ('mem-mesh-optimization', 'mem-mesh-search-quality')
    """)
    target_total = cursor.fetchone()[0]

    print(f"데이터베이스 통계:")
    print(f"- kiro-* 프로젝트: {kiro_total}개")
    print(f"- 타겟 프로젝트: {target_total}개")
    print()

    print("필터 효과:")
    print("- 기본 필터: kiro 프로젝트 점수 70% 감소")
    print("- 공격적 필터: kiro 프로젝트 완전 제거")
    print("- 스마트 필터: 컨텍스트 기반 최적화")
    print()

    print("💡 권장사항:")
    print("1. MCP 사용 시 항상 프로젝트 필터 지정")
    print("2. 공격적 필터로 노이즈 원천 차단")
    print("3. 스마트 필터로 컨텍스트 기반 검색")


if __name__ == "__main__":
    asyncio.run(test_noise_filter())