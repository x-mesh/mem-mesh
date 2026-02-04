# mem-mesh MCP Integration Guide

## Quick Start

mem-mesh provides persistent memory for AI agents via MCP protocol.

### Project Detection
Project ID is auto-detected from current directory:
- `/Users/jinwoo/work/project/my-app` → `my-app`
- Override: `project_id="custom-project"`

### Core Tools

| Tool | Purpose | Example |
|------|---------|---------|
| `search` | Find memories | `search(query="auth flow", project_id="my-app")` |
| `add` | Save memory | `add(content="...", category="decision", project_id="my-app")` |
| `session_resume` | Load session context | `session_resume(project_id="my-app", expand=false)` |
| `pin_add` | Track current task | `pin_add(content="...", project_id="my-app", importance=3)` |
| `pin_complete` | Mark task done | `pin_complete(pin_id="...")` |

### Categories
`task` | `bug` | `idea` | `decision` | `incident` | `code_snippet` | `git-history`

---

## IDE System Prompt (Copy This)

```
You have access to mem-mesh MCP for persistent memory.

## PROJECT DETECTION
Auto-detect from current directory name. Example:
- Directory: /path/to/my-app → project_id="my-app"

## SESSION WORKFLOW
1. Start: session_resume(project_id="$PROJECT", expand=false, limit=10)
2. Task: pin_add(content="task description", project_id="$PROJECT", importance=3)
3. Done: pin_complete(pin_id="...")
4. End: session_end(project_id="$PROJECT")

## SEARCH RULES
- Use phrases, not single words: ✅ "token optimization" ❌ "token"
- Always include project_id for relevance
- Limit results: limit=5 (default)

## SAVE RULES
- Include Q&A format for searchability
- Add relevant tags (3-5, kebab-case)
- Choose appropriate category

## SKILLS (Optional)
For complex workflows, use skills:
- @mem-mesh/session-start - Initialize session
- @mem-mesh/save-qa - Save Q&A pair
- @mem-mesh/search-context - Search with context
```

---

## Skills Reference

### @mem-mesh/session-start
```yaml
trigger: "start session" | "resume work"
action: |
  1. Detect project from current directory
  2. Call session_resume(project_id=$PROJECT, expand=false, limit=10)
  3. Report: pins_count, open_pins, completed_pins
```

### @mem-mesh/save-qa
```yaml
trigger: "save this" | "remember this"
action: |
  1. Format as Q&A structure
  2. Extract tags from content
  3. Call add(content=formatted, category=auto, project_id=$PROJECT, tags=[...])
```

### @mem-mesh/search-context
```yaml
trigger: "find" | "search" | "what did we"
action: |
  1. Expand single-word queries to phrases
  2. Call search(query=expanded, project_id=$PROJECT, limit=5)
  3. Format results with relevance scores
```

### @mem-mesh/task-track
```yaml
trigger: "working on" | "starting task"
action: |
  1. Create pin: pin_add(content=description, project_id=$PROJECT, importance=3)
  2. On completion: pin_complete(pin_id=...)
  3. If important (≥4): pin_promote(pin_id=...)
```

---

## Web UI Features

### Rules Manager
Access at: `http://your-server/dashboard/rules`
- View/edit project rules
- Manage steering files
- Export rules for IDE integration

### Memory Dashboard
Access at: `http://your-server/dashboard`
- Browse memories by project
- Search with filters
- View session history

---

## Best Practices

### Search Optimization
```python
# ✅ Good - specific phrase with project
search("authentication flow implementation", project_id="my-app", limit=5)

# ❌ Bad - single word, no project
search("auth")
```

### Memory Structure
```python
add(
    content="""
Q: How to implement JWT authentication?

A: Use python-jose library with FastAPI
- Install: pip install python-jose[cryptography]
- Create token: jwt.encode(payload, SECRET_KEY, algorithm="HS256")
- Verify: jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
""",
    category="code_snippet",
    project_id="my-app",
    tags=["jwt", "authentication", "fastapi", "security"]
)
```

### Session Management
```python
# Start of work
ctx = session_resume(project_id="my-app", expand=false, limit=10)
# → Returns: pins_count, open_pins, summary (token-optimized)

# Track task
pin = pin_add(content="Implement user login", project_id="my-app", importance=4)

# Complete task
pin_complete(pin_id=pin["id"])

# Important task → promote to permanent memory
pin_promote(pin_id=pin["id"])

# End session
session_end(project_id="my-app")
```

---

## Token Optimization

| Mode | Tokens | Use Case |
|------|--------|----------|
| `expand=false` | ~50 | Quick context check |
| `expand=true` | ~500+ | Full task details needed |
| `batch_operations` | -30~50% | Multiple operations |

### Batch Example
```python
batch_operations(operations=[
    {"type": "add", "content": "...", "project_id": "my-app", "category": "task"},
    {"type": "search", "query": "related work", "limit": 3}
])
```
