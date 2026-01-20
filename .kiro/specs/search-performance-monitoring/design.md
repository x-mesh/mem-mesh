# 검색 성능 모니터링 대시보드 - 설계 문서

## 1. 아키텍처 개요

### 1.1 시스템 구성

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (SPA)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Dashboard    │  │ Query        │  │ Alert        │     │
│  │ Page         │  │ Analysis     │  │ Panel        │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ REST API / SSE
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   Backend (FastAPI)                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Monitoring   │  │ Metrics      │  │ Alert        │     │
│  │ Routes       │  │ Collector    │  │ Service      │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   Database (SQLite)                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ search_      │  │ embedding_   │  │ alerts       │     │
│  │ metrics      │  │ metrics      │  │              │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 데이터 흐름

1. **메트릭 수집**: 검색/임베딩 작업 시 MetricsCollector가 자동으로 메트릭 수집
2. **메트릭 저장**: SQLite 데이터베이스에 비동기 저장 (성능 영향 최소화)
3. **메트릭 집계**: MonitoringService가 시간대별/프로젝트별 집계
4. **알림 생성**: AlertService가 임계값 체크 후 알림 생성
5. **대시보드 표시**: 프론트엔드가 REST API 또는 SSE로 실시간 데이터 수신

## 2. 데이터베이스 설계

### 2.1 search_metrics 테이블

```python
class SearchMetric(Base):
    __tablename__ = "search_metrics"
    
    id: str  # UUID
    timestamp: datetime
    query: str
    query_length: int
    project_id: Optional[str]
    category: Optional[str]
    
    # 검색 결과
    result_count: int
    avg_similarity_score: Optional[float]
    top_similarity_score: Optional[float]
    
    # 성능
    response_time_ms: int
    embedding_time_ms: Optional[int]
    search_time_ms: Optional[int]
    
    # 압축
    response_format: Optional[str]  # 'full', 'compact', 'minimal'
    original_size_bytes: Optional[int]
    compressed_size_bytes: Optional[int]
    
    # 메타데이터
    user_agent: Optional[str]
    source: str  # 'mcp_stdio', 'mcp_pure', 'web_api'
```

### 2.2 embedding_metrics 테이블

```python
class EmbeddingMetric(Base):
    __tablename__ = "embedding_metrics"
    
    id: str  # UUID
    timestamp: datetime
    operation: str  # 'generate', 'batch_generate'
    
    # 성능
    count: int  # 생성된 임베딩 수
    total_time_ms: int
    avg_time_per_embedding_ms: float
    
    # 캐시
    cache_hit: bool
    
    # 리소스
    memory_usage_mb: Optional[float]
    model_name: str
```

### 2.3 alerts 테이블

```python
class Alert(Base):
    __tablename__ = "alerts"
    
    id: str  # UUID
    timestamp: datetime
    alert_type: str  # 'low_similarity', 'high_no_results', 'slow_response', 'embedding_failure'
    severity: str  # 'warning', 'error', 'critical'
    message: str
    metric_value: float
    threshold_value: float
    status: str  # 'active', 'resolved'
    resolved_at: Optional[datetime]
```

## 3. 백엔드 설계

### 3.1 MetricsCollector 서비스

```python
class MetricsCollector:
    """메트릭 수집 및 저장"""
    
    async def collect_search_metric(
        self,
        query: str,
        result_count: int,
        avg_similarity: Optional[float],
        response_time_ms: int,
        project_id: Optional[str] = None,
        **kwargs
    ) -> str:
        """검색 메트릭 수집"""
        
    async def collect_embedding_metric(
        self,
        operation: str,
        count: int,
        total_time_ms: int,
        cache_hit: bool,
        model_name: str
    ) -> str:
        """임베딩 메트릭 수집"""
```

**통합 지점**:
- `SearchService.search()`: 검색 완료 후 메트릭 수집
- `EmbeddingService.generate_embedding()`: 임베딩 생성 후 메트릭 수집

### 3.2 MonitoringService

```python
class MonitoringService:
    """메트릭 집계 및 분석"""
    
    async def get_search_metrics(
        self,
        start_date: datetime,
        end_date: datetime,
        project_id: Optional[str] = None,
        aggregation: str = "hourly"
    ) -> Dict[str, Any]:
        """검색 메트릭 집계"""
        
    async def get_query_analysis(
        self,
        limit: int = 100,
        sort_by: str = "frequency"
    ) -> List[Dict[str, Any]]:
        """쿼리 분석"""
        
    async def get_embedding_metrics(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """임베딩 메트릭 집계"""
        
    async def get_token_usage(
        self,
        start_date: datetime,
        end_date: datetime,
        group_by: str = "operation"
    ) -> Dict[str, Any]:
        """토큰 사용량 분석"""
```

### 3.3 AlertService

```python
class AlertService:
    """알림 생성 및 관리"""
    
    # 임계값 설정
    THRESHOLDS = {
        "low_similarity": 0.5,
        "high_no_results_rate": 0.2,
        "slow_response": 1000,  # ms
    }
    
    async def check_thresholds(self) -> List[Alert]:
        """임계값 체크 및 알림 생성"""
        
    async def get_active_alerts(self) -> List[Alert]:
        """활성 알림 조회"""
        
    async def resolve_alert(self, alert_id: str) -> None:
        """알림 해결"""
```

### 3.4 API 엔드포인트

```python
# app/web/monitoring/routes.py

@router.get("/api/monitoring/search/metrics")
async def get_search_metrics(
    start_date: datetime = Query(...),
    end_date: datetime = Query(...),
    project_id: Optional[str] = None,
    aggregation: str = "hourly"
) -> Dict[str, Any]:
    """검색 메트릭 조회"""

@router.get("/api/monitoring/search/queries")
async def get_query_analysis(
    limit: int = 100,
    sort_by: str = "frequency"
) -> List[Dict[str, Any]]:
    """쿼리 분석"""

@router.get("/api/monitoring/embedding/metrics")
async def get_embedding_metrics(
    start_date: datetime = Query(...),
    end_date: datetime = Query(...)
) -> Dict[str, Any]:
    """임베딩 메트릭 조회"""

@router.get("/api/monitoring/tokens/usage")
async def get_token_usage(
    start_date: datetime = Query(...),
    end_date: datetime = Query(...),
    group_by: str = "operation"
) -> Dict[str, Any]:
    """토큰 사용량 조회"""

@router.get("/api/monitoring/alerts")
async def get_alerts(
    status: str = "active",
    limit: int = 50
) -> List[Dict[str, Any]]:
    """알림 조회"""

@router.get("/api/monitoring/stream")
async def stream_metrics(request: Request):
    """SSE를 통한 실시간 메트릭 스트리밍"""
```

## 4. 프론트엔드 설계

### 4.1 페이지 구조

```
/monitoring
├── /search-quality      # 검색 품질 메트릭
├── /query-analysis      # 쿼리 분석
├── /embedding           # 임베딩 성능
├── /tokens              # 토큰 사용량
└── /alerts              # 알림
```

### 4.2 컴포넌트 설계

#### MonitoringDashboard (static/js/pages/monitoring.js)

```javascript
class MonitoringDashboard {
    constructor() {
        this.currentTab = 'search-quality';
        this.dateRange = 'last_24h';
        this.projectFilter = null;
    }
    
    async init() {
        this.setupTabs();
        this.setupDateRangePicker();
        this.setupProjectFilter();
        this.loadMetrics();
        this.startSSE();
    }
    
    async loadMetrics() {
        // 현재 탭에 따라 적절한 메트릭 로드
    }
    
    startSSE() {
        // SSE 연결로 실시간 업데이트
    }
}
```

#### SearchQualityChart (static/js/components/search-quality-chart.js)

```javascript
class SearchQualityChart {
    constructor(containerId) {
        this.chart = null;
        this.containerId = containerId;
    }
    
    render(data) {
        // Chart.js로 시계열 차트 렌더링
        // - 평균 유사도 점수
        // - 응답 시간
        // - 결과 없음 비율
    }
    
    update(newData) {
        // 실시간 데이터 업데이트
    }
}
```

#### QueryAnalysisTable (static/js/components/query-analysis-table.js)

```javascript
class QueryAnalysisTable {
    constructor(containerId) {
        this.containerId = containerId;
        this.sortBy = 'frequency';
        this.sortOrder = 'desc';
    }
    
    render(queries) {
        // 쿼리 테이블 렌더링
        // - 쿼리 텍스트
        // - 검색 빈도
        // - 평균 유사도
        // - 평균 응답 시간
    }
    
    showQueryDetail(queryId) {
        // 쿼리 상세 정보 모달
    }
}
```

#### EmbeddingPerformanceChart (static/js/components/embedding-performance-chart.js)

```javascript
class EmbeddingPerformanceChart {
    constructor(containerId) {
        this.chart = null;
        this.containerId = containerId;
    }
    
    render(data) {
        // 임베딩 성능 차트
        // - 평균 생성 시간
        // - 배치 효율성
        // - 캐시 히트율
    }
}
```

#### TokenUsageChart (static/js/components/token-usage-chart.js)

```javascript
class TokenUsageChart {
    constructor(containerId) {
        this.lineChart = null;
        this.pieChart = null;
        this.containerId = containerId;
    }
    
    render(data) {
        // 토큰 사용량 차트
        // - 시계열 라인 차트 (일일 사용량)
        // - 파이 차트 (작업 유형별 분포)
    }
}
```

#### AlertPanel (static/js/components/alert-panel.js)

```javascript
class AlertPanel {
    constructor(containerId) {
        this.containerId = containerId;
        this.alerts = [];
    }
    
    render(alerts) {
        // 알림 패널 렌더링
        // - 심각도별 색상 구분
        // - 알림 메시지
        // - 해결 버튼
    }
    
    async resolveAlert(alertId) {
        // 알림 해결 처리
    }
}
```

### 4.3 실시간 업데이트

**SSE (Server-Sent Events) 사용**:

```javascript
// 프론트엔드
const eventSource = new EventSource('/api/monitoring/stream');

eventSource.addEventListener('search_metric', (event) => {
    const metric = JSON.parse(event.data);
    updateSearchQualityChart(metric);
});

eventSource.addEventListener('alert', (event) => {
    const alert = JSON.parse(event.data);
    showAlert(alert);
});
```

```python
# 백엔드
@router.get("/api/monitoring/stream")
async def stream_metrics(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            
            # 최신 메트릭 조회
            metrics = await monitoring_service.get_latest_metrics()
            yield f"event: search_metric\ndata: {json.dumps(metrics)}\n\n"
            
            # 새로운 알림 조회
            alerts = await alert_service.get_new_alerts()
            for alert in alerts:
                yield f"event: alert\ndata: {json.dumps(alert)}\n\n"
            
            await asyncio.sleep(5)  # 5초마다 업데이트
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

## 5. 성능 최적화

### 5.1 메트릭 수집 최적화

```python
class MetricsCollector:
    def __init__(self):
        self.buffer = []
        self.buffer_size = 100
        self.flush_interval = 60  # seconds
    
    async def collect_search_metric(self, **kwargs):
        """버퍼에 메트릭 추가"""
        self.buffer.append(kwargs)
        
        if len(self.buffer) >= self.buffer_size:
            await self.flush()
    
    async def flush(self):
        """버퍼의 메트릭을 일괄 저장"""
        if not self.buffer:
            return
        
        async with database.transaction():
            await database.bulk_insert(self.buffer)
        
        self.buffer.clear()
```

### 5.2 데이터베이스 인덱스

```sql
-- 시간 범위 쿼리 최적화
CREATE INDEX idx_search_metrics_timestamp ON search_metrics(timestamp);
CREATE INDEX idx_embedding_metrics_timestamp ON embedding_metrics(timestamp);

-- 프로젝트별 필터링 최적화
CREATE INDEX idx_search_metrics_project ON search_metrics(project_id);

-- 쿼리 분석 최적화
CREATE INDEX idx_search_metrics_query ON search_metrics(query);

-- 알림 조회 최적화
CREATE INDEX idx_alerts_status_timestamp ON alerts(status, timestamp);
```

### 5.3 데이터 정리

```python
class MetricsCleanupService:
    """오래된 메트릭 데이터 정리"""
    
    async def cleanup_old_metrics(self, days: int = 90):
        """90일 이상 된 메트릭 삭제"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        await database.execute(
            "DELETE FROM search_metrics WHERE timestamp < ?",
            (cutoff_date,)
        )
        
        await database.execute(
            "DELETE FROM embedding_metrics WHERE timestamp < ?",
            (cutoff_date,)
        )
```

## 6. 보안 고려사항

### 6.1 민감한 쿼리 처리

```python
class MetricsCollector:
    def __init__(self, hash_queries: bool = False):
        self.hash_queries = hash_queries
    
    def sanitize_query(self, query: str) -> str:
        """쿼리 내용 해시 처리 (옵션)"""
        if self.hash_queries:
            return hashlib.sha256(query.encode()).hexdigest()[:16]
        return query
```

### 6.2 접근 제어

```python
@router.get("/api/monitoring/search/metrics")
async def get_search_metrics(
    current_user: User = Depends(get_current_user)
):
    """인증된 사용자만 접근 가능"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # ...
```

## 7. 테스트 전략

### 7.1 단위 테스트

```python
# tests/test_metrics_collector.py
async def test_collect_search_metric():
    collector = MetricsCollector()
    metric_id = await collector.collect_search_metric(
        query="test query",
        result_count=5,
        avg_similarity=0.8,
        response_time_ms=150
    )
    assert metric_id is not None

# tests/test_monitoring_service.py
async def test_get_search_metrics():
    service = MonitoringService()
    metrics = await service.get_search_metrics(
        start_date=datetime.now() - timedelta(days=1),
        end_date=datetime.now()
    )
    assert "avg_similarity" in metrics
```

### 7.2 통합 테스트

```python
# tests/test_monitoring_integration.py
async def test_end_to_end_metric_collection():
    # 1. 검색 수행
    results = await search_service.search("test query")
    
    # 2. 메트릭 수집 확인
    await asyncio.sleep(1)  # 비동기 저장 대기
    
    # 3. 메트릭 조회
    metrics = await monitoring_service.get_search_metrics(
        start_date=datetime.now() - timedelta(minutes=1),
        end_date=datetime.now()
    )
    
    assert metrics["total_searches"] >= 1
```

### 7.3 프론트엔드 테스트

```javascript
// tests/test_monitoring_dashboard.js
describe('MonitoringDashboard', () => {
    it('should load search quality metrics', async () => {
        const dashboard = new MonitoringDashboard();
        await dashboard.init();
        
        expect(dashboard.currentTab).toBe('search-quality');
        expect(dashboard.chart).not.toBeNull();
    });
    
    it('should update chart on SSE event', async () => {
        const chart = new SearchQualityChart('chart-container');
        const initialData = await fetchMetrics();
        chart.render(initialData);
        
        // SSE 이벤트 시뮬레이션
        const newData = { avg_similarity: 0.85 };
        chart.update(newData);
        
        expect(chart.chart.data.datasets[0].data).toContain(0.85);
    });
});
```

## 8. 배포 및 운영

### 8.1 데이터베이스 마이그레이션

```python
# scripts/migrate_monitoring_tables.py
async def migrate():
    """모니터링 테이블 생성"""
    await database.execute("""
        CREATE TABLE IF NOT EXISTS search_metrics (
            id TEXT PRIMARY KEY,
            timestamp DATETIME NOT NULL,
            ...
        )
    """)
    
    await database.execute("""
        CREATE TABLE IF NOT EXISTS embedding_metrics (
            ...
        )
    """)
    
    await database.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            ...
        )
    """)
```

### 8.2 백그라운드 작업

```python
# app/web/lifespan.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시
    metrics_collector = MetricsCollector()
    alert_service = AlertService()
    
    # 백그라운드 작업 시작
    flush_task = asyncio.create_task(metrics_collector.auto_flush())
    alert_task = asyncio.create_task(alert_service.check_thresholds_periodically())
    
    yield
    
    # 종료 시
    flush_task.cancel()
    alert_task.cancel()
    await metrics_collector.flush()
```

## 9. 정확성 속성 (Correctness Properties)

### P1: 메트릭 수집 완전성
**속성**: 모든 검색 작업은 정확히 하나의 메트릭 레코드를 생성해야 한다.

**검증 방법**:
```python
@given(st.text(min_size=1), st.integers(min_value=0), st.floats(min_value=0, max_value=1))
async def test_search_metric_completeness(query, result_count, similarity):
    initial_count = await count_metrics()
    await search_service.search(query)
    final_count = await count_metrics()
    assert final_count == initial_count + 1
```

### P2: 메트릭 정확성
**속성**: 수집된 메트릭 값은 실제 측정 값과 일치해야 한다.

**검증 방법**:
```python
async def test_metric_accuracy():
    start_time = time.time()
    results = await search_service.search("test")
    end_time = time.time()
    
    metric = await get_latest_metric()
    assert abs(metric.response_time_ms - (end_time - start_time) * 1000) < 10
```

### P3: 알림 일관성
**속성**: 임계값을 초과하면 반드시 알림이 생성되어야 한다.

**검증 방법**:
```python
@given(st.floats(min_value=0, max_value=0.4))
async def test_alert_consistency(low_similarity):
    await create_metric_with_similarity(low_similarity)
    await alert_service.check_thresholds()
    alerts = await alert_service.get_active_alerts()
    assert any(a.alert_type == 'low_similarity' for a in alerts)
```

### P4: 데이터 정리 안전성
**속성**: 데이터 정리 후에도 최근 N일 데이터는 보존되어야 한다.

**검증 방법**:
```python
async def test_cleanup_safety():
    await create_metrics_for_days(100)
    await cleanup_service.cleanup_old_metrics(days=90)
    
    recent_metrics = await get_metrics_since(days=90)
    assert len(recent_metrics) > 0
    
    old_metrics = await get_metrics_before(days=90)
    assert len(old_metrics) == 0
```

## 10. 구현 우선순위

### Phase 1: 핵심 인프라 (1-2일)
1. 데이터베이스 테이블 생성
2. MetricsCollector 구현
3. 검색/임베딩 서비스에 메트릭 수집 통합

### Phase 2: API 및 집계 (1일)
1. MonitoringService 구현
2. REST API 엔드포인트 구현
3. 단위 테스트

### Phase 3: 프론트엔드 (2-3일)
1. 대시보드 페이지 구현
2. 차트 컴포넌트 구현
3. SSE 실시간 업데이트

### Phase 4: 알림 시스템 (1일)
1. AlertService 구현
2. 임계값 체크 로직
3. 알림 UI

### Phase 5: 최적화 및 테스트 (1일)
1. 성능 최적화
2. 통합 테스트
3. 문서화

**총 예상 기간**: 6-8일
