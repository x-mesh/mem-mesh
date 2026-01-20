#!/usr/bin/env python3
"""
다국어 모델 업그레이드 후 비교
"""

import asyncio
import json
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.search import SearchService
from app.core.config import Settings


async def test_after():
    """업그레이드 후 테스트"""

    settings = Settings()
    db = Database(db_path=settings.database_path)
    await db.connect()

    embedding_service = EmbeddingService(preload=False)
    embedding_service.load_model()
    search_service = SearchService(db, embedding_service)

    print("\n" + "="*60)
    print(f"📝 AFTER: 다국어 모델 테스트")
    print(f"모델: {embedding_service.model_name}")
    print("="*60)

    # 테스트 검색어
    test_queries = [
        ("토큰", "mem-mesh-optimization"),
        ("토큰 최적화", "mem-mesh-optimization"),
        ("검색 품질", "mem-mesh-search-quality"),
        ("캐싱", "mem-mesh-optimization"),
        ("임베딩", "mem-mesh-search-quality")
    ]

    after_results = {}

    for query, expected_project in test_queries:
        print(f"\n🔍 검색어: '{query}' (기대: {expected_project})")

        response = await search_service.search(
            query=query,
            limit=5,
            search_mode='hybrid'
        )

        correct_count = 0
        for i, r in enumerate(response.results[:5]):
            is_correct = r.project_id == expected_project
            if is_correct:
                correct_count += 1

            marker = "✅" if is_correct else "❌"
            print(f"  {i+1}. {marker} [{r.category}] {r.content[:60]}...")
            print(f"     점수: {r.similarity_score:.3f}, 프로젝트: {r.project_id}")

        accuracy = (correct_count / 5) * 100 if response.results else 0
        print(f"  📊 정확도: {accuracy:.0f}% ({correct_count}/5개)")

        after_results[query] = {
            'accuracy': accuracy,
            'correct_count': correct_count
        }

    # Before 결과 로드
    with open('before_upgrade_results.json', 'r', encoding='utf-8') as f:
        before_results = json.load(f)

    # 비교 결과
    print("\n" + "="*60)
    print("📊 BEFORE vs AFTER 비교")
    print("="*60)

    print("\n┌─────────────────┬──────────┬──────────┬───────────┐")
    print("│ 검색어          │  BEFORE  │  AFTER   │   개선    │")
    print("├─────────────────┼──────────┼──────────┼───────────┤")

    total_before = 0
    total_after = 0

    for query in test_queries:
        q = query[0]
        before_acc = before_results[q]['accuracy']
        after_acc = after_results[q]['accuracy']
        improvement = after_acc - before_acc

        total_before += before_acc
        total_after += after_acc

        print(f"│ {q:15} │  {before_acc:5.0f}%  │  {after_acc:5.0f}%  │ {improvement:+6.0f}%  │")

    print("├─────────────────┼──────────┼──────────┼───────────┤")

    avg_before = total_before / len(test_queries)
    avg_after = total_after / len(test_queries)
    avg_improvement = avg_after - avg_before

    print(f"│ {'평균':15} │  {avg_before:5.1f}%  │  {avg_after:5.1f}%  │ {avg_improvement:+6.1f}%  │")
    print("└─────────────────┴──────────┴──────────┴───────────┘")

    # 개선 요약
    print("\n" + "="*60)
    print("✨ 개선 요약")
    print("="*60)

    if avg_improvement > 0:
        print(f"🎉 평균 {avg_improvement:.1f}% 개선되었습니다!")
        print(f"   영어 전용 모델 → 다국어 모델 전환 성공")
    else:
        print(f"⚠️ 개선되지 않았습니다. 추가 조치가 필요합니다.")

    # 구체적인 성과
    print("\n📈 구체적인 성과:")
    for query, expected in test_queries:
        before_correct = before_results[query]['correct_count']
        after_correct = after_results[query]['correct_count']
        if after_correct > before_correct:
            print(f"   '{query}': {before_correct}개 → {after_correct}개 (+{after_correct-before_correct})")

    # 저장
    with open('after_upgrade_results.json', 'w', encoding='utf-8') as f:
        json.dump(after_results, f, ensure_ascii=False, indent=2)

    print("\n✅ 결과 저장: after_upgrade_results.json")


if __name__ == "__main__":
    asyncio.run(test_after())