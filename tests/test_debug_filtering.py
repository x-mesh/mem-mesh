#!/usr/bin/env python3
"""
필터링 로직 디버깅
"""

import asyncio
import sys
import logging
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from app.core.storage.direct import DirectStorageBackend
from app.core.schemas.requests import SearchParams

# 디버그 로깅 설정
logging.basicConfig(level=logging.DEBUG)


async def test_filtering():
    """필터링 로직 테스트"""
    print("🔍 필터링 로직 디버깅")
    
    storage = DirectStorageBackend("data/memories.db")
    await storage.initialize()
    
    try:
        # threshold 검색 실행
        search_params = SearchParams(query="threshold", limit=5)
        result = await storage.search_memories(search_params)
        
        print(f"\n검색 결과: {len(result.results)}개")
        for i, res in enumerate(result.results, 1):
            print(f"{i}. [{res.category}] '{res.content}' (점수: {res.similarity_score})")
    
    except Exception as e:
        print(f"❌ 오류: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await storage.shutdown()


if __name__ == "__main__":
    asyncio.run(test_filtering())