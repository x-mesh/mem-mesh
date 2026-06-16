# mem-mesh IDE Prompt (Compact ~300 tokens)

Cursor / Windsurf / Claude Code 등 IDE system prompt에 복사.

---

```
## mem-mesh MCP Memory

persistent context across sessions.

### PROJECT
Directory name → project_id. /path/to/my-app → project_id="my-app"
Auto-normalized: camelCase/PascalCase → kebab-case (e.g. "myApp" → "my-app")

### WORKFLOW
1. Start: session_resume(project_id, expand="smart", limit=10) — stale pins auto-cleaned
2. Pin Gate: create pin for file-changing or multi-step work; skip read-only questions
3. Task: pin_add(content, project_id, importance=3) — default status: in_progress
   Say "Pin created: <id>" or "No pin created: <reason>"
4. Search: search(query, project_id, limit=5) — phrases, not words
5. Save: add(content, category, project_id, tags)
6. Stats: stats(project_id) — memory statistics
7. Done: pin_complete(pin_id, promote=true) — complete+promote in one call
8. End: session_end(project_id)

### SEARCH
- ✅ "token optimization strategy" ❌ "token"
- Always project_id. recency_weight=0.3 for recent.

### SAVE
- Format: ## Title\n### WHY\n### WHAT\n### IMPACT
- Categories: task|bug|idea|decision|code_snippet|incident|git-history
- Tags: 3-6 (tech + module + action)
- Duplicate → update(memory_id)

### RELATIONS
link(source_id, target_id, relation_type) — supersedes, depends_on, references
get_links(memory_id) — expand context

### BATCH
batch_operations([{type:"add",...},{type:"search",...}]) — 30-50% token save
```
