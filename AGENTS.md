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
