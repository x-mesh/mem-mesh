#!/usr/bin/env python3
"""
검색어 인수 기능 테스트 스크립트
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from scripts.interactive_search import InteractiveSearchTool


async def test_query_argument():
    """검색어 인수 기능 테스트"""
    print("🔍 검색어 인수 기능 테스트 시작")
    
    search_tool = InteractiveSearchTool("data/memories.db", verbose=1)
    
    try:
        # 초기화
        await search_tool.initialize()
        
        print("\n1️⃣ 기본 검색 테스트")
        await search_tool.search("버그 수정", limit=3)
        
        print("\n2️⃣ 필터링 검색 테스트")
        await search_tool.search("API", limit=3, category="decision")
        
        print("\n3️⃣ 프로젝트 필터링 테스트")
        await search_tool.search("테스트", limit=2, project_id="kiro-conversations")
        
        print("\n✅ 검색어 인수 기능 테스트 완료!")
        print("\n💡 실제 사용 예시:")
        print('python scripts/interactive_search.py "버그 수정"')
        print('python scripts/interactive_search.py "API 구현" --model all-mpnet-base-v2 --limit 10')
        print('python scripts/interactive_search.py "데이터베이스" --category decision --project kiro-conversations')
        
    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await search_tool.shutdown()


if __name__ == "__main__":
    asyncio.run(test_query_argument())