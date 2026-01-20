"""모니터링 API 테스트"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.core.database.base import Database
from app.core.services.monitoring import MonitoringService
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
        CREATE TABLE search_metrics (
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
        CREATE TABLE embedding_metrics (
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
    
    await db.execute("""
        CREATE TABLE alerts (
            id TEXT PRIMARY KEY,
            timestamp DATETIME NOT NULL,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            metric_value REAL NOT NULL,
            threshold_value REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            resolved_at DATETIME
        )
    """)
    
    yield db
    
    await db.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
async def monitoring_service(temp_db):
    """MonitoringService 인스턴스 생성"""
    return MonitoringService(temp_db)


@pytest.fixture
async def collector(temp_db):
    """MetricsCollector 인스턴스 생성"""
    collector = MetricsCollector(database=temp_db, buffer_size=100)
    yield collector
    await collector.stop()


@pytest.fixture
async def sample_data(collector, temp_db):
    """샘플 데이터 생성"""
    # 검색 메트릭 추가
    for i in range(10):
        await collector.collect_search_metric(
            query=f"test query {i}",
            result_count=i + 1,
            response_time_ms=100 + i * 10,
            avg_similarity=0.7 + i * 0.02,
            top_similarity=0.8 + i * 0.02,
            project_id="test-project" if i % 2 == 0 else None,
            source="test"
        )
    
    # 결과 없음 쿼리 추가
    for i in range(3):
        await collector.collect_search_metric(
            query=f"no results query {i}",
            result_count=0,
            response_time_ms=50,
            avg_similarity=None,
            source="test"
        )
    
    # 임베딩 메트릭 추가
    for i in range(5):
        await collector.collect_embedding_metric(
            operation="generate" if i % 2 == 0 else "batch_generate",
            count=1 if i % 2 == 0 else 10,
            total_time_ms=100 + i * 20,
            cache_hit=i % 3 == 0,
            model_name="test-model"
        )
    
    await collector.flush()
    
    return {"search_count": 13, "embedding_count": 5}


@pytest.mark.asyncio
async def test_get_search_metrics(monitoring_service, sample_data):
    """검색 메트릭 조회 테스트"""
    now = datetime.utcnow()
    start_date = now - timedelta(hours=1)
    
    result = await monitoring_service.get_search_metrics(
        start_date=start_date,
        end_date=now,
        aggregation="hourly"
    )
    
    assert "period" in result
    assert "summary" in result
    assert "timeseries" in result
    
    # 요약 통계 확인
    summary = result["summary"]
    assert summary["total_searches"] == 13
    assert summary["no_results_count"] == 3
    assert summary["avg_similarity"] > 0


@pytest.mark.asyncio
async def test_get_search_metrics_with_project_filter(monitoring_service, sample_data):
    """프로젝트 필터링 테스트"""
    now = datetime.utcnow()
    start_date = now - timedelta(hours=1)
    
    result = await monitoring_service.get_search_metrics(
        start_date=start_date,
        end_date=now,
        project_id="test-project"
    )
    
    # test-project는 5개 (i % 2 == 0인 경우)
    assert result["summary"]["total_searches"] == 5


@pytest.mark.asyncio
async def test_get_query_analysis(monitoring_service, sample_data):
    """쿼리 분석 테스트"""
    result = await monitoring_service.get_query_analysis(
        limit=100,
        sort_by="frequency",
        days=7
    )
    
    assert "queries" in result
    assert "top_queries" in result
    assert "low_similarity_queries" in result
    assert "no_results_queries" in result
    assert "length_distribution" in result
    
    # 결과 없음 쿼리 확인
    assert len(result["no_results_queries"]) == 3


@pytest.mark.asyncio
async def test_get_embedding_metrics(monitoring_service, sample_data):
    """임베딩 메트릭 조회 테스트"""
    now = datetime.utcnow()
    start_date = now - timedelta(hours=1)
    
    result = await monitoring_service.get_embedding_metrics(
        start_date=start_date,
        end_date=now
    )
    
    assert "period" in result
    assert "summary" in result
    assert "by_operation" in result
    assert "timeseries" in result
    
    # 요약 통계 확인
    summary = result["summary"]
    assert summary["total_operations"] == 5
    
    # 작업 유형별 통계 확인
    assert len(result["by_operation"]) == 2  # generate, batch_generate


@pytest.mark.asyncio
async def test_get_recent_searches(monitoring_service, sample_data):
    """최근 검색 목록 조회 테스트"""
    result = await monitoring_service.get_recent_searches(limit=10)
    
    assert len(result) == 10
    
    # 최신 순으로 정렬되어 있는지 확인
    for i in range(len(result) - 1):
        assert result[i]["timestamp"] >= result[i + 1]["timestamp"]


@pytest.mark.asyncio
async def test_get_dashboard_summary(monitoring_service, sample_data):
    """대시보드 요약 테스트"""
    result = await monitoring_service.get_dashboard_summary()
    
    assert "search" in result
    assert "embedding" in result
    assert "alerts" in result
    assert "generated_at" in result
    
    # 검색 통계 확인
    assert result["search"]["last_24h"]["total"] == 13
    
    # 임베딩 통계 확인
    assert result["embedding"]["last_24h"]["total_operations"] == 5


@pytest.mark.asyncio
async def test_empty_metrics(monitoring_service):
    """빈 메트릭 조회 테스트"""
    now = datetime.utcnow()
    start_date = now - timedelta(hours=1)
    
    result = await monitoring_service.get_search_metrics(
        start_date=start_date,
        end_date=now
    )
    
    assert result["summary"]["total_searches"] == 0
    assert result["summary"]["avg_similarity"] == 0
    assert len(result["timeseries"]) == 0


@pytest.mark.asyncio
async def test_query_analysis_sort_by_similarity(monitoring_service, sample_data):
    """유사도 기준 정렬 테스트"""
    result = await monitoring_service.get_query_analysis(
        limit=10,
        sort_by="similarity",
        days=7
    )
    
    # 낮은 유사도 순으로 정렬되어야 함
    queries = result["queries"]
    for i in range(len(queries) - 1):
        if queries[i]["avg_similarity"] and queries[i + 1]["avg_similarity"]:
            assert queries[i]["avg_similarity"] <= queries[i + 1]["avg_similarity"]


@pytest.mark.asyncio
async def test_query_analysis_sort_by_time(monitoring_service, sample_data):
    """응답 시간 기준 정렬 테스트"""
    result = await monitoring_service.get_query_analysis(
        limit=10,
        sort_by="time",
        days=7
    )
    
    # 느린 응답 시간 순으로 정렬되어야 함
    queries = result["queries"]
    for i in range(len(queries) - 1):
        assert queries[i]["avg_response_time_ms"] >= queries[i + 1]["avg_response_time_ms"]


@pytest.mark.asyncio
async def test_no_results_rate_calculation(monitoring_service, sample_data):
    """결과 없음 비율 계산 테스트"""
    now = datetime.utcnow()
    start_date = now - timedelta(hours=1)
    
    result = await monitoring_service.get_search_metrics(
        start_date=start_date,
        end_date=now
    )
    
    # 13개 중 3개가 결과 없음 = 약 23.08%
    expected_rate = 3 / 13 * 100
    assert abs(result["summary"]["no_results_rate"] - expected_rate) < 0.1


@pytest.mark.asyncio
async def test_cache_hit_rate_calculation(monitoring_service, sample_data):
    """캐시 히트율 계산 테스트"""
    now = datetime.utcnow()
    start_date = now - timedelta(hours=1)
    
    result = await monitoring_service.get_embedding_metrics(
        start_date=start_date,
        end_date=now
    )
    
    # 5개 중 2개가 캐시 히트 (i % 3 == 0: 0, 3) = 40%
    expected_rate = 2 / 5 * 100
    assert abs(result["summary"]["cache_hit_rate"] - expected_rate) < 0.1
