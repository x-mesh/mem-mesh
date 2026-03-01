#!/usr/bin/env python3
"""모니터링 페이지 테스트

테스트 메트릭 데이터를 생성하여 모니터링 대시보드를 테스트합니다.
"""

import asyncio
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.config import get_settings
from app.core.database.base import Database
from app.core.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


async def generate_test_metrics():
    """테스트 메트릭 데이터 생성"""

    db = Database(settings.database_path)
    await db.connect()

    try:
        # 최근 24시간 동안의 메트릭 생성
        now = datetime.utcnow()

        logger.info("Generating test search metrics...")

        # 검색 메트릭 생성 (100개)
        queries = [
            "Python async programming",
            "FastAPI best practices",
            "SQLite vector search",
            "MCP protocol implementation",
            "embedding models comparison",
            "Korean text processing",
            "database optimization",
            "API design patterns",
            "memory management",
            "search quality improvement",
        ]

        for i in range(100):
            timestamp = now - timedelta(
                hours=random.randint(0, 23), minutes=random.randint(0, 59)
            )
            query = random.choice(queries)

            await db.execute(
                """
                INSERT INTO search_metrics (
                    id, timestamp, query, query_length, project_id, category,
                    result_count, avg_similarity_score, top_similarity_score,
                    response_time_ms, embedding_time_ms, search_time_ms,
                    source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    str(uuid4()),
                    timestamp.isoformat() + "Z",
                    query,
                    len(query),
                    "mem-mesh" if random.random() > 0.3 else None,
                    random.choice(["task", "code", "docs", "discussion"]),
                    random.randint(0, 20),
                    random.uniform(0.3, 0.95) if random.random() > 0.1 else None,
                    random.uniform(0.5, 0.98) if random.random() > 0.1 else None,
                    random.randint(50, 500),
                    random.randint(10, 100),
                    random.randint(20, 200),
                    "test_script",
                ),
            )

        logger.info("✅ Generated 100 search metrics")

        # 임베딩 메트릭 생성 (50개)
        logger.info("Generating test embedding metrics...")

        for i in range(50):
            timestamp = now - timedelta(
                hours=random.randint(0, 23), minutes=random.randint(0, 59)
            )
            count = random.randint(1, 10)
            total_time = random.randint(50, 500)

            await db.execute(
                """
                INSERT INTO embedding_metrics (
                    id, timestamp, operation, count, total_time_ms,
                    avg_time_per_embedding_ms, cache_hit, memory_usage_mb, model_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    str(uuid4()),
                    timestamp.isoformat() + "Z",
                    random.choice(["generate", "batch_generate"]),
                    count,
                    total_time,
                    total_time / count,
                    random.choice([True, False]),
                    random.uniform(100, 500),
                    "paraphrase-multilingual-MiniLM-L12-v2",
                ),
            )

        logger.info("✅ Generated 50 embedding metrics")

        # 알림 생성 (5개)
        logger.info("Generating test alerts...")

        alert_types = [
            (
                "low_similarity",
                "warning",
                "평균 유사도가 임계값 미만입니다: 45% < 50%",
                0.45,
                0.50,
            ),
            (
                "high_no_results",
                "warning",
                "결과없음 비율이 임계값 초과입니다: 25% > 20%",
                25.0,
                20.0,
            ),
            (
                "slow_response",
                "error",
                "평균 응답 시간이 임계값 초과입니다: 1200ms > 1000ms",
                1200,
                1000,
            ),
        ]

        for i, (alert_type, severity, message, metric_val, threshold_val) in enumerate(
            alert_types
        ):
            timestamp = now - timedelta(hours=random.randint(1, 12))

            await db.execute(
                """
                INSERT INTO alerts (
                    id, timestamp, alert_type, severity, message,
                    metric_value, threshold_value, status, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    str(uuid4()),
                    timestamp.isoformat() + "Z",
                    alert_type,
                    severity,
                    message,
                    metric_val,
                    threshold_val,
                    "active" if i < 2 else "resolved",
                    (now - timedelta(hours=1)).isoformat() + "Z" if i >= 2 else None,
                ),
            )

        logger.info("✅ Generated 3 alerts")

        db.connection.commit()

        logger.info("\n✅ Test data generation completed!")
        logger.info("📊 Open http://127.0.0.1:8000/#/monitoring to view the dashboard")

    except Exception as e:
        logger.error(f"❌ Failed to generate test data: {e}")
        raise
    finally:
        await db.close()


async def clear_test_metrics():
    """테스트 메트릭 데이터 삭제"""

    db = Database(settings.database_path)
    await db.connect()

    try:
        logger.info("Clearing test metrics...")

        await db.execute("DELETE FROM search_metrics WHERE source = 'test_script'")
        await db.execute(
            "DELETE FROM embedding_metrics WHERE model_name LIKE '%test%' OR timestamp > datetime('now', '-1 day')"
        )
        await db.execute(
            "DELETE FROM alerts WHERE timestamp > datetime('now', '-1 day')"
        )

        db.connection.commit()

        logger.info("✅ Test metrics cleared")

    finally:
        await db.close()


async def main():
    """메인 함수"""

    import argparse

    parser = argparse.ArgumentParser(description="모니터링 페이지 테스트 데이터 생성")
    parser.add_argument("--clear", action="store_true", help="테스트 데이터 삭제")
    args = parser.parse_args()

    if args.clear:
        await clear_test_metrics()
    else:
        await generate_test_metrics()


if __name__ == "__main__":
    asyncio.run(main())
