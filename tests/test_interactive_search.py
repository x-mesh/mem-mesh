#!/usr/bin/env python3
"""
대화형 검색 도구 테스트 스크립트
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from scripts.interactive_search import InteractiveSearchTool


async def test_interactive_search():
    """대화형 검색 도구 기본 테스트"""
    print("🔍 대화형 검색 도구 테스트 시작")
    
    search_tool = InteractiveSearchTool("data/memories.db", verbose=1)
    
    try:
        # 초기화
        await search_tool.initialize()
        
        # 사용 가능한 모델 표시
        search_tool.display_available_models()
        
        # 모델 전환 테스트
        print("\n🔄 모델 전환 테스트")
        success = await search_tool.switch_model("all-MiniLM-L6-v2")
        if success:
            print("✅ 모델 전환 성공")
        
        # 검색 테스트
        print("\n🔍 검색 테스트")
        await search_tool.search("버그 수정", limit=3)
        
        print("\n✅ 대화형 검색 도구 테스트 완료!")
        print("실제 대화형 모드를 사용하려면:")
        print("python scripts/interactive_search.py")
        
    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await search_tool.shutdown()


if __name__ == "__main__":
    asyncio.run(test_interactive_search())