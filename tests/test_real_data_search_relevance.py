"""
실제 데이터 기반 검색 관련성 테스트
Real data-driven search relevance test

점수가 아닌 실제 검색 결과의 관련성을 평가합니다.
"""

import asyncio

from app.core.config import create_settings
from app.core.schemas.requests import SearchParams
from app.core.storage.direct import DirectStorageBackend


def check_relevance(query: str, content: str) -> tuple[bool, str]:
    """
    검색 결과의 관련성을 수동으로 확인

    Returns:
        (is_relevant, reason)
    """
    query_lower = query.lower()
    content_lower = content.lower()

    # 1. 정확한 매칭
    if query_lower in content_lower:
        return True, "정확한 매칭"

    # 2. 단어 단위 매칭
    query_words = query_lower.split()
    matched_words = sum(1 for word in query_words if word in content_lower)
    match_ratio = matched_words / len(query_words) if query_words else 0

    if match_ratio >= 0.5:
        return True, f"단어 매칭 ({matched_words}/{len(query_words)})"

    # 3. 한영 번역 확인
    translations = {
        "검색": ["search", "query", "find"],
        "품질": ["quality"],
        "캐싱": ["cache", "caching"],
        "최적화": ["optimization", "optimize"],
        "테스트": ["test", "testing"],
        "데이터베이스": ["database", "db"],
        "임베딩": ["embedding"],
        "벡터": ["vector"],
    }

    for korean, english_list in translations.items():
        if korean in query_lower:
            for english in english_list:
                if english in content_lower:
                    return True, f"한영 번역 매칭 ({korean}→{english})"

    # 4. 프로젝트명 매칭
    if any(proj in query_lower for proj in ["mem-mesh", "kiro", "beads"]):
        if any(proj in content_lower for proj in ["mem-mesh", "kiro", "beads"]):
            return True, "프로젝트명 매칭"

    # 5. 기술 용어 매칭
    tech_terms = ["fastapi", "sqlite", "mcp", "api", "vector", "embedding"]
    query_has_tech = any(term in query_lower for term in tech_terms)
    content_has_tech = any(term in content_lower for term in tech_terms)

    if query_has_tech and content_has_tech:
        return True, "기술 용어 매칭"

    return False, "관련성 없음"


async def test_search_relevance():
    """검색 결과 관련성 테스트"""

    print("=" * 70)
    print("실제 데이터 기반 검색 관련성 테스트")
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

    # 테스트 쿼리
    test_queries = [
        {"query": "mem-mesh", "expected_keywords": ["mem-mesh", "memory", "search"]},
        {
            "query": "검색 품질",
            "expected_keywords": ["검색", "품질", "search", "quality"],
        },
        {"query": "FastAPI", "expected_keywords": ["fastapi", "api", "web"]},
        {"query": "임베딩", "expected_keywords": ["임베딩", "embedding", "vector"]},
        {"query": "캐싱", "expected_keywords": ["캐싱", "cache", "caching"]},
        {
            "query": "UnifiedSearchService",
            "expected_keywords": ["unified", "search", "service"],
        },
        {
            "query": "노이즈 필터",
            "expected_keywords": ["노이즈", "필터", "noise", "filter"],
        },
        {"query": "MCP", "expected_keywords": ["mcp", "protocol"]},
        {
            "query": "데이터베이스",
            "expected_keywords": ["데이터베이스", "database", "db", "sqlite"],
        },
        {
            "query": "벡터 검색",
            "expected_keywords": ["벡터", "검색", "vector", "search"],
        },
    ]

    total_queries = len(test_queries)
    total_relevant = 0
    total_results = 0

    print(f"\n총 {total_queries}개 쿼리의 관련성 테스트 중...\n")

    for i, test_case in enumerate(test_queries, 1):
        query = test_case["query"]
        expected_keywords = test_case["expected_keywords"]

        try:
            search_params = SearchParams(query=query, limit=5)
            result = await backend.search_memories(search_params)

            print(f"\n{i}. 쿼리: '{query}'")
            print(f"   결과: {len(result.results)}개")

            if len(result.results) == 0:
                print("   ✗ 결과 없음")
                continue

            # 각 결과의 관련성 확인
            relevant_count = 0
            for j, res in enumerate(result.results, 1):
                is_relevant, reason = check_relevance(query, res.content)

                if is_relevant:
                    relevant_count += 1
                    total_relevant += 1
                    status = "✓"
                else:
                    status = "✗"

                # 키워드 매칭 확인
                content_lower = res.content.lower()
                matched_keywords = [
                    kw for kw in expected_keywords if kw in content_lower
                ]

                print(
                    f"   {status} 결과 {j}: 점수={res.similarity_score:.3f}, "
                    f"관련성={reason}, "
                    f"키워드={len(matched_keywords)}/{len(expected_keywords)}"
                )

                if j <= 2:  # 상위 2개만 미리보기
                    preview = res.content[:80].replace("\n", " ")
                    print(f"      미리보기: {preview}...")

            total_results += len(result.results)
            relevance_rate = relevant_count / len(result.results) * 100

            print(
                f"   관련성 비율: {relevant_count}/{len(result.results)} ({relevance_rate:.1f}%)"
            )

        except Exception as e:
            print(f"\n{i}. 쿼리: '{query}'")
            print(f"   ✗ 오류: {str(e)[:100]}")

    await backend.shutdown()

    # 결과 요약
    print(f"\n{'=' * 70}")
    print("검색 관련성 테스트 결과")
    print(f"{'=' * 70}")
    print(f"총 쿼리: {total_queries}개")
    print(f"총 결과: {total_results}개")
    print(f"관련성 있는 결과: {total_relevant}개")

    if total_results > 0:
        relevance_rate = total_relevant / total_results * 100
        print(f"전체 관련성 비율: {relevance_rate:.1f}%")

        if relevance_rate >= 80:
            print("\n✓ 검색 관련성: 우수 (80% 이상)")
        elif relevance_rate >= 60:
            print("\n⚠ 검색 관련성: 양호 (60-80%)")
        else:
            print("\n✗ 검색 관련성: 개선 필요 (60% 미만)")

    return {
        "total_queries": total_queries,
        "total_results": total_results,
        "total_relevant": total_relevant,
        "relevance_rate": (
            total_relevant / total_results * 100 if total_results > 0 else 0
        ),
    }


async def test_specific_queries():
    """특정 쿼리의 상세 분석"""

    print(f"\n{'=' * 70}")
    print("특정 쿼리 상세 분석")
    print(f"{'=' * 70}")

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

    # 상세 분석할 쿼리
    detailed_queries = [
        "mem-mesh 검색 품질 개선",
        "UnifiedSearchService 구현",
        "노이즈 필터 완성",
    ]

    for query in detailed_queries:
        print(f"\n{'=' * 70}")
        print(f"쿼리: '{query}'")
        print(f"{'=' * 70}")

        try:
            search_params = SearchParams(query=query, limit=10)
            result = await backend.search_memories(search_params)

            print(f"결과: {len(result.results)}개\n")

            for i, res in enumerate(result.results, 1):
                is_relevant, reason = check_relevance(query, res.content)
                status = "✓" if is_relevant else "✗"

                print(
                    f"{i:2d}. {status} 점수: {res.similarity_score:.3f} | 관련성: {reason}"
                )
                print(f"    프로젝트: {res.project_id} | 카테고리: {res.category}")

                # 콘텐츠 미리보기 (첫 200자)
                preview = res.content[:200].replace("\n", " ")
                print(f"    내용: {preview}...")
                print()

        except Exception as e:
            print(f"✗ 오류: {str(e)[:100]}\n")

    await backend.shutdown()


async def main():
    """메인 함수"""

    print("\n" + "=" * 70)
    print("mem-mesh 실제 데이터 기반 검색 관련성 테스트")
    print("=" * 70)

    # 1. 관련성 테스트
    result = await test_search_relevance()

    # 2. 특정 쿼리 상세 분석
    await test_specific_queries()

    print("\n" + "=" * 70)
    print("테스트 완료")
    print("=" * 70)

    return result


if __name__ == "__main__":
    asyncio.run(main())
