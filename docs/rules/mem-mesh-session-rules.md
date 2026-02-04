# mem-mesh Session Rules

## Session Lifecycle

```
session_resume → pin_add → [work] → pin_complete → (promote) → session_end
```

### 1. Session Start
```
mcp_mem_mesh_session_resume(project_id="<project>", expand=false, limit=10)
```
Report: `pins_count`, `open_pins`, `completed_pins`

**Token Optimization:**
- `expand=false`: Summary only (no pin content) - saves ~90% tokens
- `expand=true`: Full pin content loaded
- Response includes `token_info`: `loaded_tokens`, `unloaded_tokens`, `estimated_total`

### 2. Task Start
```
mcp_mem_mesh_pin_add(content="<description>", project_id="<project>", importance=3, tags=[...])
```
- `3`: normal, `4`: important, `5`: architecture
- Wait for `pin_id` before proceeding

### 3. Task Complete
```
mcp_mem_mesh_pin_complete(pin_id="<pin_id>")
```
If importance ≥ 4: `mcp_mem_mesh_pin_promote(pin_id)`

### 4. Session End
```
mcp_mem_mesh_session_end(project_id="<project>")
```

---

## Core Tools

| Tool | Purpose | Required |
|------|---------|----------|
| `add` | Save memory | `content` |
| `search` | Find memories | `query` |
| `batch_operations` | Batch add/search (30-50% token savings) | `operations` |
| `link` | Create relation | `source_id`, `target_id` |
| `stats` | Get statistics | - |

---

## Search Patterns

```python
# Recent memories
search(query="", limit=5)

# Project filter
search(query="bug", project_id="my-app")

# Recency boost
search(query="auth", recency_weight=0.3)

# Category filter
search(query="", category="decision")
```

---

## Batch Operations

```python
batch_operations(operations=[
  {"type": "add", "content": "...", "project_id": "...", "category": "task"},
  {"type": "search", "query": "...", "limit": 5}
])
```

---

## Memory Relations

```python
# Create relation
link(source_id="<id>", target_id="<id>", relation_type="related")

# Get relations
get_links(memory_id="<id>")
```

Types: `related` | `parent` | `child` | `supersedes` | `references` | `depends_on` | `similar`

---

## Categories

`task` | `bug` | `idea` | `decision` | `incident` | `code_snippet` | `git-history`
