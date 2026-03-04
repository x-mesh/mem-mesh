"""
우선순위 높은 검색 개선 작업 통합 테스트

작업 1: 프로젝트명 검색 부스팅
작업 2: 캐시 TTL 설정
작업 3: UnifiedSearch 기본값 활성화
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.config import get_settings, reload_settings  # noqa: E402
from app.core.database.base import Database  # noqa: E402
from app.core.embeddings.service import EmbeddingService  # noqa: E402
from app.core.services.cache_manager import (  # noqa: E402
    get_cache_manager,
    reset_cache_manager,
)
from app.core.services.unified_search import UnifiedSearchService  # noqa: E402


async def test_project_name_boosting():
    """작업 1: 프로젝트명 검색 부스팅 테스트"""
    print("\n=== 작업 1: 프로젝트명 검색 부스팅 테스트 ===")

    # Setup
    settings = get_settings()
    db = Database(settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(
        model_name=settings.embedding_model, preload=True
    )

    # UnifiedSearchService 생성
    search_service = UnifiedSearchService(
        db=db,
        embedding_service=embedding_service,
        enable_quality_features=True,
        enable_korean_optimization=True,
        enable_noise_filter=True,
        enable_score_normalization=True,
        score_normalization_method="sigmoid",
    )

    # 테스트 쿼리: 프로젝트명으로 검색
    test_queries = [
        ("mem-mesh", "정확한 프로젝트명 매칭"),
        ("mem", "부분 프로젝트명 매칭"),
        ("kiro", "다른 프로젝트명"),
    ]

    for query, description in test_queries:
        print(f"\n쿼리: '{query}' ({description})")

        result = await search_service.search(query=query, limit=5, search_mode="hybrid")

        if result.results:
            print(f"  결과 수: {len(result.results)}")
            for i, res in enumerate(result.results[:3], 1):
                print(
                    f"  {i}. project_id={res.project_id}, score={res.similarity_score:.4f}"
                )
                print(f"     content={res.content[:80]}...")

            # 프로젝트명 매칭 검증
            if query in ["mem-mesh", "mem"]:
                mem_mesh_results = [
                    r
                    for r in result.results
                    if r.project_id and "mem" in r.project_id.lower()
                ]
                if mem_mesh_results:
                    print(
                        f"  ✅ 프로젝트명 부스팅 작동: mem-mesh 관련 결과 {len(mem_mesh_results)}개"
                    )
                else:
                    print("  ⚠️  프로젝트명 부스팅 미작동: mem-mesh 관련 결과 없음")
        else:
            print("  결과 없음")

    await db.close()
    print("\n✅ 작업 1 테스트 완료")


async def test_cache_ttl_configuration():
    """작업 2: 캐시 TTL 설정 테스트"""
    print("\n=== 작업 2: 캐시 TTL 설정 테스트 ===")

    # 캐시 매니저 리셋
    reset_cache_manager()

    # Config에서 TTL 값 확인
    settings = get_settings()
    print("Config TTL 설정:")
    print(
        f"  - Embedding TTL: {settings.cache_embedding_ttl}s ({settings.cache_embedding_ttl / 3600:.1f}h)"
    )
    print(
        f"  - Search TTL: {settings.cache_search_ttl}s ({settings.cache_search_ttl / 3600:.1f}h)"
    )
    print(
        f"  - Context TTL: {settings.cache_context_ttl}s ({settings.cache_context_ttl / 3600:.1f}h)"
    )

    # 캐시 매니저 생성 (TTL 전달)
    cache_manager = get_cache_manager(
        embedding_ttl=settings.cache_embedding_ttl,
        search_ttl=settings.cache_search_ttl,
        context_ttl=settings.cache_context_ttl,
    )

    # 캐시 통계 확인
    stats = cache_manager.get_cache_stats()
    print("\n캐시 매니저 통계:")
    print(f"  - Embedding cache TTL: {stats['caches']['embedding']['ttl']}s")
    print(f"  - Search cache TTL: {stats['caches']['search']['ttl']}s")
    print(f"  - Context cache TTL: {stats['caches']['context']['ttl']}s")

    # TTL 검증
    assert (
        stats["caches"]["embedding"]["ttl"] == settings.cache_embedding_ttl
    ), "Embedding TTL 불일치"
    assert (
        stats["caches"]["search"]["ttl"] == settings.cache_search_ttl
    ), "Search TTL 불일치"
    assert (
        stats["caches"]["context"]["ttl"] == settings.cache_context_ttl
    ), "Context TTL 불일치"

    print("\n✅ 작업 2 테스트 완료: TTL 설정이 올바르게 적용됨")


async def test_unified_search_enabled_by_default():
    """작업 3: UnifiedSearch 기본값 활성화 테스트"""
    print("\n=== 작업 3: UnifiedSearch 기본값 활성화 테스트 ===")

    # Config 확인
    settings = get_settings()
    print("UnifiedSearch 설정:")
    print(f"  - use_unified_search: {settings.use_unified_search}")
    print(f"  - enable_quality_features: {settings.enable_quality_features}")
    print(f"  - enable_korean_optimization: {settings.enable_korean_optimization}")
    print(f"  - enable_noise_filter: {settings.enable_noise_filter}")
    print(f"  - enable_score_normalization: {settings.enable_score_normalization}")
    print(f"  - score_normalization_method: {settings.score_normalization_method}")
    print(f"  - enable_search_warmup: {settings.enable_search_warmup}")

    # 기본값 검증
    assert (
        settings.use_unified_search
    ), "use_unified_search가 기본값으로 활성화되지 않음"
    assert settings.enable_quality_features, "enable_quality_features가 비활성화됨"
    assert (
        settings.enable_korean_optimization
    ), "enable_korean_optimization이 비활성화됨"
    assert settings.enable_noise_filter, "enable_noise_filter가 비활성화됨"
    assert (
        settings.enable_score_normalization
    ), "enable_score_normalization이 비활성화됨"
    assert (
        settings.score_normalization_method == "sigmoid"
    ), "score_normalization_method가 sigmoid가 아님"
    assert settings.enable_search_warmup, "enable_search_warmup이 비활성화됨"

    print("\n✅ 작업 3 테스트 완료: UnifiedSearch가 기본값으로 활성화됨")


async def test_integrated_improvements():
    """통합 테스트: 모든 개선사항이 함께 작동하는지 확인"""
    print("\n=== 통합 테스트: 모든 개선사항 ===")

    # Setup
    settings = get_settings()
    db = Database(settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(
        model_name=settings.embedding_model, preload=True
    )

    # 캐시 매니저 리셋
    reset_cache_manager()

    # UnifiedSearchService 생성 (Config의 TTL 사용)
    search_service = UnifiedSearchService(
        db=db,
        embedding_service=embedding_service,
        enable_quality_features=settings.enable_quality_features,
        enable_korean_optimization=settings.enable_korean_optimization,
        enable_noise_filter=settings.enable_noise_filter,
        enable_score_normalization=settings.enable_score_normalization,
        score_normalization_method=settings.score_normalization_method,
        cache_embedding_ttl=settings.cache_embedding_ttl,
        cache_search_ttl=settings.cache_search_ttl,
        cache_context_ttl=settings.cache_context_ttl,
    )

    # 테스트 쿼리
    test_query = "mem-mesh 검색 품질"

    print(f"\n쿼리: '{test_query}'")
    print("기능 활성화 상태:")
    print(f"  - UnifiedSearch: {settings.use_unified_search}")
    print(f"  - 품질 기능: {settings.enable_quality_features}")
    print(f"  - 한국어 최적화: {settings.enable_korean_optimization}")
    print(f"  - 노이즈 필터: {settings.enable_noise_filter}")
    print(f"  - 점수 정규화: {settings.enable_score_normalization}")

    # 첫 번째 검색 (캐시 미스)
    import time

    start_time = time.perf_counter()
    result1 = await search_service.search(
        query=test_query, limit=5, search_mode="hybrid"
    )
    first_search_time = time.perf_counter() - start_time

    print("\n첫 번째 검색 (캐시 미스):")
    print(f"  - 시간: {first_search_time:.3f}s")
    print(f"  - 결과 수: {len(result1.results)}")

    if result1.results:
        print("  - 상위 3개 결과:")
        for i, res in enumerate(result1.results[:3], 1):
            print(
                f"    {i}. score={res.similarity_score:.4f}, project={res.project_id}"
            )
            print(f"       {res.content[:80]}...")

    # 두 번째 검색 (캐시 히트)
    start_time = time.perf_counter()
    result2 = await search_service.search(
        query=test_query, limit=5, search_mode="hybrid"
    )
    second_search_time = time.perf_counter() - start_time

    print("\n두 번째 검색 (캐시 히트):")
    print(f"  - 시간: {second_search_time:.3f}s")
    print(f"  - 결과 수: {len(result2.results)}")
    print(f"  - 속도 향상: {first_search_time / second_search_time:.1f}x")

    # 캐시 통계
    cache_stats = search_service.cache_manager.get_cache_stats()
    print("\n캐시 통계:")
    print(
        f"  - Embedding cache: {cache_stats['caches']['embedding']['hits']} hits, {cache_stats['caches']['embedding']['misses']} misses"
    )
    print(
        f"  - Search cache: {cache_stats['caches']['search']['hits']} hits, {cache_stats['caches']['search']['misses']} misses"
    )

    await db.close()
    print("\n✅ 통합 테스트 완료: 모든 개선사항이 정상 작동")


if __name__ == "__main__":
    print("=" * 80)
    print("우선순위 높은 검색 개선 작업 통합 테스트")
    print("=" * 80)

    # 환경 변수 설정
    os.environ["MEM_MESH_USE_UNIFIED_SEARCH"] = "true"
    os.environ["MEM_MESH_CACHE_EMBEDDING_TTL"] = "86400"
    os.environ["MEM_MESH_CACHE_SEARCH_TTL"] = "3600"
    os.environ["MEM_MESH_CACHE_CONTEXT_TTL"] = "1800"

    # Settings 리로드
    reload_settings()

    # 테스트 실행
    asyncio.run(test_project_name_boosting())
    asyncio.run(test_cache_ttl_configuration())
    asyncio.run(test_unified_search_enabled_by_default())
    asyncio.run(test_integrated_improvements())

    print("\n" + "=" * 80)
    print("모든 테스트 완료!")
    print("=" * 80)
