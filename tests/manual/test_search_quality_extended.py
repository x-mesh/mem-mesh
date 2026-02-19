"""
확장된 검색 품질 테스트
실제 데이터베이스를 사용한 다양한 시나리오 테스트
"""

import asyncio
from app.core.storage.direct import DirectStorageBackend
from app.core.config import create_settings
from app.core.schemas.requests import AddParams, SearchParams


async def test_extended_search_quality():
    """확장된 검색 품질 테스트"""
    
    print("=" * 70)
    print("확장된 검색 품질 테스트")
    print("=" * 70)
    
    # 실제 데이터베이스 사용
    settings = create_settings(
        database_path="./data/memories.db",
        use_unified_search=True,
        enable_quality_features=True,
        enable_korean_optimization=True,
        enable_noise_filter=True
    )
    
    from app.core import config
    config._settings = settings
    
    backend = DirectStorageBackend(db_path="./data/memories.db")
    await backend.initialize()
    
    # 테스트 시나리오
    test_scenarios = [
        {
            "name": "한국어 기술 용어 검색",
            "queries": [
                "임베딩 모델",
                "벡터 검색",
                "데이터베이스 마이그레이션",
                "비동기 프로그래밍",
            ]
        },
        {
            "name": "영어 기술 용어 검색",
            "queries": [
                "embedding model",
                "vector search",
                "database migration",
                "async programming",
            ]
        },
        {
            "name": "한영 혼합 검색",
            "queries": [
                "FastAPI 서버 구현",
                "SQLite vector 검색",
                "MCP 프로토콜 통합",
                "Python async 최적화",
            ]
        },
        {
            "name": "약어 및 축약어 검색",
            "queries": [
                "디비",
                "API",
                "MCP",
                "UI",
            ]
        },
        {
            "name": "복합 쿼리 검색",
            "queries": [
                "검색 품질 개선 방법",
                "한국어 검색 최적화 전략",
                "노이즈 필터링 알고리즘",
                "벡터 임베딩 성능 향상",
            ]
        },
        {
            "name": "프로젝트 필터링 검색",
            "queries": [
                ("검색", "mem-mesh"),
                ("테스트", "mem-mesh"),
                ("구현", "mem-mesh"),
            ]
        },
    ]
    
    total_tests = 0
    successful_tests = 0
    
    for scenario in test_scenarios:
        print(f"\n{'=' * 70}")
        print(f"시나리오: {scenario['name']}")
        print(f"{'=' * 70}")
        
        for query_data in scenario["queries"]:
            total_tests += 1
            
            # 프로젝트 필터링 쿼리 처리
            if isinstance(query_data, tuple):
                query, project_id = query_data
                search_params = SearchParams(
                    query=query,
                    project_id=project_id,
                    limit=5
                )
            else:
                query = query_data
                search_params = SearchParams(query=query, limit=5)
            
            try:
                result = await backend.search_memories(search_params)
                
                print(f"\n쿼리: '{query}'")
                print(f"결과: {len(result.results)}개")
                
                if len(result.results) > 0:
                    successful_tests += 1
                    print("✓ 검색 성공")
                    
                    # 상위 3개 결과 표시
                    for i, r in enumerate(result.results[:3], 1):
                        score = r.similarity_score
                        content_preview = r.content[:80].replace('\n', ' ')
                        print(f"  {i}. [{score:.3f}] {content_preview}...")
                        
                        # 프로젝트 정보
                        if r.project_id:
                            print(f"     Project: {r.project_id}")
                else:
                    print("✗ 결과 없음")
                    
            except Exception as e:
                print(f"✗ 오류 발생: {e}")
    
    await backend.shutdown()
    
    # 결과 요약
    print(f"\n{'=' * 70}")
    print("테스트 결과 요약")
    print(f"{'=' * 70}")
    print(f"총 테스트: {total_tests}개")
    print(f"성공: {successful_tests}개 ({successful_tests/total_tests*100:.1f}%)")
    print(f"실패: {total_tests - successful_tests}개")
    
    # 성능 평가
    if successful_tests / total_tests >= 0.8:
        print("\n✓ 검색 품질: 우수 (80% 이상)")
    elif successful_tests / total_tests >= 0.6:
        print("\n⚠ 검색 품질: 양호 (60-80%)")
    else:
        print("\n✗ 검색 품질: 개선 필요 (60% 미만)")


async def test_search_modes():
    """다양한 검색 모드 테스트"""
    
    print("\n" + "=" * 70)
    print("검색 모드 비교 테스트")
    print("=" * 70)
    
    settings = create_settings(
        database_path="./data/memories.db",
        use_unified_search=True
    )
    
    from app.core import config
    config._settings = settings
    
    backend = DirectStorageBackend(db_path="./data/memories.db")
    await backend.initialize()
    
    test_query = "검색 품질 개선"
    
    # UnifiedSearchService는 search_mode를 지원하지만
    # DirectStorageBackend의 search_memories는 SearchParams만 받음
    # 따라서 직접 unified_search_service를 호출
    
    if backend.unified_search_service:
        modes = ["smart", "hybrid", "semantic", "exact", "fuzzy"]
        
        for mode in modes:
            print(f"\n검색 모드: {mode}")
            try:
                result = await backend.unified_search_service.search(
                    query=test_query,
                    limit=5,
                    search_mode=mode
                )
                
                print(f"결과: {len(result.results)}개")
                for i, r in enumerate(result.results[:3], 1):
                    print(f"  {i}. [{r.similarity_score:.3f}] {r.content[:60]}...")
                    
            except Exception as e:
                print(f"✗ 오류: {e}")
    else:
        print("UnifiedSearchService가 활성화되지 않았습니다.")
    
    await backend.shutdown()


async def test_recency_weight():
    """최신성 가중치 테스트"""
    
    print("\n" + "=" * 70)
    print("최신성 가중치 테스트")
    print("=" * 70)
    
    settings = create_settings(
        database_path="./data/memories.db",
        use_unified_search=True
    )
    
    from app.core import config
    config._settings = settings
    
    backend = DirectStorageBackend(db_path="./data/memories.db")
    await backend.initialize()
    
    test_query = "검색"
    weights = [0.0, 0.3, 0.5, 0.7, 1.0]
    
    for weight in weights:
        print(f"\n최신성 가중치: {weight}")
        
        search_params = SearchParams(
            query=test_query,
            limit=5,
            recency_weight=weight
        )
        
        result = await backend.search_memories(search_params)
        
        print(f"결과: {len(result.results)}개")
        for i, r in enumerate(result.results[:3], 1):
            # 날짜 표시
            created = r.created_at[:10] if r.created_at else "N/A"
            print(f"  {i}. [{r.similarity_score:.3f}] {created} - {r.content[:50]}...")
    
    await backend.shutdown()


async def test_category_filtering():
    """카테고리 필터링 테스트"""
    
    print("\n" + "=" * 70)
    print("카테고리 필터링 테스트")
    print("=" * 70)
    
    settings = create_settings(
        database_path="./data/memories.db",
        use_unified_search=True
    )
    
    from app.core import config
    config._settings = settings
    
    backend = DirectStorageBackend(db_path="./data/memories.db")
    await backend.initialize()
    
    test_query = "검색"
    categories = ["task", "bug", "idea", "decision", "code_snippet"]
    
    for category in categories:
        print(f"\n카테고리: {category}")
        
        search_params = SearchParams(
            query=test_query,
            category=category,
            limit=5
        )
        
        result = await backend.search_memories(search_params)
        
        print(f"결과: {len(result.results)}개")
        for i, r in enumerate(result.results[:3], 1):
            print(f"  {i}. [{r.similarity_score:.3f}] [{r.category}] {r.content[:50]}...")
    
    await backend.shutdown()


async def main():
    """모든 테스트 실행"""
    
    print("\n" + "=" * 70)
    print("mem-mesh 검색 품질 확장 테스트 시작")
    print("=" * 70)
    
    # 1. 기본 검색 품질 테스트
    await test_extended_search_quality()
    
    # 2. 검색 모드 비교
    await test_search_modes()
    
    # 3. 최신성 가중치 테스트
    await test_recency_weight()
    
    # 4. 카테고리 필터링 테스트
    await test_category_filtering()
    
    print("\n" + "=" * 70)
    print("모든 테스트 완료")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
