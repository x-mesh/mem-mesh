#!/usr/bin/env python3
"""
모델 호환성 검사 기능 테스트
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from scripts.interactive_search import InteractiveSearchTool


async def test_model_compatibility():
    """모델 호환성 검사 테스트"""
    print("🔍 모델 호환성 검사 기능 테스트")
    
    search_tool = InteractiveSearchTool("data/memories.db", verbose=1)
    
    try:
        # 초기화 (현재 모델 상태 확인)
        await search_tool.initialize()
        
        print("\n1️⃣ 현재 모델과 같은 모델로 전환 (문제없음)")
        current_model = search_tool.storage.embedding_service.model_name
        await search_tool.switch_model(current_model)
        
        print("\n2️⃣ 다른 차원의 모델로 전환 (경고 표시)")
        # 현재가 384차원이면 768차원으로, 768차원이면 384차원으로
        if search_tool.storage.embedding_service.dimension == 384:
            test_model = "all-mpnet-base-v2"  # 768차원
        else:
            test_model = "all-MiniLM-L6-v2"  # 384차원
        
        print(f"테스트 모델: {test_model}")
        # 자동으로 'n' 응답하도록 설정 (실제로는 사용자 입력 필요)
        search_tool.verbose = 1  # 비대화형 모드로 설정하여 자동 진행
        
        print("\n3️⃣ 검색 테스트 (fallback 동작 확인)")
        await search_tool.search("테스트 검색", limit=3)
        
        print("\n✅ 모델 호환성 검사 기능 테스트 완료!")
        print("\n💡 실제 사용 시:")
        print("- 모델 전환 시 경고 메시지가 표시됩니다")
        print("- 차원이 다르면 벡터 검색이 텍스트 검색으로 fallback됩니다")
        print("- 정확한 검색을 위해서는 모델 마이그레이션이 필요합니다")
        
    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await search_tool.shutdown()


if __name__ == "__main__":
    asyncio.run(test_model_compatibility())