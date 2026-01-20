"""모니터링 API 라우트

검색 성능 모니터링 대시보드를 위한 REST API 엔드포인트
"""

from datetime import datetime, timedelta
from typing import Optional, Literal

from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.services.monitoring import MonitoringService
from app.core.services.alert import AlertService
from app.core.database.base import Database
from app.web.common.dependencies import get_database

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


# Response Models
class PeriodInfo(BaseModel):
    start: str
    end: str
    aggregation: Optional[str] = None


class SearchSummary(BaseModel):
    total_searches: int
    avg_similarity: float
    max_similarity: float
    min_similarity: float
    avg_response_time_ms: float
    max_response_time_ms: int
    min_response_time_ms: int
    no_results_count: int
    no_results_rate: float
    avg_result_count: float


class TimeseriesPoint(BaseModel):
    period: str
    total_searches: int
    avg_similarity: float
    avg_response_time_ms: float
    no_results_count: int
    no_results_rate: float


class SearchMetricsResponse(BaseModel):
    period: PeriodInfo
    summary: SearchSummary
    timeseries: list[TimeseriesPoint]


class QueryInfo(BaseModel):
    query: str
    search_count: int
    avg_similarity: float
    avg_response_time_ms: float
    avg_result_count: float
    no_results_count: int


class TopQuery(BaseModel):
    query: str
    count: int


class LowSimilarityQuery(BaseModel):
    query: str
    avg_similarity: float
    count: int


class QueryAnalysisResponse(BaseModel):
    period_days: int
    queries: list[QueryInfo]
    top_queries: list[TopQuery]
    low_similarity_queries: list[LowSimilarityQuery]
    no_results_queries: list[TopQuery]
    length_distribution: dict


class EmbeddingSummary(BaseModel):
    total_operations: int
    total_embeddings: int
    avg_total_time_ms: float
    avg_time_per_embedding_ms: float
    cache_hits: int
    cache_hit_rate: float
    avg_memory_usage_mb: float


class EmbeddingByOperation(BaseModel):
    operation: str
    count: int
    total_embeddings: int
    avg_time_ms: float
    avg_time_per_embedding_ms: float


class EmbeddingTimeseriesPoint(BaseModel):
    period: str
    operations: int
    embeddings: int
    avg_time_ms: float


class EmbeddingMetricsResponse(BaseModel):
    period: PeriodInfo
    summary: EmbeddingSummary
    by_operation: list[EmbeddingByOperation]
    timeseries: list[EmbeddingTimeseriesPoint]


class RecentSearch(BaseModel):
    id: str
    timestamp: str
    query: str
    query_length: int
    project_id: Optional[str]
    result_count: int
    avg_similarity_score: Optional[float]
    response_time_ms: int
    source: str


class DashboardSummaryResponse(BaseModel):
    search: dict
    embedding: dict
    alerts: dict
    generated_at: str


# Alert Response Models
class AlertResponse(BaseModel):
    id: str
    timestamp: str
    alert_type: str
    severity: str
    message: str
    metric_value: float
    threshold_value: float


class AlertHistoryItem(BaseModel):
    id: str
    timestamp: str
    alert_type: str
    severity: str
    message: str
    metric_value: float
    threshold_value: float
    resolved_at: Optional[str]
    resolved_by: Optional[str]
    is_resolved: bool


class AlertSummaryResponse(BaseModel):
    active_count: int
    by_severity: dict
    last_24h_count: int


class ResolveAlertRequest(BaseModel):
    resolved_by: str = Field(default="user", description="해결자 식별자")


# Helper function
def get_monitoring_service(db: Database = Depends(get_database)) -> MonitoringService:
    return MonitoringService(db)


def get_alert_service(db: Database = Depends(get_database)) -> AlertService:
    return AlertService(db)


# Endpoints
@router.get("/search/metrics", response_model=SearchMetricsResponse)
async def get_search_metrics(
    start_date: datetime = Query(
        default_factory=lambda: datetime.utcnow() - timedelta(days=1),
        description="시작 날짜 (ISO 8601 형식)"
    ),
    end_date: datetime = Query(
        default_factory=datetime.utcnow,
        description="종료 날짜 (ISO 8601 형식)"
    ),
    project_id: Optional[str] = Query(None, description="프로젝트 ID"),
    aggregation: Literal["hourly", "daily"] = Query("hourly", description="집계 단위"),
    service: MonitoringService = Depends(get_monitoring_service)
):
    """
    검색 메트릭 조회
    
    시간대별 검색 품질 메트릭을 집계하여 반환합니다.
    """
    try:
        return await service.get_search_metrics(
            start_date=start_date,
            end_date=end_date,
            project_id=project_id,
            aggregation=aggregation
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search/queries", response_model=QueryAnalysisResponse)
async def get_query_analysis(
    limit: int = Query(100, ge=1, le=500, description="최대 결과 수"),
    sort_by: Literal["frequency", "similarity", "time"] = Query(
        "frequency", description="정렬 기준"
    ),
    days: int = Query(7, ge=1, le=90, description="분석 기간 (일)"),
    service: MonitoringService = Depends(get_monitoring_service)
):
    """
    쿼리 분석
    
    검색 쿼리를 분석하여 빈도, 유사도, 응답 시간 등의 통계를 반환합니다.
    """
    try:
        return await service.get_query_analysis(
            limit=limit,
            sort_by=sort_by,
            days=days
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/embedding/metrics", response_model=EmbeddingMetricsResponse)
async def get_embedding_metrics(
    start_date: datetime = Query(
        default_factory=lambda: datetime.utcnow() - timedelta(days=1),
        description="시작 날짜 (ISO 8601 형식)"
    ),
    end_date: datetime = Query(
        default_factory=datetime.utcnow,
        description="종료 날짜 (ISO 8601 형식)"
    ),
    service: MonitoringService = Depends(get_monitoring_service)
):
    """
    임베딩 메트릭 조회
    
    임베딩 생성 성능 메트릭을 집계하여 반환합니다.
    """
    try:
        return await service.get_embedding_metrics(
            start_date=start_date,
            end_date=end_date
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search/recent", response_model=list[RecentSearch])
async def get_recent_searches(
    limit: int = Query(50, ge=1, le=200, description="최대 결과 수"),
    project_id: Optional[str] = Query(None, description="프로젝트 ID"),
    service: MonitoringService = Depends(get_monitoring_service)
):
    """
    최근 검색 목록 조회
    
    최근 수행된 검색 목록을 반환합니다.
    """
    try:
        return await service.get_recent_searches(
            limit=limit,
            project_id=project_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    service: MonitoringService = Depends(get_monitoring_service)
):
    """
    대시보드 요약 정보
    
    모니터링 대시보드에 표시할 요약 정보를 반환합니다.
    """
    try:
        return await service.get_dashboard_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Alert Endpoints
@router.get("/alerts", response_model=list[AlertResponse])
async def get_active_alerts(
    service: AlertService = Depends(get_alert_service)
):
    """
    활성 알림 목록 조회
    
    해결되지 않은 활성 알림 목록을 반환합니다.
    """
    try:
        return await service.get_active_alerts()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts/history", response_model=list[AlertHistoryItem])
async def get_alert_history(
    limit: int = Query(50, ge=1, le=200, description="최대 결과 수"),
    include_resolved: bool = Query(True, description="해결된 알림 포함 여부"),
    service: AlertService = Depends(get_alert_service)
):
    """
    알림 히스토리 조회
    
    알림 히스토리를 반환합니다.
    """
    try:
        return await service.get_alert_history(
            limit=limit,
            include_resolved=include_resolved
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts/summary", response_model=AlertSummaryResponse)
async def get_alert_summary(
    service: AlertService = Depends(get_alert_service)
):
    """
    알림 요약 정보
    
    활성 알림 수, 심각도별 분포 등 요약 정보를 반환합니다.
    """
    try:
        return await service.get_alert_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    request: ResolveAlertRequest = ResolveAlertRequest(),
    service: AlertService = Depends(get_alert_service)
):
    """
    알림 해결 처리
    
    지정된 알림을 해결 상태로 변경합니다.
    """
    try:
        success = await service.resolve_alert(
            alert_id=alert_id,
            resolved_by=request.resolved_by
        )
        if not success:
            raise HTTPException(status_code=404, detail="Alert not found")
        return {"success": True, "message": "Alert resolved"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/alerts/check")
async def trigger_threshold_check(
    service: AlertService = Depends(get_alert_service)
):
    """
    임계값 체크 수동 실행
    
    임계값 체크를 수동으로 실행하고 생성된 알림을 반환합니다.
    """
    try:
        alerts = await service.check_thresholds()
        return {
            "checked": True,
            "alerts_created": len(alerts),
            "alerts": [
                {
                    "id": a.id,
                    "alert_type": a.alert_type,
                    "severity": a.severity,
                    "message": a.message
                }
                for a in alerts
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
