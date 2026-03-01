#!/usr/bin/env python3
"""
프로젝트 통합 후 검색 테스트
"""

import asyncio
import os

from app.core.config import Settings
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.final_improved_search import FinalImprovedSearch
from app.mcp_integration.auto_context import MCPAutoContext


async def test_consolidated():
    """통합 후 검색 테스트"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(
        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        preload=False,
    )
    embedding_service.load_model()

    search = FinalImprovedSearch(db, embedding_service)
    auto_context = MCPAutoContext()

    print("=" * 80)
    print("✨ 프로젝트 통합 후 검색 테스트")
    print("=" * 80)

    # 현재 프로젝트
    current_project = auto_context.get_current_project()
    print(f"\n📁 현재 디렉토리: {os.path.basename(os.getcwd())}")
    print(f"🎯 자동 감지 프로젝트: {current_project}")

    # 프로젝트 통계
    conn = db.connection
    cursor = conn.execute("""
        SELECT project_id, COUNT(*) as count
        FROM memories
        WHERE project_id LIKE 'mem-mesh%'
        GROUP BY project_id
        ORDER BY count DESC
    """)

    print("\n📊 프로젝트별 메모리:")
    for project, count in cursor.fetchall():
        if project == current_project:
            print(f"  ✅ {project}: {count}개 (현재)")
        else:
            print(f"  ▫️ {project}: {count}개")

    # 검색 테스트
    print("\n" + "=" * 80)
    print("🔍 통합된 mem-mesh 프로젝트 검색")
    print("=" * 80)

    test_queries = [
        ("토큰", "Token optimization 관련"),
        ("최적화", "Optimization 전략"),
        ("검색 품질", "Search quality 개선"),
        ("캐시", "Cache management"),
        ("임베딩", "Embedding 관련"),
    ]

    for query, description in test_queries:
        print(f"\n📝 검색: '{query}' ({description})")
        print("-" * 60)

        # 자동 컨텍스트로 검색
        params = auto_context.build_search_query(query)

        results = await search.search(
            query=params["query"], limit=5, project_filter=params.get("project_filter")
        )

        if results.results:
            # 카테고리별 분류
            categories = {}
            for r in results.results:
                cat = r.category or "unknown"
                categories[cat] = categories.get(cat, 0) + 1

            print(f"  결과: {len(results.results)}개")
            print(
                f"  카테고리: {', '.join(f'{k}({v})' for k, v in categories.items())}"
            )

            # 상위 2개 결과
            for i, r in enumerate(results.results[:2]):
                print(f"\n  {i+1}. [{r.category}] {r.content[:60]}...")
                print(f"     프로젝트: {r.project_id}")
        else:
            print("  결과 없음")

    # 통합 효과 요약
    print("\n" + "=" * 80)
    print("📊 프로젝트 통합 효과")
    print("=" * 80)

    print("""
✅ **통합 완료**
   - 이전: mem-mesh-optimization, mem-mesh-search-quality 등 분산
   - 현재: mem-mesh로 통합 (131개 메모리)

📈 **개선 효과**
   - 맥락 유지: 모든 관련 메모리 통합 검색
   - 단순화: 디렉토리명 = 프로젝트 ID
   - 자동화: 현재 디렉토리 기반 자동 필터

💡 **사용법**
   ```python
   # 프로젝트 지정 불필요!
   search("토큰 최적화")
   # → 자동으로 project="mem-mesh" 적용
   ```
""")


if __name__ == "__main__":
    asyncio.run(test_consolidated())
