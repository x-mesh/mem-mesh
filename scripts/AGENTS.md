# Migration & Utility Scripts

> Golden Rules, 세션 관리, 보안 정책, Anti-Patterns 등 프로젝트 공통 표준은 root [AGENTS.md](../AGENTS.md) 참조.

## Module Context
The `scripts/` directory contains Python entry points for migrations (`migrate_embeddings.py`, `migrate_monitoring_tables.py`, etc.), debugging helpers (`debug_mcp_sse_search.py`, `debug_summarization.py`), import/export utilities, benchmarks, and verification tooling. Each script typically initializes the same `Settings`, `Database`, and embedding services as the main app so that migrations and diagnostics operate on a consistent environment.

## Tech Stack & Constraints
- Plain Python CLI modules (mostly argparse/typer style); no third-party CLI frameworks beyond standard libs and `httpx` for MCP/SSE clients.
- Scripts share `app.core.config.Settings`, `Settings.database_path`, and the storage backend; respect `MEM_MESH_*` env vars just like the main server.
- Embedding-related scripts must avoid writing to sqlite-vec virtual tables with `INSERT OR REPLACE`; run in `dry-run` mode first.
- Debugging scripts (`debug_mcp_sse_search.py`, `debug_mcp_sse_search.py`) target MCP/SSE endpoints and assume the HTTP server is running.

## Implementation Patterns
- Most scripts expose `main()` that constructs services (`Database`, `EmbeddingService`, `DirectStorageBackend`), parses CLI args (`--project`, `--category`, `--check-only`, `--dry-run`), and calls shared helpers from `app.core` or `app.mcp_common`.
- Migration scripts use `scripts/migrate_embeddings.py --check-only` to inspect differences before `--dry-run` or full runs; they log summaries of vector counts, affected models, and recommended actions.
- Debug helpers call MCP SSE endpoints using `httpx.AsyncClient`/`sync Client` wrappers, print requests/responses, and enforce minimal input validation (content length, query length).
- Utilities like `scripts/verify_db_consistency.py` or `scripts/verify_embeddings.py` focus on data integrity checks and do not mutate the database unless `--fix` is explicitly requested.

## Testing Strategy
- `python scripts/migrate_embeddings.py --check-only` to validate schema assumptions and spot missing migrations.
- `python scripts/migrate_embeddings.py --dry-run` after checks to preview updates without persisting changes.
- `python scripts/debug_mcp_sse_search.py search --project mem-mesh --limit 5` for MCP/SSE regression tests; repeat for `add` and `stats` commands as needed.
- `python scripts/verify_db_consistency.py` and `python scripts/verify_embeddings.py` to assert metadata alignment before running migrations or imports.

## Local Golden Rules
**Do's:**
- Always run `--check-only` for migrations before any writes, and prefer `--dry-run` when exploring new flags.
- Keep script arguments explicit (`--project mem-mesh`, `--category bug`) to avoid accidental global changes.
- Share storage backends and services with the core app where possible, so that migrations reflect runtime behavior.

**Don'ts:**
- Do not hardcode API URLs, embedded models, or database paths inside scripts; rely on `Settings`/env vars.
- Do not run scripts like `sync_memories` or `import_kiro_chat.py` against production databases without taking a backup.
- Do not bypass validation rules (content length, query min length); these exist upstream in the MCP tools and should be mirrored here.
