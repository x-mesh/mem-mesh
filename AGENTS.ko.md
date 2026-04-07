# mem-mesh: AI Memory Management System

## Project Context & Operations
**Business Goal:** 중앙 집중식 메모리 서버를 통해 AI 도구가 벡터 검색과 컨텍스트 조회를 활용하여 실시간으로 기억을 저장·조정하도록 지원합니다.  
**Tech Stack:** Python 3.9+, FastAPI, FastMCP, sqlite-vec, sentence-transformers, MCP Protocol 2024-11-05/2025-03-26 transports.  
**Operational Commands:**
```bash
# Development
python -m app.web --reload              # FastAPI + SSE MCP dashboard
python -m app.mcp_stdio                 # FastMCP 기반 stdio MCP 서버
python -m app.mcp_stdio_pure            # Pure MCP stdio MCP 서버

# Testing
python -m pytest tests/                 # 전체 테스트
python -c "from app.web.app import app"  # FastAPI import check

# Database Migration
python scripts/migrate_embeddings.py --check-only
python scripts/migrate_embeddings.py --dry-run

# Production
uvicorn app.web.app:app --host 0.0.0.0 --port 8000
```

Note: If port 8000 is already in use locally, it indicates the FastAPI server is already running in reload mode. Do not restart it.

## Golden Rules
**Immutable Constraints:**
- SQLite + sqlite-vec virtual tables are the sole vector store; no external vector DBs allowed.
- MCP Protocol compliance (2024-11-05 core tools, 2025-03-26 Streamable HTTP transport) must be enforced through shared schemas/dispatchers.
- sentence-transformers models are the only source of embeddings; model changes require migration.
- The canonical database file is `./data/memories.db` (override only via Settings).

**Do's:**
- Use `app.core.version` for all version metadata exposed across MCP transports and APIs.
- Implement every SQL/vector operation via async/await flows inside the Database classes.
- Route shared MCP logic through `mcp_common` (tools, dispatcher, transport) to avoid duplicated protocol handling.
- Emit text log format by default (`MCP_LOG_FORMAT=text`) and keep logs structured for tracing.
- Validate external input through Pydantic schemas before touching services or storage.

**Don'ts:**
- Never use `INSERT OR REPLACE` with sqlite-vec virtual tables; prefer DELETE+INSERT.
- Avoid embedding hardcoded version/server info outside of centralized modules.
- Do not bypass the storage abstraction or open raw sqlite connections outside the Database classes.
- Do not enable JSON logging inside MCP transports unless explicitly configured.
- Do not perform database work from synchronous functions or from route handlers directly.

## Standards & References
**Code Conventions:**
- Format Python with Black and include type hints in public APIs.
- Maintain import order: stdlib → third-party → local (favor absolute imports).
- Wrap async functions in try/except, log failures, and propagate structured errors.

**Git Strategy:**
- Commit message format: `type: description` (feat, fix, refactor, docs, test, chore).
- Whenever Korean explanations are needed, pair them with English technical terms for clarity.
- Use `git --no-pager` variants (`git --no-pager log`, `git --no-pager status`) when reviewing history.

## Workflow
**Thinking Process (CoT)**

Before generating code or executing commands, you must perform a brief <Thinking> step:
1. Identify Intent: What is the user's specific goal? (Feat/Fix/Refactor/Query)
2. Check Context: Which AGENTS.md or module is relevant? (Refer to Context Map)
3. Verify Constraints: Does this action violate any Golden Rules?
4. Plan: Outline the step-by-step execution plan.

**Maintenance Policy:**
규칙과 코드 사이에 괴리가 보이면 즉시 개선 제안을 제출하고, 중앙 통제 루트(이 AGENTS.md) 및 관련 AGENT 하위 파일을 동시에 업데이트합니다.

## Context Map (Action-Based Routing)
- **[Core Services & Database](./app/core/AGENTS.md)** — 데이터/임베딩/서비스 변경 시.
- **[MCP Protocol Implementation](./app/mcp_common/AGENTS.md)** — 공통 MCP 도구, 스토리지, 스키마 작업 시.
- **[Web API & Dashboard](./app/web/AGENTS.md)** — FastAPI 앱, WebSocket, 전반 UI 라우팅 또는 템플릿 변경 시.
- **[SSE MCP Transport](./app/web/mcp/AGENTS.md)** — Streamable HTTP/SSE MCP 전송 계층 수정 시.
- **[FastMCP stdio Server](./app/mcp_stdio/AGENTS.md)** — FastMCP 기반 stdio 서버 작업 시.
- **[Pure MCP stdio Server](./app/mcp_stdio_pure/AGENTS.md)** — 직접 MCP 프로토콜 구현/디스패처 조정 시.
- **[Frontend Static Assets](./static/AGENTS.md)** — JavaScript/CSS/프론트엔드 로직 수정 시.
- **[Migration & Utility Scripts](./scripts/AGENTS.md)** — 마이그레이션, 임베딩/QA/모니터링 유틸리티 작성 또는 실행 시.
- **[Testing & Quality](./tests/AGENTS.md)** — pytest suites, 통합/회귀 테스트, 테스트 지원 도구 업데이트 시.
- **[Web Dashboard Pages](./app/web/dashboard/AGENTS.md)** — 대시보드 라우트, 페이지 템플릿, SSE MCP endpoint 고도화 시.

## Session Context Management

> CLAUDE.md의 Checklist와 MUST/SHOULD/MAY 규칙에 대한 상세 구현 가이드.

### Session Lifecycle

```
세션 시작 ──→ 작업 추적 ──→ 세션 종료
   │              │              │
   ▼              ▼              ▼
session_resume  pin_add       지식 보존 판단
   │            pin_complete     │
   │            pin_promote    session_end
   │              │
   └──── search (과거 맥락) ────┘
```

### Session Start
```
mcp_mem_mesh_session_resume(project_id="mem-mesh", expand="smart", limit=10)
```
Report: `pins_count`, `in_progress_pins`, `open_pins`, `completed_pins`

**Stale 자동 정리:** `session_resume` 호출 시 오래된 핀을 자동 완료 처리
- `in_progress` 상태 7일 경과 → `completed`
- `open` 상태 30일 경과 → `completed`

**Token Optimization — expand 모드:**
- `expand="smart"` (권장): status × importance 4-Tier 매트릭스
  - T1: active + important(≥4) → full content + tags + created_at
  - T2: active + normal(<4) → content[:200] + tags
  - T3: completed + important → content[:80]
  - T4: completed + normal → id + importance + status only
- `expand=false`: All pins as 80-char compact summary — saves ~90% tokens
- `expand=true`: Full pin content loaded
- `token_info` shows: `loaded_tokens`, `unloaded_tokens`, `estimated_total`

### Task Start
```
mcp_mem_mesh_pin_add(content="<description>", project_id="mem-mesh", importance=3, tags=[...])
```
- `3`: normal, `4`: important, `5`: architecture
- importance 생략 시 내용 기반 자동 추정
- 기본 상태: `in_progress` (작업 중). 다단계 작업에서 나중 작업은 `open`(계획됨)으로 생성 가능
- 응답(compact): `{id, importance, status}` — 자동 추정 시 `auto_importance: true` 추가
- Wait for `pin_id` before proceeding

**클라이언트 감지:** HTTP 모드에서 MCP initialize 핸드셰이크 또는 User-Agent로 자동 감지 (25+ IDE/AI 플랫폼). Stdio 모드에서는 `MEM_MESH_CLIENT` 환경변수 사용.

### Task Complete
```
mcp_mem_mesh_pin_complete(pin_id="<pin_id>")
```
If importance ≥ 4: `mcp_mem_mesh_pin_promote(pin_id)`

### Session End & Knowledge Preservation
```
mcp_mem_mesh_session_end(project_id="mem-mesh")
```

**세션 종료 시 지식 보존 판단 기준:**

| 세션에서 발생한 일 | 저장 방법 | 예시 |
|-----------------|---------|------|
| 아키텍처 결정 합의 | `add(category="decision")` | "SQLite + sqlite-vec 유일 벡터 저장소 확정" |
| 복잡한 버그 해결 | `add(category="bug")` | "sqlite-vec INSERT OR REPLACE 금지 — DELETE+INSERT" |
| 시스템 장애 복구 | `add(category="incident")` | "포트 8000 충돌로 서버 이중 기동 발생" |
| 개선 아이디어 | `add(category="idea")` | "한국어 검색에 E5 prefix encoding 검토" |
| 재사용 패턴 발견 | `add(category="code_snippet")` | batch_operations 사용 패턴 |
| Pin으로 추적 중인 작업 | `pin_complete` + 필요시 `pin_promote` | — |

**저장하지 않는 것**: 단순 Q&A, 파일 읽기, 이미 저장된 내용 반복, 모든 코드 변경 기록.
저장 시 반드시 **변경 이유(WHY)** 포함.

### Security — 민감 정보 저장 금지

메모리(`add`, `pin_add`)에 아래 정보를 **절대 저장하지 않는다**:
- API 키, 토큰, 시크릿, 비밀번호
- 개인식별정보(PII): 이메일, 전화번호, 주민등록번호
- `.env` 파일 내용, 인증 정보
- 코드 스니펫 저장 시 민감 값은 `<REDACTED>`로 치환

### Batch Operations (30-50% token savings)
```
mcp_mem_mesh_batch_operations(operations=[
  {"type": "add", "content": "...", "project_id": "...", "category": "task"},
  {"type": "search", "query": "...", "limit": 5}
])
```

### Memory Relations
- `link(source_id, target_id, relation_type)` - Create relation
- `get_links(memory_id)` - Get relations
- Types: `related` | `parent` | `child` | `supersedes` | `references` | `depends_on` | `similar`

### Search Patterns
- Recent: `search(query="", limit=5)`
- Project: `search(query="...", project_id="...")`
- Recency: `search(query="...", recency_weight=0.3)`
- Category: `search(query="", category="decision")`

### Categories
`task` | `bug` | `idea` | `decision` | `incident` | `code_snippet` | `git-history`

### Anti-Patterns (하지 말 것)
- Hook 기반 자동 저장 — 바이트 절단으로 63.4% truncation, 검색 오염 20-30%
- 모든 파일 변경을 메모리에 기록 — 검색 슬롯 낭비
- 세션 요약을 head -c로 잘라 저장 — UTF-8 깨짐
- 맥락 없이 코드 조각만 저장 — WHY 없으면 나중에 무의미