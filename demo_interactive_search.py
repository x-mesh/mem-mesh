#!/usr/bin/env python3
"""
대화형 검색 도구 데모 스크립트
실제 사용법을 보여주는 시뮬레이션
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from scripts.interactive_search import InteractiveSearchTool


async def demo_interactive_search():
    """대화형 검색 도구 데모"""
    print("🎯 대화형 검색 도구 데모")
    print("=" * 60)
    
    search_tool = InteractiveSearchTool("data/memories.db", verbose=0)
    
    try:
        # 초기화
        await search_tool.initialize()
        
        print("\n1️⃣ 사용 가능한 모델 확인")
        search_tool.display_available_models()
        
        print("\n2️⃣ 모델 전환 (대형 모델로)")
        await search_tool.switch_model("all-mpnet-base-v2")
        
        print("\n3️⃣ 기본 검색")
        await search_tool.search("API 구현", limit=3)
        
        print("\n4️⃣ 카테고리 필터링 검색")
        await search_tool.search("데이터베이스", limit=3, category="decision")
        
        print("\n5️⃣ 프로젝트 필터링 검색")
        await search_tool.search("테스트", limit=2, project_id="kiro-conversations")
        
        print("\n6️⃣ 소형 모델로 전환하여 속도 비교")
        await search_tool.switch_model("all-MiniLM-L6-v2")
        await search_tool.search("성능 최적화", limit=3)
        
        print("\n" + "=" * 60)
        print("🎉 데모 완료!")
        print("\n💡 실제 대화형 모드 사용법:")
        print("   python scripts/interactive_search.py")
        print("\n📖 주요 명령어:")
        print("   models          - 모델 목록")
        print("   model <name>    - 모델 전환")
        print("   search <query>  - 검색")
        print("   limit <number>  - 결과 개수 설정")
        print("   help            - 도움말")
        print("   quit            - 종료")
        
    except Exception as e:
        print(f"❌ 데모 실패: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await search_tool.shutdown()


if __name__ == "__main__":
    asyncio.run(demo_interactive_search())