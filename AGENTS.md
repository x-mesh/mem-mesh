# mem-mesh: AI Memory Management System

## Project Context & Operations

**Business Goal:** AI 에이전트를 위한 중앙 집중식 메모리 서버. 벡터 검색과 컨텍스트 조회를 통한 지능형 메모리 관리.

**Tech Stack:** Python 3.9+, FastAPI, SQLite + sqlite-vec, sentence-transformers, MCP Protocol

**Operational Commands:**
```bash
# Development
python -m app.web --reload              # Web Dashboard + SSE MCP
python -m app.mcp_stdio                 # FastMCP-based MCP Server
python -m app.mcp_stdio_pure            # Pure MCP Implementation

# Testing
python -m pytest tests/                 # Run test suite
python -c "from app.web.app import app" # Quick import test

# Database Migration
python scripts/migrate_embeddings.py --check-only
python scripts/migrate_embeddings.py --dry-run

# Production
uvicorn app.web.app:app --host 0.0.0.0 --port 8000
```

## Golden Rules

**Immutable Constraints:**
- SQLite with sqlite-vec for vector operations - NO external vector databases
- MCP Protocol 2024-11-05 compliance mandatory
- All embeddings use sentence-transformers models only
- Database path: `./data/memories.db` (configurable via Settings)

**Do's:**
- Use `app.core.version` for all version/server info references
- Implement proper async/await patterns for all database operations
- Use `mcp_common` module for shared MCP tool logic
- Apply text logging format by default (`MCP_LOG_FORMAT=text`)
- Validate all user inputs through Pydantic schemas

**Don'ts:**
- Never use `INSERT OR REPLACE` on sqlite-vec virtual tables (use DELETE + INSERT)
- Never hardcode version numbers or server info in multiple places
- Never bypass the storage backend abstraction layer
- Never use JSON logging in MCP servers without explicit configuration
- Never create direct database connections outside of Database class

## Standards & References

**Code Conventions:**
- Python: Black formatting, type hints mandatory
- Import order: stdlib, third-party, local (absolute imports preferred)
- Async functions: Always use proper error handling and logging

**Git Strategy:**
- Commit format: `type: description` (feat, fix, refactor, docs, test, chore)
- Korean explanations with English technical terms
- Use `git --no-pager` for log viewing commands

**Maintenance Policy:**
규칙과 코드 간 괴리 발견 시 즉시 업데이트를 제안하고 구현하라. 중앙 집중식 관리를 통해 일관성을 유지한다.

## Context Map (Action-Based Routing)

- **[Core Services & Database](./app/core/AGENTS.md)** — 데이터베이스, 임베딩, 비즈니스 로직 서비스 수정 시
- **[MCP Protocol Implementation](./app/mcp_common/AGENTS.md)** — MCP 서버 구현, 프로토콜 호환성 작업 시
- **[Web Dashboard & API](./app/web/AGENTS.md)** — FastAPI 웹 서버, REST API, SSE MCP 엔드포인트 작업 시
- **[MCP Stdio Servers](./app/mcp_stdio/AGENTS.md)** — FastMCP 기반 stdio MCP 서버 작업 시
- **[MCP Pure Implementation](./app/mcp_stdio_pure/AGENTS.md)** — 순수 MCP 프로토콜 구현 작업 시
- **[Frontend UI Components](./static/AGENTS.md)** — 웹 UI, JavaScript 컴포넌트, CSS 스타일링 작업 시
- **[Migration & Scripts](./scripts/AGENTS.md)** — 데이터 마이그레이션, 유틸리티 스크립트 작업 시
- **[Testing & Quality](./tests/AGENTS.md)** — 테스트 코드 작성, 품질 보증 작업 시


# Context Optimization with mem-mesh Pins

## Session Context Management

You have access to mem-mesh MCP tools for managing session context efficiently.

### Session Start (Minimal Context Loading)

When starting a new session or resuming work:

```
Use: mcp_mem_mesh_session_resume
Parameters:
  - project_id: [current-project]
  - expand: false  # Load summary only (~100 tokens)
  - limit: 10

Action: Display session summary (pins_count, open_pins, completed_pins)
Do NOT load full pin contents unless specifically needed.
```

### During Work (Track as Pins) - MANDATORY

**CRITICAL RULE: You MUST create a pin for EVERY task/work item you start.**

When starting ANY task (bug fix, feature, refactor, investigation):

```
MANDATORY: mcp_mem_mesh_pin_add
Parameters:
  - project_id: [current-project]
  - content: [1-line task description]
  - importance: [1-5]
    * 5: Critical feature/architecture
    * 4: Important bug fix/feature
    * 3: Regular task (default)
    * 2: Minor improvement
    * 1: Trivial fix
  - tags: [relevant, technical, keywords]

REQUIRED: Acknowledge pin creation with pin_id in your response.
```

**Importance Guidelines:**
- 5: Architecture decisions, critical features, breaking changes
- 4: Important bugs, significant features, API changes
- 3: Regular tasks, standard bug fixes, refactoring (DEFAULT)
- 2: Minor improvements, documentation updates
- 1: Typo fixes, trivial changes

When task is completed:
```
MANDATORY: mcp_mem_mesh_pin_complete
Parameters:
  - pin_id: [pin-id]

If importance >= 4: MUST suggest promotion to permanent memory.
```

**Enforcement:**
- NO work without pin creation
- ALWAYS report pin_id after creation
- ALWAYS complete pins when work is done
- NEVER skip pin creation for "small" tasks

### Session End (Selective Persistence)

When ending a session:

```
1. Review completed pins
2. For pins with importance >= 4:
   Use: mcp_mem_mesh_pin_promote
   Parameters:
     - pin_id: [pin-id]
   
3. End session:
   Use: mcp_mem_mesh_session_end
   Parameters:
     - project_id: [current-project]
     - summary: [brief session summary]

4. Report promoted memory IDs
```

### Context Retrieval Strategy

**Layered Loading:**
- Level 1 (Always): Session summary only (expand=false)
- Level 2 (On-demand): Full pins when needed (expand=true, limit=5)
- Level 3 (Search): Use mcp_mem_mesh_search for historical context

**Token Budget:**
- Session start: ~100 tokens (summary only)
- Active work: ~50 tokens per pin
- Session end: ~200 tokens (promotion + summary)
- Total: ~350 tokens/session (vs 8000+ without optimization)

### Rules

1. **MANDATORY: Create pin for every task** - NO work without pin_add
2. **Never load full context by default** - Use expand=false for session_resume
3. **Track work incrementally** - Create pins for each significant task
4. **Report pin_id immediately** - Always acknowledge pin creation
5. **Complete pins when done** - Call pin_complete for every finished task
6. **Filter by importance** - Only promote importance >= 4 to permanent memory
7. **Search when needed** - Use mcp_mem_mesh_search instead of loading everything
8. **Clean up sessions** - End sessions properly to maintain context hygiene

### Workflow Enforcement

**Before ANY work:**
```
1. Check if task already has a pin (session_resume)
2. If not, MUST create pin (pin_add)
3. Report pin_id to user
4. Proceed with work
```

**After work completion:**
```
1. MUST call pin_complete
2. If importance >= 4, suggest promotion
3. Report completion status
```

**Violations:**
- Starting work without pin → STOP and create pin first
- Completing work without pin_complete → STOP and complete pin
- Not reporting pin_id → Invalid workflow

### Example Workflow

```
User: "Start working on feature X"
→ session_resume(expand=false) → "Previous session: 3 pins (1 open, 2 completed)"
→ MANDATORY: pin_add(content="Implement feature X", importance=4, project_id="mem-mesh")
→ Report: "Created pin [pin-id-123] for feature X"
→ Proceed with implementation

User: "Feature X done"
→ MANDATORY: pin_complete(pin_id="pin-id-123")
→ Suggest: "Pin completed (importance 4). Promote to memory?"

User: "Yes, end session"
→ pin_promote(pin_id="pin-id-123") → Memory ID: abc123
→ session_end(summary="Feature X implemented")
→ Report: "Session ended. 1 pin promoted to memory (ID: abc123)"

Next session:
User: "What did I do last time?"
→ session_resume(expand=false) → "Last session: Feature X implemented"
→ search_memories(query="feature X") → Detailed context from Memory abc123
```

**Anti-Pattern (WRONG):**
```
User: "Fix the bug"
→ ❌ Start fixing without creating pin
→ ❌ Complete work without pin_complete
→ ❌ No tracking, no context preservation
```

**Correct Pattern:**
```
User: "Fix the bug"
→ ✅ pin_add(content="Fix login validation bug", importance=3)
→ ✅ Report: "Created pin [pin-id-456]"
→ ✅ Fix the bug
→ ✅ pin_complete(pin_id="pin-id-456")
→ ✅ Report: "Pin completed"
```

## Integration Points

- **Session hooks**: Auto-load context on session start
- **Work tracking**: Auto-create pins when tasks begin
- **Session cleanup**: Auto-promote important pins on session end
- **Context search**: Use memory search instead of full history loading

## Benefits

- **95% token reduction**: From ~8000 to ~350 tokens per session
- **Automatic filtering**: Importance-based memory promotion
- **Incremental tracking**: Real-time work progress without context bloat
- **Persistent context**: Important work preserved, trivial work discarded
