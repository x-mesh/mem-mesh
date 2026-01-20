"""
검색 품질 비교 테스트
UnifiedSearchService vs Legacy SearchService 실제 비교
"""

import asyncio
from app.core.storage.direct import DirectStorageBackend
from app.core.config import create_settings
from app.core.schemas.requests import AddParams, SearchParams


async def test_search_quality():
    """검색 품질 비교 테스트"""
    
    print("=" * 60)
    print("검색 품질 비교 테스트")
    print("=" * 60)
    
    # 테스트 데이터 준비
    test_memories = [
        {
            "content": "Python에서 비동기 프로그래밍을 구현하는 방법 - asyncio 사용",
            "category": "task",
            "tags": ["python", "async", "asyncio"]
        },
        {
            "content": "FastAPI를 사용한 REST API 개발 가이드",
            "category": "task",
            "tags": ["fastapi", "rest-api", "python"]
        },
        {
            "content": "데이터베이스 마이그레이션 작업 완료 - SQLite에서 PostgreSQL로 전환",
            "category": "task",
            "tags": ["database", "migration", "sqlite", "postgresql"]
        },
        {
            "content": "ok yes no understood",  # 노이즈 데이터 (짧은 응답들)
            "category": "task",
            "tags": []
        },
        {
            "content": "검색 품질 개선을 위한 노이즈 필터 구현",
            "category": "task",
            "tags": ["search", "quality", "filter"]
        },
        {
            "content": "한국어 검색 최적화 - 한영 번역 사전 추가",
            "category": "task",
            "tags": ["korean", "search", "optimization"]
        },
        {
            "content": "디비 마이그레이션 스크립트 작성",  # 한국어 약어
            "category": "task",
            "tags": ["database", "script"]
        },
    ]
    
    # 테스트 쿼리
    test_queries = [
        ("비동기 프로그래밍", "한국어 검색"),
        ("API 개발", "일반 검색"),
        ("디비 마이그레이션", "한국어 약어 검색"),
        ("ok", "노이즈 쿼리"),
        ("검색 품질", "한국어 복합어"),
    ]
    
    # Legacy Search 테스트
    print("\n" + "=" * 60)
    print("1. Legacy SearchService 테스트")
    print("=" * 60)
    
    legacy_settings = create_settings(
        database_path=":memory:",
        use_unified_search=False
    )
    
    from app.core import config
    config._settings = legacy_settings
    
    legacy_backend = DirectStorageBackend(db_path=":memory:")
    await legacy_backend.initialize()
    
    # 테스트 데이터 추가
    for mem in test_memories:
        await legacy_backend.add_memory(AddParams(
            content=mem["content"],
            project_id="test-project",
            category=mem["category"],
            tags=mem.get("tags", [])
        ))
    
    print(f"\n테스트 데이터: {len(test_memories)}개 메모리 추가됨")
    
    legacy_results = {}
    for query, desc in test_queries:
        search_params = SearchParams(query=query, limit=5)
        result = await legacy_backend.search_memories(search_params)
        legacy_results[query] = result
        
        print(f"\n쿼리: '{query}' ({desc})")
        print(f"결과: {len(result.results)}개")
        for i, r in enumerate(result.results[:3], 1):
            print(f"  {i}. [{r.similarity_score:.3f}] {r.content[:60]}...")
    
    await legacy_backend.shutdown()
    
    # UnifiedSearch 테스트
    print("\n" + "=" * 60)
    print("2. UnifiedSearchService 테스트")
    print("=" * 60)
    
    unified_settings = create_settings(
        database_path=":memory:",
        use_unified_search=True,
        enable_quality_features=True,
        enable_korean_optimization=True,
        enable_noise_filter=True
    )
    
    config._settings = unified_settings
    
    unified_backend = DirectStorageBackend(db_path=":memory:")
    await unified_backend.initialize()
    
    # 동일한 테스트 데이터 추가
    for mem in test_memories:
        await unified_backend.add_memory(AddParams(
            content=mem["content"],
            project_id="test-project",
            category=mem["category"],
            tags=mem.get("tags", [])
        ))
    
    print(f"\n테스트 데이터: {len(test_memories)}개 메모리 추가됨")
    
    unified_results = {}
    for query, desc in test_queries:
        search_params = SearchParams(query=query, limit=5)
        result = await unified_backend.search_memories(search_params)
        unified_results[query] = result
        
        print(f"\n쿼리: '{query}' ({desc})")
        print(f"결과: {len(result.results)}개")
        for i, r in enumerate(result.results[:3], 1):
            print(f"  {i}. [{r.similarity_score:.3f}] {r.content[:60]}...")
    
    await unified_backend.shutdown()
    
    # 비교 분석
    print("\n" + "=" * 60)
    print("3. 비교 분석")
    print("=" * 60)
    
    for query, desc in test_queries:
        legacy_count = len(legacy_results[query].results)
        unified_count = len(unified_results[query].results)
        
        print(f"\n쿼리: '{query}' ({desc})")
        print(f"  Legacy:  {legacy_count}개 결과")
        print(f"  Unified: {unified_count}개 결과")
        
        if query == "ok":
            # 노이즈 쿼리는 필터링되어야 함
            if unified_count < legacy_count:
                print(f"  ✓ 노이즈 필터 작동: {legacy_count - unified_count}개 필터링됨")
            else:
                print(f"  ✗ 노이즈 필터 미작동")
        
        if "디비" in query or "한국어" in desc:
            # 한국어 최적화 확인
            if unified_count > 0:
                print(f"  ✓ 한국어 최적화 작동")
            else:
                print(f"  ✗ 한국어 최적화 미작동")
    
    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_search_quality())
