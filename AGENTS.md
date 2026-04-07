<!-- English version — see AGENTS.ko.md for Korean -->

# mem-mesh: AI Memory Management System

## Project Context & Operations
**Business Goal:** Provide a centralized memory server that enables AI tools to store and coordinate memories in real-time using vector search and context retrieval.
**Tech Stack:** Python 3.9+, FastAPI, FastMCP, sqlite-vec, sentence-transformers, MCP Protocol 2024-11-05/2025-03-26 transports.
**Operational Commands:**
```bash
# Development
python -m app.web --reload              # FastAPI + SSE MCP dashboard
python -m app.mcp_stdio                 # FastMCP-based stdio MCP server
python -m app.mcp_stdio_pure            # Pure MCP stdio server

# Testing
python -m pytest tests/                 # Run all tests
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
- Use `git --no-pager` variants (`git --no-pager log`, `git --no-pager status`) when reviewing history.

## Workflow
**Thinking Process (CoT)**

Before generating code or executing commands, perform a brief <Thinking> step:
1. Identify Intent: What is the user's specific goal? (Feat/Fix/Refactor/Query)
2. Check Context: Which AGENTS.md or module is relevant? (Refer to Context Map)
3. Verify Constraints: Does this action violate any Golden Rules?
4. Plan: Outline the step-by-step execution plan.

**Maintenance Policy:**
When a discrepancy between rules and code is found, immediately submit an improvement proposal and update both this root AGENTS.md and the relevant sub-AGENTS files.

## Context Map (Action-Based Routing)
- **[Core Services & Database](./app/core/AGENTS.md)** — When modifying data, embeddings, or services.
- **[MCP Protocol Implementation](./app/mcp_common/AGENTS.md)** — When working on shared MCP tools, storage, or schemas.
- **[Web API & Dashboard](./app/web/AGENTS.md)** — When modifying FastAPI app, WebSocket, UI routing, or templates.
- **[SSE MCP Transport](./app/web/mcp/AGENTS.md)** — When modifying the Streamable HTTP/SSE MCP transport layer.
- **[FastMCP stdio Server](./app/mcp_stdio/AGENTS.md)** — When working on the FastMCP-based stdio server.
- **[Pure MCP stdio Server](./app/mcp_stdio_pure/AGENTS.md)** — When adjusting direct MCP protocol implementation or dispatcher.
- **[Frontend Static Assets](./static/AGENTS.md)** — When modifying JavaScript/CSS/frontend logic.
- **[Migration & Utility Scripts](./scripts/AGENTS.md)** — When writing or running migration, embedding, QA, or monitoring utilities.
- **[Testing & Quality](./tests/AGENTS.md)** — When updating pytest suites, integration/regression tests, or test utilities.
- **[Web Dashboard Pages](./app/web/dashboard/AGENTS.md)** — When enhancing dashboard routes, page templates, or SSE MCP endpoints.

## Session Context Management

> Detailed implementation guide for the CLAUDE.md Checklist and MUST/SHOULD/MAY rules.

### Session Lifecycle

```
Session Start ──→ Task Tracking ──→ Session End
     │                 │                 │
     ▼                 ▼                 ▼
session_resume     pin_add         Knowledge preservation
     │             pin_complete         │
     │             pin_promote      session_end
     │                 │
     └──── search (past context) ────┘
```

### Session Start
```
mcp_mem_mesh_session_resume(project_id="mem-mesh", expand="smart", limit=10)
```
Report: `pins_count`, `in_progress_pins`, `open_pins`, `completed_pins`

**Stale auto-cleanup:** On `session_resume`, old pins are automatically completed:
- `in_progress` for 7+ days → `completed`
- `open` for 30+ days → `completed`

**Token Optimization — expand modes:**
- `expand="smart"` (recommended): status × importance 4-Tier matrix
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
- If importance is omitted, it is auto-estimated based on content
- Default status: `in_progress` (active). For multi-step tasks, future steps can be created as `open` (planned)
- Response (compact): `{id, importance, status}` — includes `auto_importance: true` when auto-estimated
- Wait for `pin_id` before proceeding

**Client detection:** In HTTP mode, automatically detected from MCP initialize handshake or User-Agent (25+ IDE/AI platforms). In stdio mode, uses the `MEM_MESH_CLIENT` environment variable.

### Task Complete
```
mcp_mem_mesh_pin_complete(pin_id="<pin_id>")
```
If importance ≥ 4: `mcp_mem_mesh_pin_promote(pin_id)`

### Session End & Knowledge Preservation
```
mcp_mem_mesh_session_end(project_id="mem-mesh")
```

**Knowledge preservation criteria at session end:**

| Event during session | How to save | Example |
|---------------------|-------------|---------|
| Architecture decision agreed | `add(category="decision")` | "SQLite + sqlite-vec confirmed as sole vector store" |
| Complex bug resolved | `add(category="bug")` | "sqlite-vec INSERT OR REPLACE prohibited — use DELETE+INSERT" |
| System incident recovered | `add(category="incident")` | "Port 8000 conflict caused duplicate server startup" |
| Improvement idea | `add(category="idea")` | "Consider E5 prefix encoding for Korean search" |
| Reusable pattern discovered | `add(category="code_snippet")` | batch_operations usage pattern |
| Task tracked via Pin | `pin_complete` + optionally `pin_promote` | — |

**Do NOT save**: simple Q&A, file reads, repeated content already stored, all code change records.
Always include the **reason for the change (WHY)** when saving.

### Security — Sensitive Information Policy

Never store the following in memories (`add`, `pin_add`):
- API keys, tokens, secrets, passwords
- Personally identifiable information (PII): emails, phone numbers, national IDs
- `.env` file contents, authentication credentials
- When saving code snippets, replace sensitive values with `<REDACTED>`

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

### Anti-Patterns (Avoid These)
- Hook-based auto-save — causes 63.4% truncation via byte cutting, 20-30% search pollution
- Recording all file changes to memory — wastes search slots
- Saving session summaries via `head -c` truncation — breaks UTF-8 encoding
- Saving code snippets without context — meaningless later without WHY
