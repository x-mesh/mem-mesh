# Permanent Memory Rules

Permanent memories should be durable knowledge. Do not use `add()` as a task
log.

## Save

Save only when the work produced one of these:

| Category | Save when |
| --- | --- |
| `decision` | Architecture choice, policy change, tradeoff |
| `bug` | Meaningful root cause and fix |
| `incident` | Outage, data loss, recovery, operational failure |
| `idea` | Concrete future improvement |
| `code_snippet` | Reusable pattern with enough context to reuse |

Routine progress, file edits, and implementation status belong in pins.

## Do Not Save

- short Q&A
- file reads
- repeated information already saved
- raw command output
- secrets, tokens, passwords, PII, or `.env` contents

## Format

```markdown
## <one-line summary>

### WHY
<why this mattered>

### WHAT
- <decision, root cause, fix, or reusable pattern>

### IMPACT
<what future agents should know>
```

Use 3-6 tags that describe the module, technology, and action.

## Duplicate Control

Search first when a memory may already exist. Use `update(memory_id, ...)`
instead of creating a duplicate.
