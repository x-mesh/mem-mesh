# IDE Global Rule: mem-mesh Context Management

## Automatic Context Optimization

When mem-mesh MCP tools are available, use Pins for session context management.

### Session Lifecycle

**On Session Start:**
```python
# Load minimal context (summary only)
context = mcp_mem_mesh_session_resume(
    project_id="[current-project]",
    expand=False,  # CRITICAL: Summary only
    limit=10
)
# Display: "Session: {pins_count} pins ({open_pins} open, {completed_pins} completed)"
```

**During Work:**
```python
# When user starts a task, create a pin
mcp_mem_mesh_pin_add(
    project_id="[current-project]",
    content="[Task description in 1 line]",
    importance=[1-5],  # Auto-assess based on task scope
    tags=["relevant", "keywords"]
)

# When task completes
mcp_mem_mesh_pin_complete(pin_id="[pin-id]")
# If importance >= 4: "Promote this pin to permanent memory?"
```

**On Session End:**
```python
# Promote important pins
for pin in completed_pins:
    if pin.importance >= 4:
        result = mcp_mem_mesh_pin_promote(pin_id=pin.id)
        # Report: "Promoted to Memory ID: {result.memory_id}"

# End session
mcp_mem_mesh_session_end(
    project_id="[current-project]",
    summary="[Brief summary of session work]"
)
```

### Context Loading Rules

1. **Default: expand=False**
   - Load session summaries, not full pin contents
   - Saves ~2000 tokens per session start

2. **On-Demand: expand=True**
   - Only when user explicitly asks for details
   - Limit to top 5 by importance

3. **Search Instead of Load**
   - Use `mcp_mem_mesh_search` for historical context
   - Don't load entire session history

### Importance Assessment

Auto-assign importance when creating pins:
- **5**: Architecture changes, critical features
- **4**: Important bug fixes, significant features
- **3**: Regular tasks, standard implementations
- **2**: Minor improvements, small refactors
- **1**: Trivial fixes, typos, formatting

### Token Budget Targets

- Session start: ≤ 100 tokens (summary only)
- Per task: ≤ 50 tokens (pin tracking)
- Session end: ≤ 200 tokens (promotion + summary)
- **Target: ≤ 500 tokens/session**

### Behavior Triggers

**Auto-create pin when user says:**
- "작업 시작" / "start work"
- "구현" / "implement"
- "수정" / "fix"
- "추가" / "add"

**Auto-complete pin when user says:**
- "완료" / "done"
- "끝" / "finished"
- "테스트 통과" / "tests pass"

**Auto-end session when user says:**
- "세션 종료" / "end session"
- "오늘 끝" / "done for today"
- "작업 마무리" / "wrap up"

### Integration with Existing Rules

This rule complements existing steering rules by:
- Reducing context window usage
- Maintaining work continuity across sessions
- Automatically filtering important vs trivial work
- Enabling efficient context retrieval

### Disable Condition

If mem-mesh MCP tools are not available, fall back to standard context management.

---

**Implementation Note:** This rule is designed to work automatically. The agent should proactively use these tools without explicit user instruction, based on natural conversation flow.
