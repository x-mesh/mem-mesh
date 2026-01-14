# mem-mesh Context Optimization (Compact)

## Core Principle
Use Pins for session context, Memories for permanent storage. Load summaries by default, details on-demand.

## Commands

### Session Start
```
mcp_mem_mesh_session_resume(project_id, expand=false, limit=10)
→ Show: pins_count, open_pins, completed_pins only
```

### Track Work
```
mcp_mem_mesh_pin_add(project_id, content, importance=1-5, tags)
→ importance: 5=critical, 4=important, 3=regular, 2=minor, 1=trivial

mcp_mem_mesh_pin_complete(pin_id)
→ If importance >= 4: suggest promotion
```

### Session End
```
mcp_mem_mesh_pin_promote(pin_id)  # For importance >= 4
mcp_mem_mesh_session_end(project_id, summary)
```

## Rules
1. **expand=false by default** - Load summaries, not full content
2. **Track incrementally** - Pin each task as you work
3. **Promote selectively** - Only importance >= 4 → Memory
4. **Search, don't load** - Use mcp_mem_mesh_search for history

## Token Budget
- Session start: ~100 tokens (vs 2000+)
- Active work: ~50 tokens/pin (vs 5000+)
- Session end: ~200 tokens (vs 1000+)
- **Total: ~350 tokens/session (95% reduction)**

## Workflow
```
Start → session_resume(expand=false)
Work → pin_add(importance=4)
Done → pin_complete → pin_promote (if important)
End → session_end(summary)
Next → session_resume → search_memories (for details)
```
