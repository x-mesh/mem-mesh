# mem-mesh Default Prompt Rules

> mem-mesh MCP 서버를 사용하는 모든 프로젝트에 적용할 수 있는 기본 행동 규칙.
> Hook 없이 프롬프트만으로 AI 에이전트가 mem-mesh를 올바르게 사용하도록 안내한다.
>
> **사용법**: 아래 `---` 사이의 프롬프트 블록을 프로젝트의 CLAUDE.md, `.cursor/rules/`, Kiro steering 등에 복사.

---

```markdown
## mem-mesh Memory (MCP)

You have access to mem-mesh, a persistent memory system via MCP tools.
Use it to maintain context across sessions — but code and answers always come first.

### PROJECT ID

Directory name → project_id. Example: /path/to/my-app → project_id="my-app"
Auto-normalized: camelCase/PascalCase → kebab-case (myApp → my-app)

### SESSION LIFECYCLE (MUST)

1. **Session start** — 첫 응답 직후 `session_resume(project_id, expand="smart")` 호출.
   미완료 핀이 있으면 사용자에게 알린다.
2. **Session end** — 사용자가 작업 완료를 명시하면("끝", "PR 올려줘" 등):
   - 영구 저장 가치 판단 (decision/bug/code_snippet → `add`)
   - 진행 중 핀 → `pin_complete` (중요시 `pin_promote`)
   - `session_end(project_id)` 호출

### WHEN TO SEARCH (SHOULD)

- 과거 결정/설계/버그를 언급하거나 관련 작업 시작 전 → `search(query, project_id)` 먼저
- ✅ 구문 사용: "token optimization strategy", "인증 아키텍처 결정"
- ❌ 단일 단어 금지: "token", "인증"
- 최신 우선: `recency_weight=0.3`

### WHEN TO SAVE (SHOULD)

저장 트리거 발생 시 `add(content, category, project_id, tags)`:

| 트리거 | category |
|--------|----------|
| 아키텍처/트레이드오프 결정 | `decision` |
| 버그 진단/해결 | `bug` |
| 재사용 코드/패턴 | `code_snippet` |
| 장애/사고 | `incident` |
| 아이디어 | `idea` |

일상 작업은 `pin_add` → `pin_complete`으로 추적. `add`는 영구 보존 가치가 있는 것만.

### SAVE FORMAT

```
## [한 줄 요약]

### WHY
[왜 이 결정/변경이 필요했는가]

### WHAT
- 파일: `path` - [변경사항]

### IMPACT
[효과/주의사항]
```

Tags: 3-6개 (기술 + 모듈 + 액션). 중복 시 `update(memory_id)` 사용.

### PIN WORKFLOW (SHOULD)

진행 중 작업 추적:
1. `pin_add(content, project_id, importance=3)` — 작업 시작 (기본 상태: `in_progress`)
2. `pin_complete(pin_id, promote=true)` — 완료 + 승격을 한 번에 처리
3. importance ≥ 4 → 별도 승격 시 `pin_promote(pin_id)`

핀 상태: `open`(계획됨) → `in_progress`(작업 중, 기본값) → `completed`(완료)
Stale 자동 정리: session_resume 시 in_progress 7일, open 30일 경과 → completed

### BATCH (MAY)

여러 메모리 작업 시 `batch_operations`로 묶어 30-50% 토큰 절감.

### RELATIONS (MAY)

- 결정 업데이트 → 이전 결정과 `supersedes` 연결
- 버그 수정 → 원인과 `references` 연결
- 의존성 → `depends_on` 연결

### SECURITY (MUST)

- API 키, 토큰, 비밀번호, PII, .env 내용 **절대 저장 금지**
- 코드 스니펫의 민감 값은 `<REDACTED>` 치환

### PRIORITY

코딩 응답 > 메모리 작업. 코드와 답변을 먼저 제공하고, 메모리 저장은 그 후에.
단, 과거 맥락이 현재 작업에 직접 영향을 줄 때는 search() 후 코딩.
```

---

## 사용 예시

### Claude Code (CLAUDE.md)

프로젝트의 `CLAUDE.md`에 위 블록을 복사:

```markdown
# My Project

## 빌드
npm run build

## mem-mesh Memory (MCP)
... (위 블록 복사) ...
```

### Cursor (.cursor/rules/)

`.cursor/rules/mem-mesh.mdc` 파일로 저장:

```
---
description: mem-mesh MCP memory rules
globs: **/*
---

(위 블록 복사)
```

### Kiro (.kiro/steering/)

`.kiro/steering/memory.md` 파일로 저장.

---

## 커스터마이즈

프로젝트별로 다음을 오버라이드할 수 있다:

| 항목 | 기본값 | 오버라이드 예시 |
|------|--------|----------------|
| project_id | 디렉토리명 자동 감지 | `project_id="custom-name"` 명시 |
| 저장 카테고리 | decision, bug, code_snippet, incident, idea | 프로젝트에서 안 쓰는 카테고리 제거 |
| session_resume expand | `"smart"` | `false` (최소 토큰) 또는 `true` (전체) |
| 저장 포맷 | WHY/WHAT/IMPACT | 프로젝트 컨벤션에 맞게 변경 |

## 관련 문서

- [all-tools-full.md](./all-tools-full.md) — 15개 도구 전체 레퍼런스 (~1500 토큰)
- [mem-mesh-ide-prompt.md](./mem-mesh-ide-prompt.md) — 초경량 IDE 프롬프트 (~300 토큰)
- [modules/](./modules/) — 기능별 모듈 (search, pins, relations 등)
