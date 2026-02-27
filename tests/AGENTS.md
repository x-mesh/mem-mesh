# Testing & Quality Layer

> Golden Rules, 세션 관리, 보안 정책, Anti-Patterns 등 프로젝트 공통 표준은 root [AGENTS.md](../AGENTS.md) 참조.

## Module Context
The `tests/` suite covers the mem-mesh memory services, search, metrics, MCP transports, API, CLI tooling, and UI helpers. It includes unit test modules (e.g., `test_memory_service.py`, `test_search_service.py`, `test_metrics_collector.py`), integration suites (`test_fastapi_app.py`, `test_mcp.py`, `test_mcp_stdio.py`, `test_mcp_stdio_pure.py`), and browser/HTML artifacts (`test_web_ui.html`, `test_web_ui`-related fixtures) for manual QA.

## Tech Stack & Constraints
- Pytest-driven tests with `httpx.AsyncClient`/`TestClient` for FastAPI endpoints, plus direct invocations of `StorageManager`/`Database` for service-level validation.
- Tests expect a clean sqlite database for each run; many rely on `tests/test_*` modules to manage temporary files under `/tmp` or the project root. No external vector engines are used, so sqlite-vec constraints apply even in tests.
- Some suites load `mcp_common` dispatchers and `app.web.app` to validate serialization, so ensure environment variables (`MEM_MESH_LOG_LEVEL`, `MEM_MESH_STORAGE_MODE`) match expected defaults.

## Implementation Patterns
- Favor fixture-based initialization (database, embedding services, MCP tool handlers) so tests stay isolated and deterministic.
- High-level integration tests spin up the FastAPI app or MCP server in-process, then exercise endpoints via `TestClient` or `fastmcp.FastMCP`.
- Use `pytest.mark.asyncio` for async services and `assert` statements that check both result schemas and database side effects.
- UI-focused tests (`tests/test_web_ui.html`, `test-search.html`) are meant for manual validation but can be loaded inside browsers that mimic user flows.

## Testing Strategy
- Run `python -m pytest tests/test_fastapi_app.py tests/test_mcp.py tests/test_web_ui.html -v` for API/MCP coverage plus UI sanity.
- Run `python -m pytest tests/test_mcp_stdio.py tests/test_mcp_stdio_pure.py tests/test_mcp_tools.py -v` to guard the transports and shared tools.
- Include `python -m pytest tests/test_memory_service.py tests/test_search_service.py tests/test_monitoring_api.py` whenever sensor metrics or search logic changes.
- For manual verification, open `tests/test_web_ui.html` or `static/test-search.html` against the running dashboard to confirm the front-end piped data.

## Local Golden Rules
**Do's:**
- Keep tests independent by resetting the sqlite database between cases; use fixtures that drop/recreate tables when needed.
- Reuse shared helpers (e.g., `tests/test_mcp_tools.py` utilities) instead of duplicating storage/service initialization logic.
- Document why a test exists when it covers a non-obvious regression (MCP transports, embedding migrations, analytics).

**Don'ts:**
- Don't hardcode absolute filesystem paths; prefer `tmp_path`/`tmp_path_factory` or environment-configured `Settings`.
- Avoid writing long-running or flaky tests; split them if they rely on external timing (e.g., SSE heartbeats).
- Do not mutate production databases during tests—always point to a temporary or in-memory sqlite file.
