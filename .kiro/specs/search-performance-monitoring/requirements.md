# 검색 성능 모니터링 대시보드

## 개요

mem-mesh의 검색 품질과 성능을 실시간으로 모니터링하고 분석하기 위한 대시보드 구현.

## 비즈니스 목표

- 검색 품질 저하를 조기에 감지
- 사용자 검색 패턴 분석을 통한 개선점 도출
- 임베딩 모델 성능 추적
- 토큰 사용량 및 비용 최적화

## 사용자 스토리

### US-1: 검색 품질 메트릭 조회
**As a** 개발자  
**I want to** 검색 품질 메트릭을 실시간으로 확인  
**So that** 검색 성능 저하를 빠르게 감지하고 대응할 수 있다

**Acceptance Criteria:**
- 평균 유사도 점수 표시 (0.0-1.0)
- 검색 결과 없음 비율 표시
- 평균 응답 시간 표시 (ms)
- 시간대별 추이 그래프 (최근 24시간, 7일, 30일)
- 프로젝트별 필터링 가능

### US-2: 검색 쿼리 분석
**As a** 개발자  
**I want to** 사용자 검색 쿼리를 분석  
**So that** 자주 검색되는 주제와 개선이 필요한 쿼리를 파악할 수 있다

**Acceptance Criteria:**
- 최근 검색 쿼리 목록 (최대 100개)
- 검색 빈도 Top 10 쿼리
- 낮은 유사도 점수 쿼리 Top 10 (개선 필요)
- 검색 결과 없음 쿼리 목록
- 쿼리 길이 분포 (짧은/중간/긴 쿼리)

### US-3: 임베딩 성능 추적
**As a** 개발자  
**I want to** 임베딩 생성 성능을 추적  
**So that** 병목 지점을 파악하고 최적화할 수 있다

**Acceptance Criteria:**
- 평균 임베딩 생성 시간 (ms)
- 배치 임베딩 효율성 (단일 vs 배치)
- 임베딩 캐시 히트율
- 모델 로딩 시간
- 메모리 사용량

### US-4: 토큰 사용량 분석
**As a** 개발자  
**I want to** 토큰 사용량을 추적  
**So that** 비용을 최적화하고 예산을 관리할 수 있다

**Acceptance Criteria:**
- 일일 토큰 사용량 (검색, 추가, 컨텍스트)
- 작업 유형별 토큰 사용량 분포
- 압축 효과 (압축 전/후 비교)
- 예상 월간 비용 (토큰 단가 기준)
- 토큰 절감 추이 (최적화 효과)

### US-5: 알림 및 경고
**As a** 개발자  
**I want to** 성능 저하 시 자동 알림을 받기  
**So that** 문제를 빠르게 인지하고 대응할 수 있다

**Acceptance Criteria:**
- 평균 유사도 점수 < 0.5 시 경고
- 검색 결과 없음 비율 > 20% 시 경고
- 평균 응답 시간 > 1000ms 시 경고
- 임베딩 생성 실패 시 즉시 알림
- 알림 히스토리 조회

### US-6: 프로젝트별 상세 분석
**As a** 개발자  
**I want to** 특정 프로젝트의 검색 패턴을 상세히 분석  
**So that** 프로젝트별 검색 품질을 개선하고 사용 패턴을 이해할 수 있다

**Acceptance Criteria:**
- 프로젝트별 검색 활동 요약 (총 검색, 평균 결과, 평균 점수, 응답시간)
- 검색 활동 추이 차트 (시간대별)
- 품질 분포 차트 (유사도 점수 분포)
- 응답 시간 분포 차트
- 인기 검색어 Top 20
- Zero-result 쿼리 목록
- 낮은 점수 쿼리 목록 (< 0.5)
- 느린 쿼리 목록 (> 1000ms)
- 시간대별/요일별 검색 패턴 분석
- 프로젝트 간 비교 분석 (최대 3개 프로젝트)
- 프로젝트별 알림 임계값 설정
- 데이터 내보내기 (CSV/JSON)

## 기술 요구사항

### 데이터 수집

**SearchMetrics 테이블**:
```sql
CREATE TABLE search_metrics (
    id TEXT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    query TEXT NOT NULL,
    query_length INTEGER NOT NULL,
    project_id TEXT,
    category TEXT,
    
    -- 검색 결과
    result_count INTEGER NOT NULL,
    avg_similarity_score REAL,
    top_similarity_score REAL,
    
    -- 성능
    response_time_ms INTEGER NOT NULL,
    embedding_time_ms INTEGER,
    search_time_ms INTEGER,
    
    -- 압축
    response_format TEXT,
    original_size_bytes INTEGER,
    compressed_size_bytes INTEGER,
    
    -- 메타데이터
    user_agent TEXT,
    source TEXT  -- 'mcp_stdio', 'mcp_pure', 'web_api'
);

CREATE INDEX idx_search_metrics_timestamp ON search_metrics(timestamp);
CREATE INDEX idx_search_metrics_project ON search_metrics(project_id);
```

**EmbeddingMetrics 테이블**:
```sql
CREATE TABLE embedding_metrics (
    id TEXT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    operation TEXT NOT NULL,  -- 'generate', 'batch_generate'
    
    -- 성능
    count INTEGER NOT NULL,  -- 생성된 임베딩 수
    total_time_ms INTEGER NOT NULL,
    avg_time_per_embedding_ms REAL,
    
    -- 캐시
    cache_hit BOOLEAN,
    
    -- 리소스
    memory_usage_mb REAL,
    model_name TEXT
);

CREATE INDEX idx_embedding_metrics_timestamp ON embedding_metrics(timestamp);
```

### API 엔드포인트

**GET /api/monitoring/search/metrics**
- Query params: `start_date`, `end_date`, `project_id`, `aggregation` (hourly/daily)
- Response: 집계된 검색 메트릭

**GET /api/monitoring/search/queries**
- Query params: `limit`, `sort_by` (frequency/similarity/time)
- Response: 검색 쿼리 목록

**GET /api/monitoring/embedding/metrics**
- Query params: `start_date`, `end_date`
- Response: 임베딩 성능 메트릭

**GET /api/monitoring/tokens/usage**
- Query params: `start_date`, `end_date`, `group_by` (operation/project)
- Response: 토큰 사용량 통계

**GET /api/monitoring/alerts**
- Query params: `status` (active/resolved), `limit`
- Response: 알림 목록

## 성공 지표

- 검색 품질 메트릭 실시간 조회 가능
- 성능 저하 감지 시간 < 5분
- 대시보드 로딩 시간 < 2초
- 메트릭 수집 오버헤드 < 5%
- 알림 정확도 > 95%

## 비기능 요구사항

- **성능**: 메트릭 수집이 검색 성능에 미치는 영향 최소화 (< 5% 오버헤드)
- **확장성**: 일일 10만 건 이상의 검색 메트릭 처리 가능
- **보안**: 민감한 쿼리 내용은 해시 처리 옵션 제공
- **유지보수**: 메트릭 데이터 자동 정리 (90일 이상 데이터 삭제)
