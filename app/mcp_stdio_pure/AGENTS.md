# Pure MCP stdio Implementation

> Golden Rules, 세션 관리, 보안 정책, Anti-Patterns 등 프로젝트 공통 표준은 root [AGENTS.md](../../AGENTS.md) 참조.

## Module Context
`app.mcp_stdio_pure.server` is the fallback stdio transport that implements the Model Context Protocol directly instead of relying on FastMCP. It reads NDJSON from stdin, parses JSON-RPC 2.0 requests, dispatches them through `MCPDispatcher`, and writes responses to stdout. Shared services (`StorageManager`, `MCPToolHandlers`, `BatchOperationHandler`, metrics, and embedding services) are wired via `initialize_storage`, ensuring parity with other transports.

## Tech Stack & Constraints
- `asyncio.StreamReader`/`StreamReaderProtocol` for non-blocking stdin, `json` for serialization, `signal` handlers for graceful shutdown.
- Protocol helpers (`format_tool_error`, `MCPDispatcher`) live in `mcp_common` to avoid duplicated serialization logic.
- Logging is centralized via `setup_logging`, and every response adheres to JSON-RPC 2.0 (even errors).
- Batch operations and caching rely on `BatchOperationHandler` to reuse embedding/search services already instantiated for the Transport.

## Implementation Patterns
- `read_line_async` → `parse_message` → `process_jsonrpc_request` is the canonical pipeline; errors always route through `write_error`.
- `initialize_storage` boots storage, tool handlers, dispatcher, batch handler, and background tasks so the pure server can respond to tools without per-request initialization.
- Batch tool handling (`batch_operations`) is delegated to `BatchOperationHandler` while returning the textual result for easier debugging.
- Signal handlers (`SIGTERM`, `SIGINT`) flip an asyncio Event to orchestrate a graceful loop shutdown.

## Testing Strategy
- `python -m pytest tests/test_mcp_stdio_pure.py tests/test_mcp.py tests/test_mcp_tools.py -v` for JSON-RPC compliance and dispatcher reuse.
- `python -m pytest tests/test_mcp_stdio.py` ensures the FastMCP and pure transports remain behaviorally equivalent.
- Manual invocation via `python -m app.mcp_stdio_pure` + `static/test-api.js` allows live verification of NDJSON responses.

## Local Golden Rules
**Do's:**
- Keep every outbound message in strict JSON-RPC 2.0 format (use `write_result`/`write_error`).
- Use the shared `MCPDispatcher` so that service logic remains centralized.
- Drain `_stdin_reader` via `read_line_async` and re-queue `None` on EOF to trigger shutdown.

**Don'ts:**
- Do not perform synchronous blocking operations while waiting on stdin; use asyncio primitives.
- Do not raise uncaught exceptions—always log and convert them into JSON-RPC errors to keep clients stable.
- Never bypass `initialize_storage`; the dispatcher and batch handler assume `tool_handlers` is ready.
