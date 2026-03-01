#!/usr/bin/env python3
"""
차원 불일치 모델 전환 테스트
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from scripts.interactive_search import InteractiveSearchTool


async def test_dimension_mismatch():
    """차원 불일치 모델 전환 테스트"""
    print("🔍 차원 불일치 모델 전환 테스트")
    
    # 비대화형 모드로 설정 (자동 진행)
    search_tool = InteractiveSearchTool("data/memories.db", verbose=2)
    
    try:
        await search_tool.initialize()
        
        current_dim = search_tool.storage.embedding_service.dimension
        print(f"\n현재 모델 차원: {current_dim}")
        
        # 다른 차원의 모델로 전환 시도
        if current_dim == 384:
            test_model = "all-mpnet-base-v2"  # 768차원
            expected_dim = 768
        else:
            test_model = "all-MiniLM-L6-v2"  # 384차원
            expected_dim = 384
        
        print(f"테스트 모델: {test_model} ({expected_dim}차원)")
        print("예상 결과: 차원 불일치 경고 표시")
        
        # 모델 전환 (경고 메시지 확인)
        success = await search_tool.switch_model(test_model)
        
        if success:
            print("\n✅ 모델 전환 성공 (경고와 함께)")
            
            # 검색 테스트 (fallback 동작 확인)
            print("\n🔍 검색 테스트 (차원 불일치 상황)")
            await search_tool.search("벡터 검색 테스트", limit=3)
            
        else:
            print("\n❌ 모델 전환 실패 또는 사용자 취소")
        
    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await search_tool.shutdown()


if __name__ == "__main__":
    asyncio.run(test_dimension_mismatch())