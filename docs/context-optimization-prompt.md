# Context Optimization with mem-mesh Pins

## Session Context Management

You have access to mem-mesh MCP tools for managing session context efficiently.

### Session Start (Minimal Context Loading)

When starting a new session or resuming work:

```
Use: mcp_mem_mesh_session_resume
Parameters:
  - project_id: [current-project]
  - expand: false  # Load summary only (~100 tokens)
  - limit: 10

Action: Display session summary (pins_count, open_pins, completed_pins)
Do NOT load full pin contents unless specifically needed.
```

### During Work (Track as Pins)

When starting a new task:

```
Use: mcp_mem_mesh_pin_add
Parameters:
  - project_id: [current-project]
  - content: [1-line task description]
  - importance: [1-5]
    * 5: Critical feature/architecture
    * 4: Important bug fix/feature
    * 3: Regular task
    * 2: Minor improvement
    * 1: Trivial fix
  - tags: [relevant, technical, keywords]

When task is completed:
Use: mcp_mem_mesh_pin_complete
Parameters:
  - pin_id: [pin-id]

If importance >= 4, suggest promotion to permanent memory.
```

### Session End (Selective Persistence)

When ending a session:

```
1. Review completed pins
2. For pins with importance >= 4:
   Use: mcp_mem_mesh_pin_promote
   Parameters:
     - pin_id: [pin-id]
   
3. End session:
   Use: mcp_mem_mesh_session_end
   Parameters:
     - project_id: [current-project]
     - summary: [brief session summary]

4. Report promoted memory IDs
```

### Context Retrieval Strategy

**Layered Loading:**
- Level 1 (Always): Session summary only (expand=false)
- Level 2 (On-demand): Full pins when needed (expand=true, limit=5)
- Level 3 (Search): Use mcp_mem_mesh_search for historical context

**Token Budget:**
- Session start: ~100 tokens (summary only)
- Active work: ~50 tokens per pin
- Session end: ~200 tokens (promotion + summary)
- Total: ~350 tokens/session (vs 8000+ without optimization)

### Rules

1. **Never load full context by default** - Use expand=false for session_resume
2. **Track work incrementally** - Create pins for each significant task
3. **Filter by importance** - Only promote importance >= 4 to permanent memory
4. **Search when needed** - Use mcp_mem_mesh_search instead of loading everything
5. **Clean up sessions** - End sessions properly to maintain context hygiene

### Example Workflow

```
User: "Start working on feature X"
→ session_resume(expand=false) → "Previous session: 3 pins (1 open, 2 completed)"
→ pin_add(content="Implement feature X", importance=4)

User: "Feature X done"
→ pin_complete(pin_id)
→ Suggest: "Pin completed (importance 4). Promote to memory?"

User: "Yes, end session"
→ pin_promote(pin_id) → Memory ID: abc123
→ session_end(summary="Feature X implemented")
→ Report: "Session ended. 1 pin promoted to memory (ID: abc123)"

Next session:
User: "What did I do last time?"
→ session_resume(expand=false) → "Last session: Feature X implemented"
→ search_memories(query="feature X") → Detailed context from Memory abc123
```

## Integration Points

- **Session hooks**: Auto-load context on session start
- **Work tracking**: Auto-create pins when tasks begin
- **Session cleanup**: Auto-promote important pins on session end
- **Context search**: Use memory search instead of full history loading

## Benefits

- **95% token reduction**: From ~8000 to ~350 tokens per session
- **Automatic filtering**: Importance-based memory promotion
- **Incremental tracking**: Real-time work progress without context bloat
- **Persistent context**: Important work preserved, trivial work discarded
