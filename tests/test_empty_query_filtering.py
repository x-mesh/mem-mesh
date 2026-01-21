"""빈 쿼리 필터링 테스트"""

import pytest
from app.core.services.metrics_collector import MetricsCollector
from app.core.database.base import Database


@pytest.mark.asyncio
async def test_empty_query_not_collected():
    """빈 쿼리는 메트릭 수집에서 제외되어야 함"""
    # Given
    db = Database("./data/memories.db")
    await db.connect()
    collector = MetricsCollector(database=db, buffer_size=1)
    
    # When - 빈 쿼리로 메트릭 수집 시도
    result_id = await collector.collect_search_metric(
        query="",
        result_count=0,
        response_time_ms=100,
        source="test"
    )
    
    # Then - 스킵되어야 함
    assert result_id == "skipped-empty-query"
    
    # When - 공백만 있는 쿼리로 메트릭 수집 시도
    result_id2 = await collector.collect_search_metric(
        query="   ",
        result_count=0,
        response_time_ms=100,
        source="test"
    )
    
    # Then - 스킵되어야 함
    assert result_id2 == "skipped-empty-query"
    
    # When - 정상 쿼리로 메트릭 수집
    result_id3 = await collector.collect_search_metric(
        query="test query",
        result_count=5,
        response_time_ms=100,
        source="test"
    )
    
    # Then - 정상 수집되어야 함
    assert result_id3 != "skipped-empty-query"
    assert len(result_id3) > 0
    
    await collector.stop()
    await db.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_empty_query_not_collected())
    print("✅ 빈 쿼리 필터링 테스트 통과!")
