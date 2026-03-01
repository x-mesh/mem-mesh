"""
실제 데이터 기반 상세 검색 품질 테스트
Detailed real data-driven search quality test

실제 데이터베이스에서 검색어를 추출하고, 검색 결과의 품질을 상세히 분석합니다.
"""

import asyncio
import time

from app.core.config import create_settings
from app.core.schemas.requests import SearchParams
from app.core.storage.direct import DirectStorageBackend


async def test_search_quality_metrics():
    """검색 품질 메트릭 상세 분석"""

    print("=" * 70)
    print("실제 데이터 기반 검색 품질 상세 분석")
    print("=" * 70)

    settings = create_settings(
        database_path="./data/memories.db",
        use_unified_search=True,
        enable_quality_features=True,
        enable_korean_optimization=True,
        enable_noise_filter=True,
    )

    from app.core import config

    config._settings = settings

    backend = DirectStorageBackend(db_path="./data/memories.db")
    await backend.initialize()

    # 실제 사용 패턴 기반 검색 쿼리
    real_world_queries = [
        # 1. 프로젝트 관련 검색
        {"query": "mem-mesh", "description": "프로젝트명 검색"},
        {"query": "kiro", "description": "IDE 프로젝트 검색"},
        {"query": "beads", "description": "Beads 프로젝트 검색"},
        # 2. 기술 스택 검색
        {"query": "FastAPI", "description": "FastAPI 관련 검색"},
        {"query": "SQLite", "description": "SQLite 관련 검색"},
        {"query": "MCP", "description": "MCP 프로토콜 검색"},
        {"query": "embedding", "description": "임베딩 관련 검색"},
        {"query": "vector search", "description": "벡터 검색 관련"},
        # 3. 기능 관련 검색
        {"query": "검색 품질", "description": "검색 품질 개선"},
        {"query": "캐싱", "description": "캐싱 관련"},
        {"query": "최적화", "description": "최적화 작업"},
        {"query": "테스트", "description": "테스트 관련"},
        {"query": "버그", "description": "버그 관련"},
        # 4. 한국어 검색
        {"query": "데이터베이스", "description": "한국어 기술 용어"},
        {"query": "임베딩 모델", "description": "한국어 복합어"},
        {"query": "검색 서비스", "description": "한국어 서비스명"},
        # 5. 한영 혼합 검색
        {"query": "search 품질", "description": "한영 혼합 1"},
        {"query": "API 개발", "description": "한영 혼합 2"},
        {"query": "vector 검색", "description": "한영 혼합 3"},
        # 6. 복합 쿼리
        {"query": "UnifiedSearchService 구현", "description": "복합 쿼리 1"},
        {"query": "노이즈 필터 완성", "description": "복합 쿼리 2"},
        {"query": "검색 품질 테스트", "description": "복합 쿼리 3"},
        # 7. 약어 검색
        {"query": "DB", "description": "약어 1"},
        {"query": "API", "description": "약어 2"},
        {"query": "UI", "description": "약어 3"},
        # 8. 긴 쿼리
        {
            "query": "검색 품질을 개선하기 위한 UnifiedSearchService 구현",
            "description": "긴 쿼리 1",
        },
        {"query": "실제 데이터베이스를 사용한 검색 테스트", "description": "긴 쿼리 2"},
    ]

    metrics = {
        "total_queries": len(real_world_queries),
        "queries_with_results": 0,
        "avg_results_count": 0,
        "avg_top_score": 0,
        "avg_search_time": 0,
        "high_quality_results": 0,  # score >= 0.7
        "medium_quality_results": 0,  # 0.5 <= score < 0.7
        "low_quality_results": 0,  # score < 0.5
        "detailed_results": [],
    }

    total_results = 0
    total_top_scores = 0
    total_time = 0

    print(f"\n총 {len(real_world_queries)}개 실제 쿼리 테스트 중...\n")

    for i, test_case in enumerate(real_world_queries, 1):
        query = test_case["query"]
        description = test_case["description"]

        try:
            start_time = time.perf_counter()

            search_params = SearchParams(query=query, limit=10)
            result = await backend.search_memories(search_params)

            search_time = time.perf_counter() - start_time
            total_time += search_time

            result_count = len(result.results)
            total_results += result_count

            if result_count > 0:
                metrics["queries_with_results"] += 1

                # 상위 결과 점수 분석
                top_score = result.results[0].similarity_score if result.results else 0
                total_top_scores += top_score

                # 품질 분류
                if top_score >= 0.7:
                    metrics["high_quality_results"] += 1
                    quality = "높음"
                elif top_score >= 0.5:
                    metrics["medium_quality_results"] += 1
                    quality = "중간"
                else:
                    metrics["low_quality_results"] += 1
                    quality = "낮음"

                # 상세 결과 저장
                metrics["detailed_results"].append(
                    {
                        "query": query,
                        "description": description,
                        "result_count": result_count,
                        "top_score": top_score,
                        "search_time": search_time,
                        "quality": quality,
                        "top_result_preview": (
                            result.results[0].content[:100] if result.results else ""
                        ),
                    }
                )

                print(
                    f"{i:2d}. [{quality:4s}] {description:20s} | "
                    f"쿼리: '{query[:30]:30s}' | "
                    f"결과: {result_count:2d}개 | "
                    f"점수: {top_score:.3f} | "
                    f"시간: {search_time*1000:.1f}ms"
                )
            else:
                print(
                    f"{i:2d}. [없음] {description:20s} | "
                    f"쿼리: '{query[:30]:30s}' | "
                    f"결과: 0개"
                )

                metrics["detailed_results"].append(
                    {
                        "query": query,
                        "description": description,
                        "result_count": 0,
                        "top_score": 0,
                        "search_time": search_time,
                        "quality": "없음",
                        "top_result_preview": "",
                    }
                )

        except Exception as e:
            print(
                f"{i:2d}. [오류] {description:20s} | "
                f"쿼리: '{query[:30]:30s}' | "
                f"오류: {str(e)[:50]}"
            )

    await backend.shutdown()

    # 평균 계산
    if metrics["queries_with_results"] > 0:
        metrics["avg_results_count"] = total_results / metrics["queries_with_results"]
        metrics["avg_top_score"] = total_top_scores / metrics["queries_with_results"]
    metrics["avg_search_time"] = total_time / metrics["total_queries"]

    # 결과 요약
    print(f"\n{'=' * 70}")
    print("검색 품질 메트릭 요약")
    print(f"{'=' * 70}")
    print(f"총 쿼리: {metrics['total_queries']}개")
    print(
        f"결과 있는 쿼리: {metrics['queries_with_results']}개 "
        f"({metrics['queries_with_results']/metrics['total_queries']*100:.1f}%)"
    )
    print(f"평균 결과 개수: {metrics['avg_results_count']:.1f}개")
    print(f"평균 상위 점수: {metrics['avg_top_score']:.3f}")
    print(f"평균 검색 시간: {metrics['avg_search_time']*1000:.1f}ms")

    qwr = metrics["queries_with_results"] or 1  # avoid division by zero
    print("\n품질 분포:")
    print(
        f"  - 높음 (≥0.7): {metrics['high_quality_results']}개 "
        f"({metrics['high_quality_results']/qwr*100:.1f}%)"
    )
    print(
        f"  - 중간 (0.5-0.7): {metrics['medium_quality_results']}개 "
        f"({metrics['medium_quality_results']/qwr*100:.1f}%)"
    )
    print(
        f"  - 낮음 (<0.5): {metrics['low_quality_results']}개 "
        f"({metrics['low_quality_results']/qwr*100:.1f}%)"
    )

    # 상위 5개 고품질 결과
    print(f"\n{'=' * 70}")
    print("상위 5개 고품질 검색 결과")
    print(f"{'=' * 70}")
    high_quality = sorted(
        [r for r in metrics["detailed_results"] if r["result_count"] > 0],
        key=lambda x: x["top_score"],
        reverse=True,
    )[:5]

    for i, result in enumerate(high_quality, 1):
        print(f"\n{i}. {result['description']}")
        print(f"   쿼리: '{result['query']}'")
        print(
            f"   점수: {result['top_score']:.3f} | 결과: {result['result_count']}개 | "
            f"시간: {result['search_time']*1000:.1f}ms"
        )
        print(f"   미리보기: {result['top_result_preview']}...")

    # 개선이 필요한 쿼리
    print(f"\n{'=' * 70}")
    print("개선이 필요한 검색 쿼리 (점수 < 0.5 또는 결과 없음)")
    print(f"{'=' * 70}")
    low_quality = [
        r
        for r in metrics["detailed_results"]
        if r["result_count"] == 0 or r["top_score"] < 0.5
    ]

    if low_quality:
        for i, result in enumerate(low_quality[:5], 1):
            print(f"\n{i}. {result['description']}")
            print(f"   쿼리: '{result['query']}'")
            if result["result_count"] == 0:
                print("   문제: 결과 없음")
            else:
                print(f"   문제: 낮은 점수 ({result['top_score']:.3f})")
    else:
        print("\n✓ 모든 쿼리가 양호한 품질을 보입니다!")

    # 성능 평가
    print(f"\n{'=' * 70}")
    print("종합 평가")
    print(f"{'=' * 70}")

    coverage_rate = metrics["queries_with_results"] / metrics["total_queries"]
    quality_rate = (
        metrics["high_quality_results"] / metrics["queries_with_results"]
        if metrics["queries_with_results"] > 0
        else 0
    )

    print(f"검색 커버리지: {coverage_rate*100:.1f}% ", end="")
    if coverage_rate >= 0.9:
        print("(우수)")
    elif coverage_rate >= 0.7:
        print("(양호)")
    else:
        print("(개선 필요)")

    print(f"고품질 비율: {quality_rate*100:.1f}% ", end="")
    if quality_rate >= 0.7:
        print("(우수)")
    elif quality_rate >= 0.5:
        print("(양호)")
    else:
        print("(개선 필요)")

    print(f"평균 응답 시간: {metrics['avg_search_time']*1000:.1f}ms ", end="")
    if metrics["avg_search_time"] < 0.1:
        print("(우수)")
    elif metrics["avg_search_time"] < 0.2:
        print("(양호)")
    else:
        print("(개선 필요)")

    return metrics


async def main():
    """메인 함수"""

    print("\n" + "=" * 70)
    print("mem-mesh 실제 데이터 기반 상세 검색 품질 테스트")
    print("=" * 70)

    metrics = await test_search_quality_metrics()

    print("\n" + "=" * 70)
    print("테스트 완료")
    print("=" * 70)

    return metrics


if __name__ == "__main__":
    asyncio.run(main())
