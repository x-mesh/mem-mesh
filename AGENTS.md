# Agents & MCP Integration

`mem-mesh` is designed to serve as a centralized, persistent memory layer for AI agents. It implements the **Model Context Protocol (MCP)** to expose its capabilities as tools that agents can invoke.

## Overview

The system operates as an **MCP Server**, allowing any MCP-compliant agent (such as Claude Desktop, IDE extensions, or custom agents) to connect and utilize the memory store.

### Connection Method
- **Transport:** Stdio (Standard Input/Output)
- **Protocol Version:** 2024-11-05
- **Commands:**
  - FastMCP 기반: `python -m app.mcp_stdio`
  - Pure MCP 기반: `python -m app.mcp_stdio_pure`
  - Web Dashboard: `python -m app.web --reload`

## Available Tools

Agents connecting to `mem-mesh` have access to the following tools to manage and retrieve information.

### 1. `mem-mesh.add`
Adds a new memory to the system. Agents should use this to store important information, decisions, tasks, or code snippets.

*   **Inputs:**
    *   `content` (string, required): The actual memory content (10-10,000 chars).
    *   `project_id` (string, optional): Identifier for the project this memory relates to.
    *   `category` (string, optional): One of `task`, `bug`, `idea`, `decision`, `incident`, `code_snippet`. Defaults to `task`.
    *   `source` (string, optional): Origin of the memory (defaults to "mcp").
    *   `tags` (array of strings, optional): Keywords for easier filtering.

### 2. `mem-mesh.search`
Performs a hybrid search (Vector + Metadata) to find relevant memories.

*   **Inputs:**
    *   `query` (string, required): The search text.
    *   `project_id` (string, optional): Filter by project.
    *   `category` (string, optional): Filter by category.
    *   `limit` (integer, optional): Max results (default 5).
    *   `recency_weight` (number, optional): 0.0 to 1.0, giving preference to newer memories.

### 3. `mem-mesh.context`
Retrieves the "context" surrounding a specific memory. This is useful for understanding the evolution of a task or related items.

*   **Inputs:**
    *   `memory_id` (string, required): The ID of the focal memory.
    *   `depth` (integer, optional): How far to traverse the relationship graph (default 2).
    *   `project_id` (string, optional): Restrict context to a specific project.

### 4. `mem-mesh.update`
Updates an existing memory.

*   **Inputs:**
    *   `memory_id` (string, required): ID of the memory to update.
    *   `content` (string, optional): New content.
    *   `category` (string, optional): New category.
    *   `tags` (array of strings, optional): New tags.

### 5. `mem-mesh.delete`
Permanently removes a memory.

*   **Inputs:**
    *   `memory_id` (string, required): ID of the memory to delete.

### 6. `mem-mesh.stats`
Retrieves statistical data about the memory store, useful for agents to get a high-level overview.

*   **Inputs:**
    *   `project_id` (string, optional): Filter stats by project.
    *   `start_date` / `end_date` (string, optional): Date range (YYYY-MM-DD).
    *   `group_by` (string, optional): Grouping method (`overall`, `project`, `category`, `source`).

## Agent Workflows

### Storing Context
When an agent completes a significant task or makes a design decision, it should use `mem-mesh.add` to persist this context.

```json
{
  "name": "mem-mesh.add",
  "arguments": {
    "content": "Decided to use SQLite with sqlite-vec for the backend database to support vector search without external dependencies.",
    "category": "decision",
    "project_id": "mem-mesh-core",
    "tags": ["architecture", "database"]
  }
}
```

### Retrieving Information
Before starting a task, an agent can search for relevant past memories to avoid duplication or regression.

```json
{
  "name": "mem-mesh.search",
  "arguments": {
    "query": "vector search implementation details",
    "project_id": "mem-mesh-core",
    "limit": 3
  }
}
```

### Project Onboarding
An agent can use `mem-mesh.stats` and broad searches to quickly "read up" on a project's history and current status.
