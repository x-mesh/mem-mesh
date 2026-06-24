# Batch Rules

Use `batch_operations` when several memory calls are needed in one turn.

## When to Batch

- multiple related searches
- search followed by a memory save
- creating several pins or memories from one workflow

## Example

```text
batch_operations(operations=[
  {"type": "search", "query": "oauth hook token decision", "project_id": "mem-mesh", "limit": 5},
  {"type": "pin_add", "content": "Update hook token docs", "project_id": "mem-mesh", "importance": 3}
])
```

## Rules

- Keep each operation explicit.
- Do not batch unrelated work just to reduce calls.
- Do not use batch operations to hide failures. If one result matters, inspect it.
