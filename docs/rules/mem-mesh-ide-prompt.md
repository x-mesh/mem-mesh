# mem-mesh IDE Prompt (Compact)

Copy this to your IDE's system prompt or rules file.

---

```
## mem-mesh MCP Memory System

You have access to mem-mesh for persistent context across sessions.

### AUTO PROJECT
Detect from current directory: /path/to/PROJECT → project_id="PROJECT"

### TOOLS
- search(query, project_id, limit=5) - Find memories
- add(content, category, project_id, tags) - Save memory
- session_resume(project_id, expand=false) - Load session
- pin_add(content, project_id, importance) - Track task
- pin_complete(pin_id) - Complete task

### WORKFLOW
1. Session start: session_resume(project_id="$DIR", expand=false)
2. Track work: pin_add(content="task", project_id="$DIR", importance=3)
3. Save knowledge: add(content="Q: ...\nA: ...", category="decision", project_id="$DIR")
4. Search: search(query="specific phrase", project_id="$DIR", limit=5)

### RULES
- Query: Use phrases ("token optimization"), not words ("token")
- Save: Q&A format, 3-5 tags, appropriate category
- Categories: task | bug | idea | decision | code_snippet

### SKILLS
Use @mem-mesh/skill-name for complex workflows:
- @mem-mesh/session-start - Initialize with context
- @mem-mesh/save-qa - Format and save Q&A
- @mem-mesh/search-context - Smart search
```

---

## Kiro/Cursor Rules File Version

For `.kiro/steering/mem-mesh.md` or `.cursorrules`:

```markdown
# mem-mesh Memory Integration

## When to Use
- Starting work: Call session_resume to load context
- Learning something: Save with add() in Q&A format
- Need past context: Search with specific phrases
- Tracking tasks: Use pin_add/pin_complete

## Project Detection
Current directory name = project_id
Example: ~/work/my-app → project_id="my-app"

## Quick Reference
| Action | Tool | Example |
|--------|------|---------|
| Load context | session_resume | `(project_id="my-app", expand=false)` |
| Save memory | add | `(content="Q:..A:..", category="decision")` |
| Find memory | search | `(query="auth flow", limit=5)` |
| Track task | pin_add | `(content="implement X", importance=3)` |

## Format for Saving
```
Q: [Clear question]

A: [Detailed answer]
- Key point 1
- Key point 2
- Code: `example`
```

Tags: 3-5 relevant keywords (kebab-case)
Categories: task, bug, idea, decision, code_snippet
```
