# mem-mesh Examples

Integration examples for popular AI coding tools.

## Setup Methods

| Method | Transport | Use Case |
|--------|-----------|----------|
| [Stdio](#stdio-local) | stdin/stdout | Local IDE integration (recommended) |
| [HTTP/SSE](#httpsse-remote) | Streamable HTTP | Remote/shared server, web dashboard |

---

## Stdio (Local)

### Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio"],
      "cwd": "/path/to/mem-mesh",
      "env": {
        "MCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

Or install globally via PyPI:

```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "mem-mesh-mcp-stdio"
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio"],
      "cwd": "/path/to/mem-mesh"
    }
  }
}
```

### Kiro

Add to `~/.kiro/settings/mcp.json`:

```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio"],
      "cwd": "/path/to/mem-mesh"
    }
  }
}
```

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "mem-mesh": {
      "command": "python",
      "args": ["-m", "app.mcp_stdio"],
      "cwd": "/path/to/mem-mesh"
    }
  }
}
```

---

## HTTP/SSE (Remote)

Start the server:

```bash
python -m app.web --host 0.0.0.0 --port 8000
```

### Claude Code (SSE)

```json
{
  "mcpServers": {
    "mem-mesh": {
      "type": "sse",
      "url": "http://localhost:8000/mcp/sse"
    }
  }
}
```

### Cursor (SSE)

```json
{
  "mcpServers": {
    "mem-mesh": {
      "url": "http://localhost:8000/mcp/sse"
    }
  }
}
```

### Docker

```bash
docker compose up -d
# Server available at http://localhost:8000
# SSE endpoint: http://localhost:8000/mcp/sse
# Web dashboard: http://localhost:8000
```

---

## Auto-Install Hooks

mem-mesh provides a CLI to auto-install session hooks for supported editors:

```bash
# Install hooks for Claude Code, Cursor, and Kiro
mem-mesh-hooks install

# Check current hook status
mem-mesh-hooks status

# Uninstall hooks
mem-mesh-hooks uninstall
```

Hooks auto-inject `session_resume` on conversation start and `session_end` on conversation end.

---

## Typical Agent Workflow

```
Session Start
  └─ session_resume(project_id="my-project", expand="smart")
      → Restores active pins and previous context

During Work
  ├─ pin_add(content="Implement auth middleware", project_id="my-project")
  ├─ search(query="auth decision", project_id="my-project")
  ├─ add(content="Chose JWT over session cookies because...", category="decision")
  ├─ pin_complete(pin_id="...", promote=true, category="decision")
  └─ batch_operations(operations=[...])  # 30-50% token savings

Session End
  └─ session_end(project_id="my-project", summary="Implemented auth middleware")
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_PATH` | SQLite database path | `./data/memories.db` |
| `LOG_LEVEL` | Log level | `INFO` |
| `MCP_LOG_LEVEL` | MCP-specific log level | `INFO` |
| `MEM_MESH_CLIENT` | Client name (stdio mode) | auto-detected |
| `MEM_MESH_SERVER_HOST` | HTTP server host | `127.0.0.1` |
| `MEM_MESH_SERVER_PORT` | HTTP server port | `8000` |
