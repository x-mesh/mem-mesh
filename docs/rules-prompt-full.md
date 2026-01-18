# mem-mesh Rules (Canonical)

## 0) TL;DR (필수 5줄)
1. 작업 시작/컨텍스트 전환 전 `mcp_mem_mesh_search(query, project_id, limit=3~5)` 호출
2. 관련 메모리 있으면 `mcp_mem_mesh_context(memory_id, depth=2)`로 확장
3. 작업 시작 시 `mcp_mem_mesh_pin_add`, 완료 시 `mcp_mem_mesh_pin_complete` (importance >= 4 → promote)
4. 결정/버그/사고/재사용 코드/중요 요구사항 완료 즉시 `mcp_mem_mesh_add`
5. 기존 내용 대체 시 `mcp_mem_mesh_update` (중복 금지), 성공 전 “저장됨” 발언 금지

## 1) 조회 규칙 (Mandatory)
- 새 작업 시작/전환 시 반드시 검색
- 검색 결과는 실제 응답/수행에 반영
- 필요할 때만 컨텍스트 확장 조회

## 2) 저장 규칙 (Mandatory)
다음 이벤트는 즉시 저장:
- 버그 진단 및 해결 완료 → `category="bug"`
- 아키텍처/트레이드오프 결정 → `category="decision"`
- 재사용 가능한 코드/패턴 → `category="code_snippet"`
- 중요 요구사항/작업 이정표 완료 → `category="task"`
- 심각 장애/사고 → `category="incident"`

새 정보가 기존 메모리를 대체하면 반드시 `mcp_mem_mesh_update`로 업데이트.

## 3) 포맷 규칙 (Strict)
- **언어**: 한국어만 사용
- **카테고리**: `bug | decision | code_snippet | task | incident` (5개만)
- **태그**: 3~6개, 반드시 포함:
  - 기술 스택 (예: `Python`, `FastAPI`, `SQLite`)
  - 모듈/영역 (예: `API`, `Database`, `Search`)
  - 액션 타입 (예: `Fix`, `Feature`, `Refactor`)
- **보안**: 비밀/토큰/PII/절대 경로 저장 금지

### content 템플릿 (Markdown 고정)
```
## [한 줄 요약 제목]

### 배경 (WHY)
[문제/컨텍스트]

### 내용 (WHAT)
- 파일: `relative/path` - [주요 변경]
- 파일: `relative/path2` - [주요 변경]

### 영향 (IMPACT)
[효과/주의사항]
```

## 4) 정직성 규칙
- 툴 성공 전 “저장 완료” 언급 금지
- 실패 시 의도한 payload를 그대로 제공

## 5) 프로젝트 특화
- mem-mesh 프로젝트는 `project_id="mem-mesh"` 고정
- 절대 경로 금지 (상대 경로만)
