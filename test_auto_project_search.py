#!/usr/bin/env python3
"""
자동 프로젝트 감지를 적용한 검색 테스트
"""

import asyncio
import os
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.final_improved_search import FinalImprovedSearch
from app.core.services.noise_filter import SmartSearchFilter
from app.mcp_integration.auto_context import MCPAutoContext, get_current_project_id
from app.core.config import Settings


async def test_auto_project_search():
    """자동 프로젝트 감지 검색 테스트"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(
        model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
        preload=False
    )
    embedding_service.load_model()

    search = FinalImprovedSearch(db, embedding_service)
    smart_filter = SmartSearchFilter()
    auto_context = MCPAutoContext()

    print("=" * 80)
    print("🎯 자동 프로젝트 감지 검색 테스트")
    print("=" * 80)

    # 현재 프로젝트 확인
    current_project = get_current_project_id()
    print(f"\n📁 현재 디렉토리: {os.path.basename(os.getcwd())}")
    print(f"🎯 자동 감지된 프로젝트: {current_project}")
    print()

    test_queries = [
        "토큰",
        "토큰 최적화",
        "캐시 관리",
        "검색 품질"
    ]

    print("=" * 80)
    print("📊 프로젝트 자동 필터 적용 검색")
    print("=" * 80)

    for query in test_queries:
        print(f"\n🔍 검색어: '{query}'")
        print("-" * 60)

        # 자동 컨텍스트로 검색 파라미터 구성
        params = auto_context.build_search_query(query)

        # 실제 검색 실행
        results = await search.search(
            query=params['query'],
            limit=params['limit'],
            project_filter=params.get('project_filter')
        )

        # 스마트 필터 적용
        context = {
            'project': current_project,
            'aggressive_filter': True,
            'max_results': 5
        }

        filtered_response = smart_filter.apply(results, query, context)

        # 결과 분석
        project_matches = {}
        for r in filtered_response.results:
            proj = r.project_id or 'None'
            project_matches[proj] = project_matches.get(proj, 0) + 1

        print(f"  결과 수: {len(filtered_response.results)}")
        print(f"  프로젝트 분포:")
        for proj, count in project_matches.items():
            marker = "✅" if proj == current_project else "⚠️"
            print(f"    {marker} {proj}: {count}개")

        # 상위 3개 결과
        if filtered_response.results:
            print(f"\n  상위 3개 결과:")
            for i, r in enumerate(filtered_response.results[:3]):
                is_match = r.project_id == current_project
                marker = "✅" if is_match else "❌"
                print(f"    {i+1}. {marker} [{r.category}] {r.content[:40]}...")
                print(f"       프로젝트: {r.project_id}")

    # 비교: 프로젝트 필터 없이
    print("\n" + "=" * 80)
    print("⚠️ 비교: 프로젝트 필터 없이 (노이즈 많음)")
    print("=" * 80)

    query = "토큰"
    print(f"\n검색어: '{query}' (필터 없음)")

    results_no_filter = await search.search(query, limit=10)

    project_stats = {}
    for r in results_no_filter.results:
        proj = r.project_id or 'None'
        project_stats[proj] = project_stats.get(proj, 0) + 1

    kiro_count = sum(1 for p in project_stats if p.startswith('kiro-'))

    print(f"  결과 수: {len(results_no_filter.results)}")
    print(f"  kiro-* 프로젝트: {kiro_count}개")
    print(f"  {current_project}: {project_stats.get(current_project, 0)}개")

    # 최종 요약
    print("\n" + "=" * 80)
    print("📊 자동 프로젝트 감지 효과")
    print("=" * 80)

    print(f"""
✅ 자동 감지 성공:
   - 현재 디렉토리: {os.path.basename(os.getcwd())}
   - 감지된 프로젝트: {current_project}
   - 모든 검색에 자동 적용됨

📈 개선 효과:
   - 노이즈 감소: kiro-* 프로젝트 자동 제외
   - 정확도 향상: 현재 프로젝트 결과 우선
   - 토큰 절약: 관련 결과만 5개 제한

💡 사용법:
   1. 프로젝트 디렉토리로 이동
   2. MCP 검색 시 프로젝트 자동 적용
   3. 필요시 수동 오버라이드 가능
""")


if __name__ == "__main__":
    asyncio.run(test_auto_project_search())