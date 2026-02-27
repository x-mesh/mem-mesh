# SSE MCP Transport Layer

> Golden Rules, 세션 관리, 보안 정책, Anti-Patterns 등 프로젝트 공통 표준은 root [AGENTS.md](../../../AGENTS.md) 참조.

## Module Context
Streamable HTTP transport implementation for MCP 2025-03-26. `app.web.mcp.sse` exposes `/mcp/sse` and `/mcp/message` endpoints, dispatches JSON-RPC payloads to `MCPDispatcher`, manages session queues, and optionally emits SSE events back to the client or returns immediate JSON. Session IDs live in `_sessions`, while `_tool_handlers` and `_dispatcher` share the same `MCPToolHandlers` injected from `app.web.lifespan`. Error formatting and schema lookups reuse `mcp_common.transport` and `mcp_common.schemas`.

## Tech Stack & Constraints
- FastAPI `APIRouter` with `sse_starlette.sse.EventSourceResponse` for SSE streams and standard JSON for HTTP clients.
- JSON-RPC 2.0 framing via helpers `format_jsonrpc_response`/`format_jsonrpc_error` + schema discovery from `mcp_common.schemas`.
- `MCPDispatcher` and `MCPToolHandlers` ensure all transports run against the same business logic.
- Sessions require `Mcp-Session-Id` header; Accept header determines SSE vs JSON response (`text/event-stream` vs `application/json`).
- No long-lived blocking operations inside the router; each request is async and respects FastAPI timeouts.

## Implementation Patterns
- `set_tool_handlers` injects a single `MCPToolHandlers` instance and builds the dispatcher once per application lifetime.
- `process_jsonrpc_request` centralizes method dispatch: `initialize` (new session), `tools/list`, `tools/call`, `ping`, and fallback errors.
- SSE stream generator yields an initial `endpoint` discovery event, then listens on the session queue, emitting Server-Sent Events for queued responses while respecting `request.is_disconnected()`.
- POST `/mcp/message` and SSE GET handlers reuse the same JSON-RPC plumbing and optionally return `format_jsonrpc_response` or errors depending on Accept header.

## Testing Strategy
- `python -m pytest tests/test_mcp.py tests/test_sse_mcp.py -v` for protocol compliance and session handling.
- `python -m pytest tests/test_mcp_stdio.py tests/test_mcp_stdio_pure.py` to cover dispatcher reuse across transports.
- End-to-end verification through `static/test-api.js` against `/mcp/sse` when running the web server.

## Local Golden Rules
**Do's:**
- Always honor the Accept header: SSE clients must receive `text/event-stream`, JSON clients default to `application/json`.
- Keep `_sessions` queues aligned with incoming `initialize` calls and clear entries on session completion.
- Reuse `get_dispatcher()` rather than instantiating new dispatchers per request.

**Don'ts:**
- Do not bypass `format_jsonrpc_error`; always reply with JSON-RPC compatible payloads, even on unexpected exceptions.
- Do not send SSE data when the client has disconnected or when the queue is empty for long periods without heartbeats.
- Avoid injecting new storage instances directly into this layer—use the shared `MCPToolHandlers`.
