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
1. Start: session_resume(project_id, expand=false, limit=10)
2. Task: pin_add(content, project_id, importance=3)
3. Search: search(query, project_id, limit=5) — phrases, not words
4. Save: add(content, category, project_id, tags)
5. Stats: stats(project_id) — memory statistics
6. Done: pin_complete(pin_id); importance≥4 → pin_promote(pin_id)
7. End: session_end(project_id)

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
