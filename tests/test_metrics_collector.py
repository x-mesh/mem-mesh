"""MetricsCollector 서비스 단위 테스트"""

import pytest
import asyncio
from pathlib import Path
import tempfile

from app.core.database.base import Database
from app.core.services.metrics_collector import MetricsCollector


@pytest.fixture
async def temp_db():
    """임시 데이터베이스 생성"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    db = Database(db_path)
    await db.connect()
    
    # 테이블 생성
    await db.execute("""
        CREATE TABLE IF NOT EXISTS search_metrics (
            id TEXT PRIMARY KEY,
            timestamp DATETIME NOT NULL,
            query TEXT NOT NULL,
            query_length INTEGER NOT NULL,
            project_id TEXT,
            category TEXT,
            result_count INTEGER NOT NULL,
            avg_similarity_score REAL,
            top_similarity_score REAL,
            response_time_ms INTEGER NOT NULL,
            embedding_time_ms INTEGER,
            search_time_ms INTEGER,
            response_format TEXT,
            original_size_bytes INTEGER,
            compressed_size_bytes INTEGER,
            user_agent TEXT,
            source TEXT NOT NULL
        )
    """)
    
    await db.execute("""
        CREATE TABLE IF NOT EXISTS embedding_metrics (
            id TEXT PRIMARY KEY,
            timestamp DATETIME NOT NULL,
            operation TEXT NOT NULL,
            count INTEGER NOT NULL,
            total_time_ms INTEGER NOT NULL,
            avg_time_per_embedding_ms REAL NOT NULL,
            cache_hit BOOLEAN NOT NULL,
            memory_usage_mb REAL,
            model_name TEXT NOT NULL
        )
    """)
    
    yield db
    
    await db.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
async def collector(temp_db):
    """MetricsCollector 인스턴스 생성"""
    collector = MetricsCollector(
        database=temp_db,
        buffer_size=5,  # 테스트용 작은 버퍼
        flush_interval=60
    )
    yield collector
    await collector.stop()


@pytest.mark.asyncio
async def test_collect_search_metric(collector, temp_db):
    """검색 메트릭 수집 테스트"""
    # 메트릭 수집
    metric_id = await collector.collect_search_metric(
        query="test query",
        result_count=5,
        response_time_ms=150,
        avg_similarity=0.8,
        top_similarity=0.95,
        project_id="test-project",
        source="test"
    )
    
    assert metric_id is not None
    assert len(collector.search_buffer) == 1
    
    # 버퍼 플러시
    await collector.flush()
    
    # 데이터베이스 확인
    result = await temp_db.fetchone(
        "SELECT * FROM search_metrics WHERE id = ?",
        (metric_id,)
    )
    
    assert result is not None
    assert result["query"] == "test query"
    assert result["query_length"] == 10
    assert result["result_count"] == 5
    assert result["response_time_ms"] == 150
    assert result["avg_similarity_score"] == 0.8
    assert result["top_similarity_score"] == 0.95
    assert result["project_id"] == "test-project"
    assert result["source"] == "test"


@pytest.mark.asyncio
async def test_collect_embedding_metric(collector, temp_db):
    """임베딩 메트릭 수집 테스트"""
    # 메트릭 수집
    metric_id = await collector.collect_embedding_metric(
        operation="generate",
        count=1,
        total_time_ms=100,
        cache_hit=False,
        model_name="test-model"
    )
    
    assert metric_id is not None
    assert len(collector.embedding_buffer) == 1
    
    # 버퍼 플러시
    await collector.flush()
    
    # 데이터베이스 확인
    result = await temp_db.fetchone(
        "SELECT * FROM embedding_metrics WHERE id = ?",
        (metric_id,)
    )
    
    assert result is not None
    assert result["operation"] == "generate"
    assert result["count"] == 1
    assert result["total_time_ms"] == 100
    assert result["avg_time_per_embedding_ms"] == 100.0
    assert result["cache_hit"] == 0  # SQLite stores boolean as 0/1
    assert result["model_name"] == "test-model"


@pytest.mark.asyncio
async def test_auto_flush_on_buffer_full(collector, temp_db):
    """버퍼가 가득 차면 자동 플러시 테스트"""
    # buffer_size=5로 설정되어 있음
    for i in range(5):
        await collector.collect_search_metric(
            query=f"query {i}",
            result_count=i,
            response_time_ms=100,
            source="test"
        )
    
    # 버퍼가 자동으로 플러시되어야 함
    assert len(collector.search_buffer) == 0
    
    # 데이터베이스 확인
    results = await temp_db.fetchall("SELECT * FROM search_metrics")
    assert len(results) == 5


@pytest.mark.asyncio
async def test_batch_flush(collector, temp_db):
    """일괄 플러시 테스트"""
    # 여러 메트릭 수집 (버퍼 크기 미만)
    for i in range(3):
        await collector.collect_search_metric(
            query=f"query {i}",
            result_count=i,
            response_time_ms=100,
            source="test"
        )
    
    assert len(collector.search_buffer) == 3
    
    # 수동 플러시
    await collector.flush()
    
    assert len(collector.search_buffer) == 0
    
    # 데이터베이스 확인
    results = await temp_db.fetchall("SELECT * FROM search_metrics")
    assert len(results) == 3


@pytest.mark.asyncio
async def test_query_sanitization(temp_db):
    """쿼리 해시 처리 테스트"""
    collector = MetricsCollector(
        database=temp_db,
        buffer_size=10,
        hash_queries=True  # 해시 활성화
    )
    
    original_query = "sensitive query"
    metric_id = await collector.collect_search_metric(
        query=original_query,
        result_count=1,
        response_time_ms=100,
        source="test"
    )
    
    await collector.flush()
    
    # 데이터베이스 확인
    result = await temp_db.fetchone(
        "SELECT * FROM search_metrics WHERE id = ?",
        (metric_id,)
    )
    
    # 쿼리가 해시되어 저장되어야 함
    assert result["query"] != original_query
    assert len(result["query"]) == 16  # 해시의 처음 16자
    
    await collector.stop()


@pytest.mark.asyncio
async def test_buffer_stats(collector):
    """버퍼 상태 조회 테스트"""
    # 초기 상태
    stats = await collector.get_buffer_stats()
    assert stats["search_buffer_size"] == 0
    assert stats["embedding_buffer_size"] == 0
    assert stats["buffer_capacity"] == 5
    
    # 메트릭 추가
    await collector.collect_search_metric(
        query="test",
        result_count=1,
        response_time_ms=100,
        source="test"
    )
    
    await collector.collect_embedding_metric(
        operation="generate",
        count=1,
        total_time_ms=100,
        cache_hit=False,
        model_name="test"
    )
    
    # 상태 확인
    stats = await collector.get_buffer_stats()
    assert stats["search_buffer_size"] == 1
    assert stats["embedding_buffer_size"] == 1


@pytest.mark.asyncio
async def test_concurrent_collection(collector, temp_db):
    """동시 메트릭 수집 테스트"""
    # 여러 코루틴에서 동시에 메트릭 수집
    tasks = []
    for i in range(10):
        task = collector.collect_search_metric(
            query=f"concurrent query {i}",
            result_count=i,
            response_time_ms=100,
            source="test"
        )
        tasks.append(task)
    
    # 모든 태스크 완료 대기
    await asyncio.gather(*tasks)
    
    # 플러시
    await collector.flush()
    
    # 데이터베이스 확인 (모든 메트릭이 저장되어야 함)
    results = await temp_db.fetchall("SELECT * FROM search_metrics")
    assert len(results) == 10


@pytest.mark.asyncio
async def test_stop_flushes_buffer(collector, temp_db):
    """stop() 호출 시 버퍼 플러시 테스트"""
    # 메트릭 수집 (버퍼에만 저장)
    await collector.collect_search_metric(
        query="test",
        result_count=1,
        response_time_ms=100,
        source="test"
    )
    
    assert len(collector.search_buffer) == 1
    
    # stop 호출 (자동 플러시)
    await collector.stop()
    
    # 버퍼가 비워져야 함
    assert len(collector.search_buffer) == 0
    
    # 데이터베이스 확인
    results = await temp_db.fetchall("SELECT * FROM search_metrics")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_embedding_avg_time_calculation(collector, temp_db):
    """임베딩 평균 시간 계산 테스트"""
    # 배치 임베딩 메트릭
    metric_id = await collector.collect_embedding_metric(
        operation="batch_generate",
        count=10,
        total_time_ms=500,
        cache_hit=False,
        model_name="test-model"
    )
    
    await collector.flush()
    
    # 데이터베이스 확인
    result = await temp_db.fetchone(
        "SELECT * FROM embedding_metrics WHERE id = ?",
        (metric_id,)
    )
    
    # 평균 시간이 올바르게 계산되어야 함
    assert result["avg_time_per_embedding_ms"] == 50.0  # 500 / 10


@pytest.mark.asyncio
async def test_optional_fields(collector, temp_db):
    """선택적 필드 테스트"""
    # 최소 필드만으로 메트릭 수집
    metric_id = await collector.collect_search_metric(
        query="minimal query",
        result_count=0,
        response_time_ms=100,
        source="test"
    )
    
    await collector.flush()
    
    # 데이터베이스 확인
    result = await temp_db.fetchone(
        "SELECT * FROM search_metrics WHERE id = ?",
        (metric_id,)
    )
    
    assert result is not None
    assert result["query"] == "minimal query"
    assert result["avg_similarity_score"] is None
    assert result["project_id"] is None
    assert result["embedding_time_ms"] is None
