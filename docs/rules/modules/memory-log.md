# Memory Log Rules — 저장 가이드

메모리 저장 트리거, 포맷, 카테고리, 태그 상세.

---

## 저장 트리거 (즉시 add)

| 이벤트 | category |
|--------|----------|
| 버그 진단/해결 완료 | `bug` |
| 아키텍처/트레이드오프 결정 | `decision` |
| 재사용 코드/패턴 작성 | `code_snippet` |
| 중요 요구사항/작업 이정표 | `task` |
| 사고/장애 | `incident` |
| 아이디어 | `idea` |
| Git 이력 관련 | `git-history` |

---

## 저장 포맷 (WHY/WHAT/IMPACT)

```
## [한 줄 요약 제목]

### 배경 (WHY)
[문제나 컨텍스트가 무엇이었는지]

### 내용 (WHAT)
- 파일: `path/to/file` - [주요 변경사항]
- 파일: `path/to/file2` - [주요 변경사항]

### 영향 (IMPACT)
[결과, 효과, 주의사항]
```

---

## 카테고리 (7종, 필수)

`task` | `bug` | `idea` | `decision` | `incident` | `code_snippet` | `git-history`

- **task**: 일반 작업, 요구사항
- **bug**: 에러 수정, 이슈 해결
- **idea**: 아이디어, 제안
- **decision**: 아키텍처 선택, 설계 결정
- **incident**: 서버 크래시, 장애
- **code_snippet**: 재사용 함수, 패턴
- **git-history**: 커밋/브랜치 관련

---

## 태그 규칙 (3~6개 필수)

1. **기술 스택**: Python, FastAPI, SQLite, React
2. **모듈/영역**: API, Search, Database, Frontend
3. **액션 타입**: Fix, Feature, Refactor, Optimization

예: `["FastAPI", "Stats", "Optimization", "SQL", "Performance"]`

---

## 중복 방지

1. `search(query, project_id)`로 기존 메모리 확인
2. 대체할 내용이 있으면 `update(memory_id, content, ...)` 사용
3. **add로 중복 저장 금지**
