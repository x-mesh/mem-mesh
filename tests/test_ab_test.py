#!/usr/bin/env python3
"""
A/B 테스트 시스템 간단 테스트
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from scripts.ab_test_embeddings import EmbeddingABTest


async def test_ab_test():
    """A/B 테스트 시스템 기본 테스트"""
    print("🔬 A/B 테스트 시스템 테스트 시작")

    # 두 개의 작은 모델로 테스트
    ab_test = EmbeddingABTest(
        model_a="all-MiniLM-L6-v2",
        model_b="paraphrase-MiniLM-L6-v2",
        db_path="data/memories.db",
    )

    try:
        # 초기화
        print("📊 A/B 테스트 시스템 초기화 중...")
        await ab_test.initialize()

        # 단일 쿼리 비교 테스트
        print("🧪 단일 쿼리 비교 테스트")
        result = await ab_test.run_comparison("버그 수정", limit=5)

        print("✅ A/B 테스트 성공!")
        print(f"   - 쿼리: {result.query}")
        print(f"   - 모델 A 시간: {result.model_a_time:.4f}초")
        print(f"   - 모델 B 시간: {result.model_b_time:.4f}초")
        print(f"   - 모델 A 결과 수: {len(result.model_a_results)}")
        print(f"   - 모델 B 결과 수: {len(result.model_b_results)}")

    except Exception as e:
        print(f"❌ A/B 테스트 실패: {e}")
        import traceback

        traceback.print_exc()
    finally:
        await ab_test.shutdown()


if __name__ == "__main__":
    asyncio.run(test_ab_test())
