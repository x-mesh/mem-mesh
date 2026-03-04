# mem-mesh Rules (All Tools Full)

AI 에이전트가 mem-mesh MCP 도구를 최적으로 사용하기 위한 규칙. IDE system prompt/rules에 주입.

---

## 1. 도구 목록 (15개)

| 도구 | 필수 파라미터 | 용도 |
|------|--------------|------|
| `add` | content | 메모리 저장 |
| `search` | query | 메모리 검색 |
| `context` | memory_id | 컨텍스트 조회 |
| `update` | memory_id | 메모리 수정 |
| `delete` | memory_id | 메모리 삭제 |
| `stats` | - | 통계 조회 |
| `pin_add` | content, project_id | 핀(작업) 생성 |
| `pin_complete` | pin_id | 핀 완료 |
| `pin_promote` | pin_id | 핀→영구 메모리 승격 |
| `session_resume` | project_id | 세션 복원 |
| `session_end` | project_id | 세션 종료 |
| `link` | source_id, target_id | 관계 생성 |
| `unlink` | source_id, target_id | 관계 삭제 |
| `get_links` | memory_id | 관계 조회 |
| `batch_operations` | operations | 배치 작업 |

---

## 2. 핵심 워크플로우

### 검색 → 작업 → 저장 사이클

```
1. search(query, project_id, limit=5)     # 작업 시작/전환 시
2. [작업 수행]
3. add(content, category, project_id, tags) # 트리거 발생 시
```

- **작업 시작/전환 전** `search(query, project_id, limit=3~5)` 호출
- **필요할 때만** `context(memory_id, depth=2)` — 검색 결과가 실제 작업에 중요할 때
- **저장 트리거** 발생 시 즉시 `add(...)` 호출
- **중복 방지**: 대체 시 `update(memory_id, ...)` 사용

### 프로젝트 감지

- 디렉토리명 → `project_id`: `/path/to/my-app` → `project_id="my-app"`
- `project_id`는 자동 정규화: camelCase/PascalCase → kebab-case (예: `"jmonServerWeb"` → `"jmon-server-web"`)
- 명시적 지정: `project_id="custom-project"`

---

## 3. 세션 워크플로우 (토큰 최적화)

```
session_resume(expand=false) → pin_add → [work] → pin_complete → (pin_promote) → session_end
```

- **시작**: `session_resume(project_id, expand=false, limit=10)` — 요약만 로드 (~90% 토큰 절약)
- **작업 추적**: `pin_add(content, project_id, importance=3)` → `pin_complete(pin_id)`
- **importance ≥ 4**: `pin_promote(pin_id)` 제안
- **종료**: `session_end(project_id)`

---

## 4. 검색 최적화

### 쿼리 작성
- ✅ 구문 사용: `"token optimization strategy"`, `"검색 품질 최적화"`
- ❌ 단일 단어 금지: `"token"`, `"검색"`
- 한국어 복합어: 4음절 이상은 자동 n-gram 분해 (예: "토큰최적화" → 부분 매칭)
- 하이브리드 검색: 벡터 + FTS 동시 사용, RRF로 결합

### 검색 엔진 동작
- **E5 모델**: query/passage prefix 자동 적용 (E5 계열 감지 시)
- **Sigmoid 정규화**: 점수 분포 0.3~0.7에 맞게 조정
- **RRF 가중치**: FTS 키워드 매칭 우대 (vector_weight=1.0, text_weight=1.2)

### 파라미터
- `project_id`: 항상 지정 (관련성 ↑)
- `category`: decision, code_snippet 등 필터
- `limit`: 3~5 (기본 5)
- `recency_weight`: 0.2~0.5 — 최근 메모리 우선
- `response_format`: minimal/compact/standard/full (토큰 절약용)

### 예시
```
search(query="E5 모델 prefix 적용", project_id="mem-mesh", limit=5)
search(query="", category="decision", limit=5)  # 최근 결정만
search(query="버그 수정", project_id="my-app", recency_weight=0.3)
```

---

## 5. 메모리 저장

### 저장 트리거 (즉시 add)
- 버그 진단/해결 → `category="bug"`
- 아키텍처/트레이드오프 결정 → `category="decision"`
- 재사용 코드/패턴 → `category="code_snippet"`
- 중요 요구사항/작업 완료 → `category="task"`
- 사고/장애 → `category="incident"`
- 아이디어 → `category="idea"`
- Git 이력 관련 → `category="git-history"`

### 포맷 (WHY/WHAT/IMPACT)
```
## [한 줄 요약]

### 배경 (WHY)
[문제/컨텍스트]

### 내용 (WHAT)
- 파일: `path` - [변경사항]

### 영향 (IMPACT)
[효과/주의사항]
```

### 카테고리 (7종)
`task` | `bug` | `idea` | `decision` | `incident` | `code_snippet` | `git-history`

### 태그 (3~6개 필수)
- 기술 스택: Python, FastAPI, SQLite
- 모듈: API, Search, Database
- 액션: Fix, Feature, Refactor

### 중복 방지
- 대체 시 `update(memory_id, content, ...)` 사용
- search로 기존 메모리 확인 후 update vs add 결정

---

## 6. 관계 (Relations)

### 관계 타입
`related` | `parent` | `child` | `supersedes` | `references` | `depends_on` | `similar`

### 사용
```
link(source_id, target_id, relation_type="depends_on", strength=0.9)
get_links(memory_id, relation_type="references", direction="outgoing")
unlink(source_id, target_id, relation_type)  # relation_type 생략 시 전체 삭제
```

### 시나리오
- 버그 수정 → 원인 메모리와 `references` 연결
- 결정 업데이트 → 이전 결정과 `supersedes` 연결
- 의존성 → `depends_on` 연결

---

## 7. 배치 작업

```
batch_operations(operations=[
  {"type": "add", "content": "...", "project_id": "...", "category": "task"},
  {"type": "search", "query": "...", "limit": 5}
])
```

- add + search 조합 시 30~50% 토큰 절약
- 여러 검색/저장을 한 번에 처리

---

## 8. 컨텍스트 조회

- 검색 결과가 작업에 중요할 때만 `context(memory_id, depth=2)` 호출
- depth 1~5, 기본 2
- 연관 메모리까지 함께 반환

---

## 9. 통계 조회

```
stats()                                          # 전체 통계
stats(project_id="my-app")                       # 프로젝트별 통계
stats(start_date="2026-01-01", end_date="2026-01-31")  # 기간별 통계
```

- 총 메모리 수, 카테고리 분포, 프로젝트 분포, 최근 활동 반환
- `project_id`, `start_date`, `end_date` 모두 선택적

---

## 10. 보안/정직성

- 비밀/토큰/PII/절대 경로 저장 금지
- 도구 성공 전 "저장 완료" 언급 금지
- 실패 시 의도한 payload를 그대로 제공

---

## 11. 팀 맥락

- 결정/사고/재사용 패턴 위주 저장
- Q/A 전체 저장 최소화 (노이즈 증가)

---

## 12. API 사용

- 규칙 목록: `GET /api/rules`
- 규칙 조회: `GET /api/rules/{rule_id}`
- 규칙 수정: `PUT /api/rules/{rule_id}` (content 필수)
- API로 가져온 규칙은 로컬 툴에 맞게 함수명만 치환해서 사용
