"""
검색 품질 엣지 케이스 테스트
Edge cases and boundary conditions for search quality
"""

import asyncio

from app.core.config import create_settings
from app.core.schemas.requests import SearchParams
from app.core.storage.direct import DirectStorageBackend


async def test_edge_cases():
    """엣지 케이스 테스트"""

    print("=" * 70)
    print("검색 품질 엣지 케이스 테스트")
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

    # 엣지 케이스 정의
    edge_cases = [
        # 1. 특수문자 포함 쿼리
        {
            "category": "특수문자",
            "queries": [
                "C++",
                "Node.js",
                ".env 설정",
                "@decorator",
                "#hashtag",
                "file.py",
                "user@email.com",
            ],
        },
        # 2. 매우 짧은 쿼리
        {
            "category": "짧은 쿼리",
            "queries": [
                "AI",
                "DB",
                "UI",
                "API",
                "MCP",
                "SQL",
            ],
        },
        # 3. 매우 긴 쿼리
        {
            "category": "긴 쿼리",
            "queries": [
                "Python에서 비동기 프로그래밍을 구현할 때 asyncio 라이브러리를 사용하여 여러 작업을 동시에 처리하는 방법",
                "FastAPI 프레임워크를 사용하여 RESTful API를 개발하고 SQLite 데이터베이스와 연동하여 CRUD 작업을 수행하는 전체 프로세스",
            ],
        },
        # 4. 숫자 포함 쿼리
        {
            "category": "숫자 포함",
            "queries": [
                "Python 3.9",
                "2024년 개발",
                "v2.0 업데이트",
                "100개 이상",
                "1차 테스트",
            ],
        },
        # 5. 오타 및 유사 단어
        {
            "category": "오타/유사어",
            "queries": [
                "serach",  # search 오타
                "databse",  # database 오타
                "pyton",  # python 오타
                "임베딩",  # 임베딩 (정상)
                "엠베딩",  # 임베딩 변형
            ],
        },
        # 6. 대소문자 혼합
        {
            "category": "대소문자",
            "queries": [
                "PYTHON",
                "Python",
                "python",
                "PyThOn",
                "fastapi",
                "FastAPI",
                "FASTAPI",
            ],
        },
        # 7. 공백 및 특수 공백
        {
            "category": "공백 처리",
            "queries": [
                "검색  품질",  # 이중 공백
                " 검색 ",  # 앞뒤 공백
                "검색\t품질",  # 탭
                "검색\n품질",  # 개행
            ],
        },
        # 8. 존재하지 않는 용어
        {
            "category": "존재하지 않는 용어",
            "queries": [
                "xyzabc123",
                "완전히존재하지않는단어",
                "nonexistent term query",
            ],
        },
        # 9. 한글 자모 분리
        {
            "category": "한글 자모",
            "queries": [
                "ㄱㅓㅁㅅㅐㄱ",  # 검색 자모 분리
                "ㅂㅔㄱㅌㅓ",  # 벡터 자모 분리
            ],
        },
        # 10. 이모지 포함
        {
            "category": "이모지",
            "queries": [
                "검색 🔍",
                "✅ 완료",
                "🚀 배포",
            ],
        },
        # 11. URL 및 경로
        {
            "category": "URL/경로",
            "queries": [
                "https://example.com",
                "/app/core/services",
                "C:\\Users\\path",
            ],
        },
        # 12. 코드 스니펫
        {
            "category": "코드",
            "queries": [
                "async def search",
                "import asyncio",
                "SELECT * FROM",
            ],
        },
    ]

    total_tests = 0
    successful_tests = 0
    failed_tests = []

    for scenario in edge_cases:
        print(f"\n{'=' * 70}")
        print(f"카테고리: {scenario['category']}")
        print(f"{'=' * 70}")

        for query in scenario["queries"]:
            total_tests += 1

            try:
                search_params = SearchParams(query=query, limit=5)
                result = await backend.search_memories(search_params)

                print(f"\n쿼리: '{query}'")
                print(f"결과: {len(result.results)}개")

                if len(result.results) > 0:
                    successful_tests += 1
                    print("✓ 검색 성공")

                    # 상위 2개 결과만 표시
                    for i, r in enumerate(result.results[:2], 1):
                        score = r.similarity_score
                        content_preview = r.content[:60].replace("\n", " ")
                        print(f"  {i}. [{score:.3f}] {content_preview}...")
                else:
                    print("○ 결과 없음 (정상)")
                    # 존재하지 않는 용어는 결과 없음이 정상
                    if scenario["category"] == "존재하지 않는 용어":
                        successful_tests += 1

            except Exception as e:
                print(f"✗ 오류 발생: {type(e).__name__}: {str(e)[:100]}")
                failed_tests.append(
                    {
                        "category": scenario["category"],
                        "query": query,
                        "error": str(e)[:200],
                    }
                )

    await backend.shutdown()

    # 결과 요약
    print(f"\n{'=' * 70}")
    print("엣지 케이스 테스트 결과 요약")
    print(f"{'=' * 70}")
    print(f"총 테스트: {total_tests}개")
    print(f"성공: {successful_tests}개 ({successful_tests/total_tests*100:.1f}%)")
    print(f"실패: {len(failed_tests)}개")

    if failed_tests:
        print("\n실패한 테스트:")
        for fail in failed_tests:
            print(f"  - [{fail['category']}] '{fail['query']}'")
            print(f"    오류: {fail['error']}")

    # 성능 평가
    success_rate = successful_tests / total_tests
    if success_rate >= 0.9:
        print("\n✓ 엣지 케이스 처리: 우수 (90% 이상)")
    elif success_rate >= 0.7:
        print("\n⚠ 엣지 케이스 처리: 양호 (70-90%)")
    else:
        print("\n✗ 엣지 케이스 처리: 개선 필요 (70% 미만)")


async def test_boundary_conditions():
    """경계 조건 테스트"""

    print("\n" + "=" * 70)
    print("경계 조건 테스트")
    print("=" * 70)

    settings = create_settings(
        database_path="./data/memories.db", use_unified_search=True
    )

    from app.core import config

    config._settings = settings

    backend = DirectStorageBackend(db_path="./data/memories.db")
    await backend.initialize()

    boundary_tests = [
        {"name": "limit=0", "params": {"query": "검색", "limit": 0}},
        {"name": "limit=1", "params": {"query": "검색", "limit": 1}},
        {"name": "limit=100", "params": {"query": "검색", "limit": 100}},
        {
            "name": "recency_weight=0.0",
            "params": {"query": "검색", "limit": 5, "recency_weight": 0.0},
        },
        {
            "name": "recency_weight=1.0",
            "params": {"query": "검색", "limit": 5, "recency_weight": 1.0},
        },
        {"name": "빈 쿼리", "params": {"query": "", "limit": 5}},
        {"name": "공백만 있는 쿼리", "params": {"query": "   ", "limit": 5}},
    ]

    for test in boundary_tests:
        print(f"\n테스트: {test['name']}")

        try:
            search_params = SearchParams(**test["params"])
            result = await backend.search_memories(search_params)

            print(f"✓ 성공 - 결과: {len(result.results)}개")

        except Exception as e:
            print(f"✗ 오류: {type(e).__name__}: {str(e)[:100]}")

    await backend.shutdown()


async def test_performance_stress():
    """성능 스트레스 테스트"""

    print("\n" + "=" * 70)
    print("성능 스트레스 테스트")
    print("=" * 70)

    settings = create_settings(
        database_path="./data/memories.db", use_unified_search=True
    )

    from app.core import config

    config._settings = settings

    backend = DirectStorageBackend(db_path="./data/memories.db")
    await backend.initialize()

    import time

    # 1. 동일 쿼리 반복 (캐싱 효과 확인)
    print("\n1. 동일 쿼리 반복 테스트 (캐싱 효과)")
    query = "검색 품질"
    times = []

    for i in range(5):
        start = time.perf_counter()
        search_params = SearchParams(query=query, limit=5)
        result = await backend.search_memories(search_params)
        elapsed = time.perf_counter() - start
        times.append(elapsed)

        print(f"  시도 {i+1}: {elapsed:.3f}초 - 결과 {len(result.results)}개")

    print(f"  평균: {sum(times)/len(times):.3f}초")
    print(f"  최소: {min(times):.3f}초")
    print(f"  최대: {max(times):.3f}초")

    if times[0] > times[-1] * 1.5:
        print("  ✓ 캐싱 효과 확인됨")

    # 2. 다양한 쿼리 연속 실행
    print("\n2. 다양한 쿼리 연속 실행")
    queries = [
        "검색",
        "임베딩",
        "벡터",
        "데이터베이스",
        "API",
        "Python",
        "FastAPI",
        "SQLite",
        "MCP",
        "테스트",
    ]

    start = time.perf_counter()
    for query in queries:
        search_params = SearchParams(query=query, limit=5)
        await backend.search_memories(search_params)
    elapsed = time.perf_counter() - start

    print(f"  {len(queries)}개 쿼리 실행: {elapsed:.3f}초")
    print(f"  평균 쿼리당: {elapsed/len(queries):.3f}초")

    await backend.shutdown()


async def main():
    """모든 엣지 케이스 테스트 실행"""

    print("\n" + "=" * 70)
    print("mem-mesh 검색 품질 엣지 케이스 테스트 시작")
    print("=" * 70)

    # 1. 엣지 케이스 테스트
    await test_edge_cases()

    # 2. 경계 조건 테스트
    await test_boundary_conditions()

    # 3. 성능 스트레스 테스트
    await test_performance_stress()

    print("\n" + "=" * 70)
    print("모든 엣지 케이스 테스트 완료")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
