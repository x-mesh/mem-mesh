# Search Rules

Search is for restoring relevant prior context, not for every turn.

## When to Search

Search before coding when the task depends on:

- prior decisions
- previous bugs or incidents
- project conventions
- unfinished work
- user references such as "as before" or "the previous fix"

Skip search for simple status checks, explanations, and obvious local edits.

## Query Shape

Use specific phrases:

```text
search(query="oauth hook token rotation decision", project_id="mem-mesh", limit=5)
```

Avoid weak one-word queries:

```text
search(query="auth")
search(query="bug")
```

## Parameters

| Parameter | Recommendation |
| --- | --- |
| `project_id` | Always set it when the project is known |
| `limit` | Use 3-5 for prompt context |
| `category` | Filter to `decision`, `bug`, or `code_snippet` when useful |
| `recency_weight` | Use `0.2` to `0.5` when recent work matters |
| `response_format` | Use `compact` or `minimal` when IDs are enough |

## Follow-up Context

Call `context(memory_id, depth=2)` only when a search result is important to
the current work. Do not expand every result by default.
