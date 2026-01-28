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
### Session Start
- Always begin with `mcp_mem_mesh_session_resume` (project_id=mem-mesh, expand=false, limit=10) and report the returned summary (pins_count, open_pins, completed_pins) before modifying AGENT files.

### During Work
- For every new task, call `mcp_mem_mesh_pin_add` with a one-line description, importance (default 3, 4 for important changes, 5 for architecture), and relevant tags. Report the `pin_id` immediately in your response. Work must not proceed until a pin exists.
- Track dependencies and context by referencing the pin content; keep importance aligned with impact.

### After Work
- Call `mcp_mem_mesh_pin_complete` with the `pin_id` when work finishes. If importance ≥4, recommend `mcp_mem_mesh_pin_promote` to preserve the outcome and mention the promotion ID in the wrap-up.
- Close the session with `mcp_mem_mesh_session_end` (project_id=mem-mesh) and summarize the session in the final report.
