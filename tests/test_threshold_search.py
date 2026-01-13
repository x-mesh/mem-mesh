#!/usr/bin/env python3
"""
threshold vs threshold1 검색 결과 비교 테스트
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from scripts.interactive_search import InteractiveSearchTool


async def test_threshold_search():
    """threshold 검색 문제 분석"""
    print("🔍 threshold vs threshold1 검색 결과 비교 테스트")
    
    search_tool = InteractiveSearchTool("data/memories.db", verbose=1)
    
    try:
        await search_tool.initialize()
        
        current_model = search_tool.storage.embedding_service.model_name
        print(f"\n현재 모델: {current_model}")
        
        # 1. threshold1 검색
        print("\n" + "="*60)
        print("1️⃣ 'threshold1' 검색 결과")
        print("="*60)
        await search_tool.search("threshold1", limit=5)
        
        # 2. threshold 검색
        print("\n" + "="*60)
        print("2️⃣ 'threshold' 검색 결과")
        print("="*60)
        await search_tool.search("threshold", limit=5)
        
        # 3. 부분 문자열 검색 테스트
        print("\n" + "="*60)
        print("3️⃣ 'thresh' 검색 결과")
        print("="*60)
        await search_tool.search("thresh", limit=5)
        
        # 4. 정확한 단어 검색
        print("\n" + "="*60)
        print("4️⃣ 'search_threshold' 검색 결과")
        print("="*60)
        await search_tool.search("search_threshold", limit=5)
        
        print("\n" + "="*60)
        print("📊 분석 결과")
        print("="*60)
        print("- threshold1과 threshold 검색 결과를 비교해보세요")
        print("- 토큰화 방식이나 벡터 임베딩에서 차이가 있을 수 있습니다")
        print("- 다른 모델로도 테스트해보겠습니다")
        
    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await search_tool.shutdown()


async def test_multiple_models():
    """여러 모델로 threshold 검색 테스트"""
    print("\n🔬 여러 모델로 threshold 검색 비교")
    
    test_models = [
        "all-MiniLM-L6-v2",
        "all-mpnet-base-v2", 
        "intfloat/multilingual-e5-small"
    ]
    
    for model_name in test_models:
        print(f"\n{'='*60}")
        print(f"🧪 모델: {model_name}")
        print(f"{'='*60}")
        
        search_tool = InteractiveSearchTool("data/memories.db", verbose=0)
        
        try:
            await search_tool.initialize()
            
            # 모델 전환 (경고 무시하고 진행)
            search_tool.verbose = 1  # 자동 진행
            success = await search_tool.switch_model(model_name)
            
            if success:
                print(f"\n🔍 '{model_name}'로 'threshold' 검색:")
                await search_tool.search("threshold", limit=3)
                
                print(f"\n🔍 '{model_name}'로 'threshold1' 검색:")
                await search_tool.search("threshold1", limit=3)
            else:
                print(f"❌ 모델 {model_name} 전환 실패")
                
        except Exception as e:
            print(f"❌ 모델 {model_name} 테스트 실패: {e}")
        finally:
            await search_tool.shutdown()


if __name__ == "__main__":
    asyncio.run(test_threshold_search())
    asyncio.run(test_multiple_models())