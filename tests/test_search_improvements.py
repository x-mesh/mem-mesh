"""
검색 개선 사항 테스트
Score Normalization & Search Warmup
"""

import asyncio
import time
from app.core.storage.direct import DirectStorageBackend
from app.core.config import create_settings
from app.core.schemas.requests import SearchParams
from app.core.services.score_normalizer import ScoreNormalizer


async def test_score_normalization():
    """점수 정규화 테스트"""
    
    print("=" * 70)
    print("점수 정규화 테스트")
    print("=" * 70)
    
    # 테스트 점수 (실제 데이터에서 관찰된 낮은 점수들)
    test_scores = [0.359, 0.169, 0.156, 0.119, 0.108, 0.091, 0.078, 0.065, 0.047, 0.018]
    
    normalizer = ScoreNormalizer()
    
    # 각 정규화 방법 테스트
    methods = ["sigmoid", "minmax", "zscore", "percentile"]
    
    for method in methods:
        print(f"\n{method.upper()} 정규화:")
        normalized = normalizer.normalize(test_scores, method=method)
        
        print(f"  원본 점수: {[f'{s:.3f}' for s in test_scores[:5]]}...")
        print(f"  정규화 후: {[f'{s:.3f}' for s in normalized[:5]]}...")
        print(f"  평균: {sum(normalized)/len(normalized):.3f}")
        print(f"  최소: {min(normalized):.3f}, 최대: {max(normalized):.3f}")
    
    # 자동 보정 테스트
    print("\n자동 보정 추천:")
    calibration = normalizer.auto_calibrate(test_scores)
    print(f"  추천 방법: {calibration['recommended_method']}")
    print(f"  이유: {calibration['reason']}")
    print(f"  통계: min={calibration['stats'].min_score:.3f}, "
          f"max={calibration['stats'].max_score:.3f}, "
          f"mean={calibration['stats'].mean_score:.3f}")


async def test_search_with_normalization():
    """정규화 적용 검색 테스트"""
    
    print("\n" + "=" * 70)
    print("정규화 적용 검색 테스트")
    print("=" * 70)
    
    # 정규화 활성화
    settings = create_settings(
        database_path="./data/memories.db",
        use_unified_search=True,
        enable_score_normalization=True,
        score_normalization_method="sigmoid"
    )
    
    from app.core import config
    config._settings = settings
    
    backend = DirectStorageBackend(db_path="./data/memories.db")
    await backend.initialize()
    
    # 테스트 쿼리
    test_queries = [
        "mem-mesh",
        "검색 품질",
        "UnifiedSearchService",
        "캐싱",
        "MCP"
    ]
    
    print("\n정규화 전후 점수 비교:\n")
    
    for query in test_queries:
        search_params = SearchParams(query=query, limit=5)
        result = await backend.search_memories(search_params)
        
        if result.results:
            scores = [r.similarity_score for r in result.results]
            print(f"쿼리: '{query}'")
            print(f"  점수: {[f'{s:.3f}' for s in scores]}")
            print(f"  평균: {sum(scores)/len(scores):.3f}")
        else:
            print(f"쿼리: '{query}' - 결과 없음")
    
    await backend.shutdown()


async def test_search_warmup():
    """검색 워밍업 테스트"""
    
    print("\n" + "=" * 70)
    print("검색 워밍업 테스트")
    print("=" * 70)
    
    # 워밍업 활성화
    settings = create_settings(
        database_path="./data/memories.db",
        use_unified_search=True,
        enable_search_warmup=True
    )
    
    from app.core import config
    config._settings = settings
    
    # 초기화 시간 측정
    start_time = time.perf_counter()
    
    backend = DirectStorageBackend(db_path="./data/memories.db")
    await backend.initialize()
    
    init_time = time.perf_counter() - start_time
    
    print(f"\n초기화 시간: {init_time*1000:.1f}ms")
    
    # 첫 검색 시간 측정
    test_query = "검색 품질"
    
    start_time = time.perf_counter()
    search_params = SearchParams(query=test_query, limit=5)
    result = await backend.search_memories(search_params)
    first_search_time = time.perf_counter() - start_time
    
    print(f"첫 검색 시간: {first_search_time*1000:.1f}ms")
    print(f"결과: {len(result.results)}개")
    
    # 두 번째 검색 (캐시 히트)
    start_time = time.perf_counter()
    result = await backend.search_memories(search_params)
    second_search_time = time.perf_counter() - start_time
    
    print(f"두 번째 검색 시간: {second_search_time*1000:.1f}ms (캐시 히트)")
    
    # 성능 개선 확인
    if first_search_time < 1.0:
        print("\n✓ 첫 검색 성능 우수 (< 1초)")
    elif first_search_time < 2.0:
        print("\n⚠ 첫 검색 성능 양호 (1-2초)")
    else:
        print("\n✗ 첫 검색 성능 개선 필요 (> 2초)")
    
    await backend.shutdown()


async def test_combined_improvements():
    """통합 개선 사항 테스트"""
    
    print("\n" + "=" * 70)
    print("통합 개선 사항 테스트 (정규화 + 워밍업)")
    print("=" * 70)
    
    # 모든 개선 사항 활성화
    settings = create_settings(
        database_path="./data/memories.db",
        use_unified_search=True,
        enable_quality_features=True,
        enable_korean_optimization=True,
        enable_noise_filter=True,
        enable_score_normalization=True,
        score_normalization_method="sigmoid",
        enable_search_warmup=True
    )
    
    from app.core import config
    config._settings = settings
    
    print("\n초기화 중...")
    start_time = time.perf_counter()
    
    backend = DirectStorageBackend(db_path="./data/memories.db")
    await backend.initialize()
    
    init_time = time.perf_counter() - start_time
    print(f"초기화 완료: {init_time*1000:.1f}ms")
    
    # 다양한 쿼리 테스트
    test_cases = [
        {"query": "mem-mesh", "description": "프로젝트명"},
        {"query": "검색 품질", "description": "한국어 복합어"},
        {"query": "FastAPI", "description": "기술 스택"},
        {"query": "캐싱", "description": "한국어 기술 용어"},
        {"query": "MCP", "description": "약어"},
    ]
    
    print("\n검색 품질 테스트:")
    print(f"{'쿼리':<20} {'설명':<15} {'결과':<5} {'평균점수':<10} {'시간(ms)':<10}")
    print("-" * 70)
    
    total_time = 0
    total_score = 0
    result_count = 0
    
    for test_case in test_cases:
        query = test_case["query"]
        description = test_case["description"]
        
        start_time = time.perf_counter()
        search_params = SearchParams(query=query, limit=5)
        result = await backend.search_memories(search_params)
        search_time = time.perf_counter() - start_time
        
        total_time += search_time
        
        if result.results:
            scores = [r.similarity_score for r in result.results]
            avg_score = sum(scores) / len(scores)
            total_score += avg_score
            result_count += 1
            
            print(f"{query:<20} {description:<15} {len(result.results):<5} "
                  f"{avg_score:<10.3f} {search_time*1000:<10.1f}")
        else:
            print(f"{query:<20} {description:<15} {'0':<5} {'-':<10} {search_time*1000:<10.1f}")
    
    # 종합 평가
    print("\n" + "=" * 70)
    print("종합 평가")
    print("=" * 70)
    
    avg_search_time = total_time / len(test_cases)
    avg_score = total_score / result_count if result_count > 0 else 0
    
    print(f"평균 검색 시간: {avg_search_time*1000:.1f}ms")
    print(f"평균 점수: {avg_score:.3f}")
    print(f"결과 있는 쿼리: {result_count}/{len(test_cases)}")
    
    # 개선 효과 평가
    improvements = []
    
    if avg_search_time < 0.1:
        improvements.append("✓ 검색 속도 우수 (< 100ms)")
    elif avg_search_time < 0.2:
        improvements.append("⚠ 검색 속도 양호 (100-200ms)")
    else:
        improvements.append("✗ 검색 속도 개선 필요 (> 200ms)")
    
    if avg_score > 0.5:
        improvements.append("✓ 점수 정규화 효과 우수 (> 0.5)")
    elif avg_score > 0.3:
        improvements.append("⚠ 점수 정규화 효과 양호 (0.3-0.5)")
    else:
        improvements.append("✗ 점수 정규화 효과 미흡 (< 0.3)")
    
    print("\n개선 효과:")
    for improvement in improvements:
        print(f"  {improvement}")
    
    await backend.shutdown()


async def main():
    """메인 함수"""
    
    print("\n" + "=" * 70)
    print("mem-mesh 검색 개선 사항 테스트")
    print("=" * 70)
    
    # 1. 점수 정규화 테스트
    await test_score_normalization()
    
    # 2. 정규화 적용 검색 테스트
    await test_search_with_normalization()
    
    # 3. 검색 워밍업 테스트
    await test_search_warmup()
    
    # 4. 통합 개선 사항 테스트
    await test_combined_improvements()
    
    print("\n" + "=" * 70)
    print("모든 테스트 완료")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
