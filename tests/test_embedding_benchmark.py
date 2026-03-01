#!/usr/bin/env python3
"""
임베딩 모델 벤치마크 시스템 테스트 스크립트
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from scripts.benchmark_embedding_models import EmbeddingModelBenchmark


async def test_benchmark():
    """벤치마크 시스템 기본 테스트"""
    print("🔬 임베딩 모델 벤치마크 시스템 테스트 시작")

    benchmark = EmbeddingModelBenchmark("data/memories.db")

    try:
        # 초기화
        print("📊 벤치마크 시스템 초기화 중...")
        await benchmark.initialize()

        # 작은 모델 하나만 테스트
        test_models = ["all-MiniLM-L6-v2"]

        print(f"🧪 테스트 모델: {test_models}")
        results = await benchmark.run_benchmark(test_models)

        if results:
            print("✅ 벤치마크 테스트 성공!")
            benchmark.generate_report("test_benchmark_results.json")
        else:
            print("❌ 벤치마크 결과가 없습니다.")

    except Exception as e:
        print(f"❌ 벤치마크 테스트 실패: {e}")
        import traceback

        traceback.print_exc()
    finally:
        if benchmark.storage:
            await benchmark.storage.shutdown()


if __name__ == "__main__":
    asyncio.run(test_benchmark())
