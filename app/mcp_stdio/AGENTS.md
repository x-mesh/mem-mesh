# FastMCP stdio MCP Server

## Module Context
FastMCP-based stdio server (`app.mcp_stdio.server`) is the entry point for the default mem-mesh MCP transport. It initializes logging, storage, tool handlers, and batch operations, then registers FastMCP tools (`add`, `search`, `context`, `update`, `delete`, `stats`, `batch_add_memories`, etc.) that delegate to `MCPToolHandlers`. Storage lifecycle is managed via `StorageManager`, embedding/search services, and `BatchOperationHandler` so MCP operations stay consistent with the rest of the platform.

## Tech Stack & Constraints
- `fastmcp.FastMCP` for tool registration and JSON-RPC handling; each tool function is decorated with `@mcp.tool()`.
- Shared storage modules (`mcp_common.storage`, `mcp_common.tools`, `mcp_common.batch_tools`) provide cohesive MCP tool logic and batch mutation helpers.
- Logging respects `MCP_LOG_*` environment variables; asynchronous initialization is mandatory before any tool call occurs.
- Caching and metrics (via `CacheManager`) hook into services used by `BatchOperationHandler` for batch procedures.

## Implementation Patterns
- `initialize_storage` loads settings, calls `storage_manager.initialize`, builds `MCPToolHandlers`, creates `Database`, embedding/search/memory services, and wires `BatchOperationHandler`.
- Each tool function simply calls `_get_handlers()` (ensuring initialization) and delegates to shared service logic; there is no business logic inside tool definitions.
- Batch operations rely on `BatchOperationHandler.batch_operations` to reduce repeated embedding calls and to keep `Database` operations atomic.
- `shutdown_storage` gracefully tears down the storage backend to avoid dangling connections when the FastMCP loop exits.

## Testing Strategy
- `python -m pytest tests/test_mcp_stdio.py tests/test_mcp_tools.py -v` for FastMCP server behavior and tool handler correctness.
- `python -m pytest tests/test_mcp.py tests/test_mcp_stdio_pure.py -v` to cover protocol compliance across transports.
- Use `scripts/debug_mcp_sse_search.py` or `static/test-api.js` against a running FastMCP server to check live tool responses.

## Local Golden Rules
**Do's:**
- Ensure `initialize_storage` completes before allowing tool handlers to be called; guard with `_get_handlers()` that raises if `tool_handlers` is None.
- Keep tools as thin wrappers; delegate validation, storage access, and response formatting to `mcp_common` modules.
- Leverage `BatchOperationHandler` to keep multi-memory writes consistent with embedding service constraints.

**Don'ts:**
- Do not mutate global handler references directly or bypass `storage_manager.shutdown()` during teardown.
- Never add business logic to the tool decorator functions—put it inside `MCPToolHandlers` or supporting services.
- Avoid synchronous blocking operations inside tool handlers—FastMCP expects async callables.
