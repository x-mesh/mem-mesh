# Core Rules

Use this module as the baseline when building a custom mem-mesh prompt.

## Project ID

- Use the repository directory name as `project_id` unless the project defines another value.
- Normalize names to kebab-case.
- Example: `/Users/dev/work/MyProject` -> `project_id="my-project"`.

## Session Gate

At the start of a new session:

```text
session_resume(project_id="<project_id>", expand="smart")
```

Report only useful counts: `pins_count`, `in_progress_pins`, `open_pins`, and `completed_pins`.
If no active session exists, continue with the task.

## Pin Gate

Create a pin before work that changes files, implements features, fixes bugs,
refactors code, runs migrations, or requires multi-step investigation.

Do not create a pin for simple questions, read-only status checks, or hook/rule
discussion.

```text
pin_add(content="<one-line task summary>", project_id="<project_id>", importance=3)
```

State one marker: `Pin created: <id>` or `No pin created: <reason>`.
Complete created pins before the final response.

## Search Gate

Search before coding when prior decisions, previous bugs, conventions, or
unfinished work may affect the answer.

```text
search(query="auth hook decision", project_id="<project_id>", limit=5)
```

Use specific phrases, not one-word queries.

## Permanent Memory Gate

Use `add()` only for durable knowledge: decisions, meaningful bugs, incidents,
ideas, and reusable code patterns. Routine task state belongs in pins.

## Core Tools

| Tool | Use |
| --- | --- |
| `session_resume` | Restore session context |
| `pin_add` / `pin_complete` | Track active work |
| `search` | Find prior context |
| `add` | Save durable memory |
| `context` | Expand one important search result |
| `update` | Correct or replace an existing memory |
