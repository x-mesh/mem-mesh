# Web API & Dashboard Layer

## Module Context
FastAPI application (`app.web.app`) assembles middleware, routers, and lifecycle hooks for the dashboard, monitoring, SSE MCP, and WebSocket transports. `lifespan` orchestrates Settings, Database, embedding/search services, metrics collector, MCP SSE storage, MCP tool handlers, and project/session/pin services. `common.dependencies` exposes service providers, while `websocket.realtime` and `monitoring.routes` publish real-time notifications and observability APIs. Static files and templates serve the single-page application assets alongside the API endpoints.

## Tech Stack & Constraints
- FastAPI + Uvicorn (ASGI) with Jinja2 templates and StaticFiles mount.
- SSE transport powered by `sse_starlette` and MCP dispatchers; WebSocket notifier for live updates.
- Configuration by `dotenv` + `app.core.config.Settings`, direct SQLite backend via `DirectStorageBackend`, strict use of `sentence-transformers` for embeddings.
- Dependencies resolved through `common.dependencies`/lifespan helpers; no direct database connections from routers.
- Templates and static assets live in `templates/` and `static/`; keep caching disabled during development via `NoCacheStaticMiddleware`.

## Implementation Patterns
- Use the `create_app()` factory so routers, middleware (`setup_middleware`), and exception handlers (`setup_exception_handlers`) install deterministically before returning the `FastAPI` object.
- Inject services through `Depends` helpers (e.g., `get_memory_service`) so MC services share the same lifespan-managed instances.
- Mount `/static`, then register routers in this order: WebSocket → MCP SSE → Monitoring → Dashboard API → Dashboard pages (catch-all last) to avoid route conflicts.
- Lifespan hook initializes logging, database connection, services, metrics collector, MCP storage, and MCP SSE handler wiring before yielding control, and it tears down metrics, MCP storage, and DB on shutdown.

## Testing Strategy
- `python -m pytest tests/test_fastapi_app.py tests/test_monitoring_api.py tests/test_mcp.py -v` for API, monitoring, and MCP surface coverage.
- `python -m pytest tests/test_mcp_stdio.py tests/test_mcp_stdio_pure.py tests/test_mcp_tools.py -v` to validate tool handlers and stdio transports.
- Manual/visual smoke checks via `static/test-api.js` and `tests/test_web_ui.html` while servicing the UI assets.

## Local Golden Rules
**Do's:**
- Keep all API handlers async and return Pydantic models + FastAPI Response objects.
- Raise HTTPExceptions when dependencies fail instead of letting service initialization leaks surface.
- Reuse the MCP tool dispatcher when exposing SSE endpoints; share the logger context and `MCPToolHandlers`.
- Document new routes in the dashboard AGENT (`./dashboard/AGENTS.md`) and add OpenAPI descriptions or tags.

**Don'ts:**
- Do not open database connections inside route functions or middlewares—always go through lifespan-managed services.
- Do not duplicate exception handlers; extend `setup_exception_handlers` if new error types are needed.
- Do not reorder routers without validating static/page fallthrough behavior.
- Do not mutate `app.state` outside of controlled initialization functions.
