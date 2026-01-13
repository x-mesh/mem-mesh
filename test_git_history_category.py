#!/usr/bin/env python3
"""git-history 카테고리 테스트"""

import asyncio
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.config import Settings
from app.core.storage.direct import DirectStorageBackend
from app.core.schemas.requests import AddParams, SearchParams

async def test_git_history_category():
    """git-history 카테고리로 메모리 추가 및 검색 테스트"""
    
    # 설정 및 스토리지 초기화
    settings = Settings()
    storage = DirectStorageBackend(settings.database_path)
    await storage.initialize()
    
    try:
        # git-history 카테고리로 메모리 추가
        print("1. git-history 카테고리로 메모리 추가 테스트...")
        add_params = AddParams(
            content="Git commit: Added SSL verification bypass feature with MEM_MESH_IGNORE_SSL environment variable",
            project_id="mem-mesh-core",
            category="git-history",
            source="git",
            tags=["ssl", "security", "environment-variable"]
        )
        
        result = await storage.add_memory(add_params)
        print(f"✅ 메모리 추가 성공: ID={result.id}")
        
        # 추가된 메모리 검색
        print("\n2. git-history 카테고리 메모리 검색 테스트...")
        search_params = SearchParams(
            query="SSL verification",
            category="git-history",
            limit=5
        )
        
        search_result = await storage.search_memories(search_params)
        print(f"✅ 검색 성공: {len(search_result.results)}개 결과 발견")
        
        for memory in search_result.results:
            print(f"  - ID: {memory.id}")
            print(f"    Category: {memory.category}")
            print(f"    Content: {memory.content[:100]}...")
            print(f"    Score: {memory.similarity_score}")
        
        # 카테고리별 통계 확인
        print("\n3. 전체 카테고리 통계 확인...")
        from app.core.schemas.requests import StatsParams
        stats_params = StatsParams(project_id="mem-mesh-core")
        stats_result = await storage.get_stats(stats_params)
        
        print(f"✅ 통계 조회 성공:")
        print(f"  - 총 메모리: {stats_result.total_memories}")
        if hasattr(stats_result, 'by_category'):
            for category, count in stats_result.by_category.items():
                print(f"  - {category}: {count}개")
        
        print("\n🎉 모든 테스트 통과!")
        
    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await storage.shutdown()

if __name__ == "__main__":
    asyncio.run(test_git_history_category())