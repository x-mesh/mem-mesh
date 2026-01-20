#!/usr/bin/env python3
"""
다국어 모델 전환 전후 비교 테스트
"""

import asyncio
import json
from datetime import datetime
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.search import SearchService
from app.core.config import Settings


async def test_searches(label: str):
    """검색 테스트 수행"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(preload=False)
    embedding_service.load_model()
    search_service = SearchService(db, embedding_service)

    print(f"\n{'='*60}")
    print(f"{label} - 모델: {embedding_service.model_name}")
    print(f"{'='*60}")

    # 테스트할 검색어
    test_queries = [
        ("토큰", "mem-mesh-optimization"),
        ("토큰 최적화", "mem-mesh-optimization"),
        ("검색 품질", "mem-mesh-search-quality"),
        ("캐싱", "mem-mesh-optimization"),
        ("임베딩", "mem-mesh-search-quality")
    ]

    results = {}

    for query, expected_project in test_queries:
        print(f"\n🔍 검색어: '{query}' (기대: {expected_project})")

        # 검색 수행
        response = await search_service.search(
            query=query,
            limit=5,
            search_mode='hybrid'
        )

        # 결과 분석
        correct_project_count = 0
        top_results = []

        for i, r in enumerate(response.results[:5]):
            is_correct = r.project_id == expected_project
            if is_correct:
                correct_project_count += 1

            top_results.append({
                'content': r.content[:100],
                'project': r.project_id,
                'score': r.similarity_score,
                'category': r.category,
                'is_correct': is_correct
            })

            marker = "✅" if is_correct else "❌"
            print(f"  {i+1}. {marker} [{r.category}] {r.content[:60]}...")
            print(f"     점수: {r.similarity_score:.3f}, 프로젝트: {r.project_id}")

        accuracy = (correct_project_count / min(5, len(response.results))) * 100 if response.results else 0
        print(f"  📊 정확도: {accuracy:.0f}% ({correct_project_count}/5개가 올바른 프로젝트)")

        results[query] = {
            'expected': expected_project,
            'accuracy': accuracy,
            'correct_count': correct_project_count,
            'total': len(response.results),
            'top_results': top_results
        }

    return results


async def main():
    """메인 테스트"""

    # 1. 현재 모델로 테스트
    print("\n" + "="*60)
    print("📝 BEFORE: 영어 전용 모델 테스트")
    print("="*60)

    before_results = await test_searches("BEFORE")

    # 결과 저장
    with open('before_upgrade_results.json', 'w', encoding='utf-8') as f:
        json.dump(before_results, f, ensure_ascii=False, indent=2)

    print("\n" + "="*60)
    print("📊 BEFORE 요약")
    print("="*60)

    total_accuracy = 0
    for query, result in before_results.items():
        print(f"'{query}': {result['accuracy']:.0f}% 정확도")
        total_accuracy += result['accuracy']

    avg_accuracy = total_accuracy / len(before_results)
    print(f"\n평균 정확도: {avg_accuracy:.1f}%")

    print("\n✅ 현재 상태 저장 완료: before_upgrade_results.json")
    print("\n이제 upgrade_to_multilingual.py를 실행하여 다국어 모델로 전환하세요.")
    print("전환 후 다시 이 스크립트를 실행하면 AFTER 결과와 비교됩니다.")


if __name__ == "__main__":
    asyncio.run(main())