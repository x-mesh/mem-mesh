"""
실제 데이터 기반 검색 품질 테스트
Real data-driven search quality test

실제 데이터베이스에서 검색어를 추출하여 검색 품질을 검증합니다.
"""

import asyncio
import random
from typing import Dict, List

from app.core.config import create_settings
from app.core.schemas.requests import SearchParams
from app.core.storage.direct import DirectStorageBackend


async def extract_search_terms_from_db() -> Dict[str, List[str]]:
    """데이터베이스에서 실제 검색어 추출"""

    print("=" * 70)
    print("실제 데이터에서 검색어 추출 중...")
    print("=" * 70)

    settings = create_settings(database_path="./data/memories.db")
    from app.core import config

    config._settings = settings

    backend = DirectStorageBackend(db_path="./data/memories.db")
    await backend.initialize()

    # 모든 메모리 가져오기
    query = """
        SELECT content, category, project_id, tags
        FROM memories 
        ORDER BY created_at DESC 
        LIMIT 500
    """

    rows = await backend.db.fetchall(query, ())

    # 검색어 추출 전략
    search_terms = {
        "단일_키워드": [],
        "기술_용어": [],
        "한국어_용어": [],
        "복합_쿼리": [],
        "프로젝트명": set(),
        "카테고리": set(),
        "태그": set(),
    }

    for row in rows:
        content = row["content"]
        category = row["category"]
        project_id = row["project_id"]
        tags = row["tags"]

        # 프로젝트명 수집
        if project_id:
            search_terms["프로젝트명"].add(project_id)

        # 카테고리 수집
        if category:
            search_terms["카테고리"].add(category)

        # 태그 수집
        if tags:
            import json

            try:
                if isinstance(tags, str):
                    tag_list = (
                        json.loads(tags) if tags.startswith("[") else tags.split(",")
                    )
                else:
                    tag_list = tags
                for tag in tag_list:
                    if tag and isinstance(tag, str):
                        search_terms["태그"].add(tag.strip())
            except Exception:
                pass

        # 콘텐츠에서 키워드 추출
        words = content.split()

        # 단일 키워드 (3-15자)
        for word in words:
            clean_word = word.strip('.,!?()[]{}":;')
            if (
                3 <= len(clean_word) <= 15
                and clean_word not in search_terms["단일_키워드"]
            ):
                search_terms["단일_키워드"].append(clean_word)

        # 기술 용어 패턴 (영어 대문자 포함, 특수문자 포함)
        tech_patterns = [
            "API",
            "MCP",
            "SQLite",
            "FastAPI",
            "Python",
            "async",
            "await",
            "embedding",
            "vector",
            "search",
            "cache",
            "database",
            "query",
            "token",
            "optimization",
            "performance",
            "quality",
            "filter",
        ]
        for word in words:
            for pattern in tech_patterns:
                if (
                    pattern.lower() in word.lower()
                    and word not in search_terms["기술_용어"]
                ):
                    search_terms["기술_용어"].append(word.strip('.,!?()[]{}":;'))

        # 한국어 용어 (한글 포함)
        for word in words:
            if any("\uac00" <= c <= "\ud7a3" for c in word):
                clean_word = word.strip('.,!?()[]{}":;')
                if (
                    2 <= len(clean_word) <= 10
                    and clean_word not in search_terms["한국어_용어"]
                ):
                    search_terms["한국어_용어"].append(clean_word)

        # 복합 쿼리 (2-3 단어 조합)
        for i in range(len(words) - 1):
            phrase = f"{words[i]} {words[i+1]}"
            clean_phrase = phrase.strip('.,!?()[]{}":;')
            if (
                5 <= len(clean_phrase) <= 30
                and clean_phrase not in search_terms["복합_쿼리"]
            ):
                search_terms["복합_쿼리"].append(clean_phrase)

    await backend.shutdown()

    # 리스트로 변환 및 제한
    search_terms["프로젝트명"] = list(search_terms["프로젝트명"])[:20]
    search_terms["카테고리"] = list(search_terms["카테고리"])
    search_terms["태그"] = list(search_terms["태그"])[:30]
    search_terms["단일_키워드"] = search_terms["단일_키워드"][:50]
    search_terms["기술_용어"] = search_terms["기술_용어"][:30]
    search_terms["한국어_용어"] = search_terms["한국어_용어"][:30]
    search_terms["복합_쿼리"] = search_terms["복합_쿼리"][:30]

    # 통계 출력
    print("\n추출된 검색어 통계:")
    print(f"  - 프로젝트명: {len(search_terms['프로젝트명'])}개")
    print(f"  - 카테고리: {len(search_terms['카테고리'])}개")
    print(f"  - 태그: {len(search_terms['태그'])}개")
    print(f"  - 단일 키워드: {len(search_terms['단일_키워드'])}개")
    print(f"  - 기술 용어: {len(search_terms['기술_용어'])}개")
    print(f"  - 한국어 용어: {len(search_terms['한국어_용어'])}개")
    print(f"  - 복합 쿼리: {len(search_terms['복합_쿼리'])}개")

    return search_terms


async def test_real_data_search():
    """실제 데이터 기반 검색 테스트"""

    print("\n" + "=" * 70)
    print("실제 데이터 기반 검색 품질 테스트 시작")
    print("=" * 70)

    # 검색어 추출
    search_terms = await extract_search_terms_from_db()

    # UnifiedSearchService 초기화
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

    # 테스트 시나리오 구성
    test_scenarios = []

    # 1. 프로젝트명 검색
    for project in random.sample(
        search_terms["프로젝트명"], min(5, len(search_terms["프로젝트명"]))
    ):
        test_scenarios.append(
            {
                "category": "프로젝트명 검색",
                "query": project,
                "project_filter": None,
                "expected_min_results": 1,
            }
        )

    # 2. 카테고리별 검색
    for category in search_terms["카테고리"]:
        test_scenarios.append(
            {
                "category": "카테고리 검색",
                "query": "",
                "category_filter": category,
                "expected_min_results": 1,
            }
        )

    # 3. 태그 검색
    for tag in random.sample(search_terms["태그"], min(10, len(search_terms["태그"]))):
        test_scenarios.append(
            {"category": "태그 검색", "query": tag, "expected_min_results": 1}
        )

    # 4. 단일 키워드 검색
    for keyword in random.sample(
        search_terms["단일_키워드"], min(15, len(search_terms["단일_키워드"]))
    ):
        test_scenarios.append(
            {
                "category": "단일 키워드",
                "query": keyword,
                "expected_min_results": 0,  # 결과 없을 수도 있음
            }
        )

    # 5. 기술 용어 검색
    for term in random.sample(
        search_terms["기술_용어"], min(10, len(search_terms["기술_용어"]))
    ):
        test_scenarios.append(
            {"category": "기술 용어", "query": term, "expected_min_results": 1}
        )

    # 6. 한국어 용어 검색
    for term in random.sample(
        search_terms["한국어_용어"], min(10, len(search_terms["한국어_용어"]))
    ):
        test_scenarios.append(
            {"category": "한국어 용어", "query": term, "expected_min_results": 1}
        )

    # 7. 복합 쿼리 검색
    for query in random.sample(
        search_terms["복합_쿼리"], min(10, len(search_terms["복합_쿼리"]))
    ):
        test_scenarios.append(
            {"category": "복합 쿼리", "query": query, "expected_min_results": 0}
        )

    # 테스트 실행
    total_tests = len(test_scenarios)
    successful_tests = 0
    failed_tests = []
    results_by_category = {}

    print(f"\n총 {total_tests}개 테스트 시나리오 실행 중...\n")

    for i, scenario in enumerate(test_scenarios, 1):
        category = scenario["category"]
        query = scenario["query"]

        if category not in results_by_category:
            results_by_category[category] = {
                "total": 0,
                "success": 0,
                "with_results": 0,
            }

        results_by_category[category]["total"] += 1

        try:
            # 검색 파라미터 구성
            search_params = SearchParams(
                query=query,
                project_id=scenario.get("project_filter"),
                category=scenario.get("category_filter"),
                limit=10,
            )

            result = await backend.search_memories(search_params)

            has_results = len(result.results) > 0
            meets_expectation = len(result.results) >= scenario["expected_min_results"]

            if has_results:
                results_by_category[category]["with_results"] += 1

            if meets_expectation:
                successful_tests += 1
                results_by_category[category]["success"] += 1
            else:
                if scenario["expected_min_results"] > 0:
                    failed_tests.append(
                        {
                            "category": category,
                            "query": query,
                            "expected": scenario["expected_min_results"],
                            "actual": len(result.results),
                        }
                    )

            # 진행 상황 출력 (10개마다)
            if i % 10 == 0 or i == total_tests:
                print(f"진행: {i}/{total_tests} ({i/total_tests*100:.1f}%)")

        except Exception as e:
            print(f"✗ 오류 [{category}] '{query}': {str(e)[:100]}")
            failed_tests.append(
                {"category": category, "query": query, "error": str(e)[:200]}
            )

    await backend.shutdown()

    # 결과 요약
    print(f"\n{'=' * 70}")
    print("실제 데이터 기반 검색 테스트 결과")
    print(f"{'=' * 70}")
    print(f"총 테스트: {total_tests}개")
    print(
        f"성공: {successful_tests}개 ({successful_tests/total_tests*100:.1f}%)"
        if total_tests
        else "성공: 0개"
    )
    print(f"실패: {len(failed_tests)}개")

    # 카테고리별 결과
    print(f"\n{'=' * 70}")
    print("카테고리별 결과")
    print(f"{'=' * 70}")
    for category, stats in sorted(results_by_category.items()):
        success_rate = (
            stats["success"] / stats["total"] * 100 if stats["total"] > 0 else 0
        )
        result_rate = (
            stats["with_results"] / stats["total"] * 100 if stats["total"] > 0 else 0
        )
        print(f"\n{category}:")
        print(f"  - 총 테스트: {stats['total']}개")
        print(f"  - 성공: {stats['success']}개 ({success_rate:.1f}%)")
        print(f"  - 결과 있음: {stats['with_results']}개 ({result_rate:.1f}%)")

    # 실패한 테스트 상세
    if failed_tests:
        print(f"\n{'=' * 70}")
        print("실패한 테스트 상세 (최대 10개)")
        print(f"{'=' * 70}")
        for fail in failed_tests[:10]:
            print(f"\n[{fail['category']}] '{fail['query']}'")
            if "error" in fail:
                print(f"  오류: {fail['error']}")
            else:
                print(f"  예상: {fail['expected']}개 이상, 실제: {fail['actual']}개")

    # 성능 평가
    success_rate = successful_tests / total_tests if total_tests else 0
    if success_rate >= 0.8:
        print("\n✓ 실제 데이터 검색 품질: 우수 (80% 이상)")
    elif success_rate >= 0.6:
        print("\n⚠ 실제 데이터 검색 품질: 양호 (60-80%)")
    else:
        print("\n✗ 실제 데이터 검색 품질: 개선 필요 (60% 미만)")

    return {
        "total_tests": total_tests,
        "successful_tests": successful_tests,
        "success_rate": success_rate,
        "results_by_category": results_by_category,
        "failed_tests": failed_tests,
    }


async def main():
    """메인 함수"""

    print("\n" + "=" * 70)
    print("mem-mesh 실제 데이터 기반 검색 품질 테스트")
    print("=" * 70)

    result = await test_real_data_search()

    print("\n" + "=" * 70)
    print("테스트 완료")
    print("=" * 70)

    return result


if __name__ == "__main__":
    asyncio.run(main())
