# 검색 품질 개선사항
Search Quality Improvements

## 개요

mem-mesh 검색 품질을 향상시키기 위한 즉시 개선 사항들입니다.

## 구현된 개선사항

### 1. 노이즈 필터 완성 ✅

**파일**: `app/core/services/noise_filter.py`

**개선 내용**:
- 잘린 정규식 패턴 수정 완료
- 추가 노이즈 패턴 정의 (단순 응답: ok, yes, no)
- 완전한 필터링 로직 구현

**기능**:
```python
# 노이즈 프로젝트 필터링
- kiro-, test-, tmp-, temp-, demo- 프로젝트 제외 또는 점수 감소

# 노이즈 콘텐츠 필터링
- 반복되는 규칙 텍스트
- 반복되는 프롬프트
- 빈 콘텐츠
- 단순 응답 (ok, yes, no)

# 중복 제거
- 콘텐츠 해시 기반 중복 감지
- 최대 3개까지 중복 허용

# 부스팅
- 선호 프로젝트 (mem-mesh): 1.3x
- 프로젝트 힌트 매칭: 1.5x
- 쿼리 관련성: 1.2x
```

**사용 예시**:
```python
from app.core.services.noise_filter import NoiseFilter

filter_service = NoiseFilter()
filtered_results = filter_service.filter(
    results=search_results,
    query="검색 쿼리",
    project_hint="mem-mesh",
    aggressive=False  # True면 노이즈 완전 제거
)
```

### 2. MCP 검색에 노이즈 필터 통합 ✅

**파일**: `app/mcp_common/tools.py`

**개선 내용**:
- `search()` 메서드에 `enable_noise_filter` 파라미터 추가 (기본값: True)
- SmartSearchFilter 자동 적용
- 필터링 고려하여 더 많은 결과 가져온 후 필터링

**변경사항**:
```python
async def search(
    query: str,
    project_id: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 5,
    recency_weight: float = 0.0,
    response_format: str = "standard",
    enable_noise_filter: bool = True  # 새로 추가
) -> Dict[str, Any]:
    # ...
    # 노이즈 필터 자동 적용
    if enable_noise_filter and result.results:
        from ..core.services.noise_filter import SmartSearchFilter
        filter_service = SmartSearchFilter()
        context = {
            'project': project_id,
            'max_results': limit,
            'aggressive_filter': False
        }
        result = filter_service.apply(result, query, context)
```

**효과**:
- MCP를 통한 모든 검색에 자동으로 노이즈 필터 적용
- 검색 품질 즉시 향상
- 필요시 `enable_noise_filter=False`로 비활성화 가능

### 3. 스코어링 파이프라인 확인 ✅

**파일**: `app/core/services/search.py`

**확인 결과**:
- `ScoringPipeline`이 이미 `_vector_search()` 메서드에 통합되어 있음
- 다음 스코어러들이 활성화되어 있음:
  - ExactMatchScorer: 정확한 텍스트 매칭
  - ContentQualityScorer: 콘텐츠 품질 평가
  - RecencyScorer: 최신성 점수 (recency_weight > 0일 때)
  - CategoryBoostScorer: 카테고리별 부스트
  - TagMatchScorer: 태그 매칭 보너스

**추가 작업 불필요**: 이미 올바르게 구현되어 있음

## 테스트

**파일**: `tests/test_search_quality_improvements.py`

**테스트 케이스**:
1. 노이즈 프로젝트 필터링
2. 노이즈 콘텐츠 필터링
3. 중복 콘텐츠 제거
4. 선호 프로젝트 부스팅
5. 시간 범위 필터링
6. 컨텍스트 인식 필터링

**실행 방법**:
```bash
python -m pytest tests/test_search_quality_improvements.py -v
```

## 사용 가이드

### MCP를 통한 검색

```python
# 기본 사용 (노이즈 필터 자동 적용)
result = await mcp_tools.search(
    query="검색어",
    project_id="mem-mesh",
    limit=10
)

# 노이즈 필터 비활성화
result = await mcp_tools.search(
    query="검색어",
    enable_noise_filter=False
)
```

### 직접 노이즈 필터 사용

```python
from app.core.services.noise_filter import SmartSearchFilter

filter_service = SmartSearchFilter()
filtered_response = filter_service.apply(
    response=search_response,
    query="검색어",
    context={
        'project': 'mem-mesh',
        'time_range': '30d',  # 최근 30일
        'max_results': 10,
        'aggressive_filter': False
    }
)
```

## 성능 영향

- **노이즈 필터링**: 검색 결과 후처리이므로 성능 영향 미미 (< 1ms)
- **중복 제거**: O(n) 복잡도, 해시 기반으로 빠름
- **메모리**: 추가 메모리 사용 최소 (해시 테이블만)

## 향후 개선 계획

### 중기 (1-2주)
1. **검색 서비스 통합**: 5개의 검색 구현을 하나로 통합
2. **의도 기반 자동 조정**: SearchIntentAnalyzer를 기본 검색에 통합
3. **피드백 루프**: RelevanceFeedback 실제 사용 및 저장

### 장기 (1-2개월)
1. **A/B 테스트**: 검색 품질 측정 프레임워크
2. **동적 가중치 학습**: 사용 패턴 기반 자동 조정
3. **실시간 모니터링**: 검색 품질 메트릭 대시보드

## 관련 파일

- `app/core/services/noise_filter.py` - 노이즈 필터 구현
- `app/core/services/scoring.py` - 스코어링 파이프라인
- `app/core/services/search_quality.py` - 고급 품질 시스템
- `app/core/services/search.py` - 기본 검색 서비스
- `app/mcp_common/tools.py` - MCP 도구 핸들러
- `tests/test_search_quality_improvements.py` - 테스트

## 변경 이력

- 2026-01-20: 초기 개선사항 구현
  - 노이즈 필터 완성
  - MCP 검색 통합
  - 테스트 작성
