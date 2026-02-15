# RFC: 검색 모드 단순화

## 현황

현재 UnifiedSearchService는 5가지 검색 모드를 지원합니다:
- `smart` (기본) — 의도 분석 후 자동 모드 선택
- `hybrid` — 벡터 + FTS 병렬 검색 + RRF 병합
- `exact` — FTS5만 사용
- `semantic` — 벡터 검색만 사용
- `fuzzy` — SequenceMatcher 기반 퍼지 매칭

추가로 `services/legacy/search.py`의 SearchService도 아직 사용 중입니다.

## 문제점

1. `smart` 모드는 내부적으로 `hybrid`, `exact`, `semantic`으로 라우팅 → 사실상 wrapper
2. `fuzzy` 모드는 비벡터 기반이라 대규모 데이터에서 비효율적
3. 레거시 `SearchService`와 `UnifiedSearchService`가 공존
4. 동작 차이 파악이 어렵고 테스트/유지보수 비용 증가

## 제안

### Phase 1: 기본 모드 변경 (단기)
- `hybrid`를 기본 모드로 설정 (현재 `smart`가 기본)
- `smart` 모드를 `hybrid`의 별칭(alias)으로 유지
- `fuzzy` 모드에 deprecation warning 추가

### Phase 2: 레거시 SearchService 이전 (중기)
- `batch_tools.py`, `storage/direct.py`, `mcp_stdio/server.py`에서
  레거시 SearchService 대신 UnifiedSearchService 사용
- `services/legacy/search.py`에 deprecation warning 추가

### Phase 3: 검색 모드 통합 (장기)
- `smart` 모드 제거, `hybrid`로 통합
- `fuzzy` 모드 제거 (필요 시 FTS5 prefix 검색으로 대체)
- 최종 모드: `hybrid` (기본), `exact`, `semantic`

## 마이그레이션 영향

- MCP 도구의 `search_mode` 파라미터는 유지 (하위 호환)
- deprecated 모드 사용 시 warning 로그 + 자동 fallback

## 일정

- Phase 1: 다음 마이너 릴리스
- Phase 2: v1.1.0
- Phase 3: v2.0.0
