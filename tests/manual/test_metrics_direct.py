#!/usr/bin/env python
"""웹 UI 검색 메트릭 수집 직접 테스트"""

import asyncio

from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.metrics_collector import MetricsCollector
from app.core.services.search import SearchService


async def main():
    print("=== 메트릭 수집 테스트 시작 ===\n")

    # 데이터베이스 연결
    db = Database("./data/memories.db")
    await db.connect()
    print("✓ Database connected")

    # 임베딩 서비스 초기화
    embedding_service = EmbeddingService(
        model_name="sentence-transformers/all-MiniLM-L6-v2", preload=True
    )
    print("✓ Embedding service initialized")

    # MetricsCollector 초기화
    metrics_collector = MetricsCollector(database=db)
    print("✓ MetricsCollector initialized")

    # SearchService 초기화 (MetricsCollector 주입)
    search_service = SearchService(db, embedding_service, metrics_collector)
    print("✓ SearchService initialized with MetricsCollector\n")

    # 검색 수행
    print("검색 수행 중: 'test query'...")
    result = await search_service.search(query="test query", limit=5)
    print(f"✓ 검색 완료: {len(result.results)}개 결과\n")

    # 메트릭 버퍼 플러시
    print("메트릭 버퍼 플러시 중...")
    await metrics_collector.flush()
    print("✓ 메트릭 플러시 완료\n")

    # 최근 메트릭 조회
    print("최근 메트릭 조회 중...")
    recent_metrics = await db.fetchall("""
        SELECT id, timestamp, query, source, result_count, response_time_ms
        FROM search_metrics
        ORDER BY timestamp DESC
        LIMIT 3
    """)

    print(f"\n최근 검색 메트릭 ({len(recent_metrics)}개):")
    for metric in recent_metrics:
        print(
            f"  - Query: '{metric['query']}' | Source: {metric['source']} | Results: {metric['result_count']} | Time: {metric['response_time_ms']}ms"
        )

    # 정리
    await db.close()
    print("\n=== 테스트 완료 ===")


if __name__ == "__main__":
    asyncio.run(main())
