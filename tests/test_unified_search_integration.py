"""
UnifiedSearchService 통합 테스트

DirectStorageBackend와 UnifiedSearchService의 통합을 검증합니다.
pytest 없이 직접 실행 가능합니다.
"""

import asyncio

from app.core.config import create_settings
from app.core.schemas.requests import AddParams, SearchParams
from app.core.storage.direct import DirectStorageBackend

if __name__ == "__main__":
    # 간단한 테스트 실행
    async def run_tests():
        print("=== UnifiedSearchService Integration Tests ===\n")

        # Test 1: Initialization
        print("Test 1: Initialization")
        settings = create_settings(database_path=":memory:", use_unified_search=True)
        from app.core import config

        config._settings = settings

        backend = DirectStorageBackend(db_path=":memory:")
        await backend.initialize()

        assert backend.unified_search_service is not None
        print("✓ UnifiedSearchService initialized\n")

        # Test 2: Basic search
        print("Test 2: Basic Search")
        add_params = AddParams(
            content="Python 비동기 프로그래밍 가이드",
            project_id="test",
            category="task",
        )
        await backend.add_memory(add_params)

        search_params = SearchParams(query="비동기", limit=5)
        result = await backend.search_memories(search_params)

        assert len(result.results) > 0
        print(f"✓ Found {len(result.results)} results\n")

        await backend.shutdown()

        print("=== All tests passed! ===")

    asyncio.run(run_tests())
