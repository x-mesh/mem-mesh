#!/usr/bin/env python3
"""
다양한 검색 모드로 threshold 검색 결과 비교
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from app.core.schemas.requests import SearchParams
from app.core.storage.direct import DirectStorageBackend


async def test_search_modes():
    """다양한 검색 모드로 threshold 검색 테스트"""
    print("🔍 다양한 검색 모드로 threshold 검색 비교")

    storage = DirectStorageBackend("data/memories.db")
    await storage.initialize()

    search_modes = ["hybrid", "exact", "semantic", "fuzzy"]
    queries = ["threshold", "threshold1"]

    try:
        for query in queries:
            print(f"\n{'='*80}")
            print(f"🔍 검색어: '{query}'")
            print(f"{'='*80}")

            for mode in search_modes:
                print(f"\n📋 검색 모드: {mode}")
                print("-" * 50)

                search_params = SearchParams(query=query, limit=3, search_mode=mode)

                try:
                    result = await storage.search_memories(search_params)

                    if result.results:
                        for i, res in enumerate(result.results, 1):
                            content = (
                                res.content[:100] + "..."
                                if len(res.content) > 100
                                else res.content
                            )
                            score = getattr(res, "similarity_score", "N/A")
                            print(f"  {i}. [{res.category}] {content} (점수: {score})")
                    else:
                        print("  결과 없음")

                except Exception as e:
                    print(f"  ❌ 오류: {e}")

        # 추가 분석: "understood" 메모리들 확인
        print(f"\n{'='*80}")
        print("🔍 'understood' 메모리들 분석")
        print(f"{'='*80}")

        understood_params = SearchParams(
            query="understood", limit=5, search_mode="exact"
        )

        result = await storage.search_memories(understood_params)

        if result.results:
            print(f"총 {len(result.results)}개의 'understood' 메모리 발견:")
            for i, res in enumerate(result.results, 1):
                print(f"  {i}. [{res.category}] {res.id[:8]}... - {res.project_id}")
                print(f"     내용: '{res.content}'")
                print(f"     생성일: {res.created_at}")

    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        import traceback

        traceback.print_exc()
    finally:
        await storage.shutdown()


if __name__ == "__main__":
    asyncio.run(test_search_modes())
