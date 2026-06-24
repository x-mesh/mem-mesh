# Relation Rules

Relations are useful when memory links will help future search and context
reconstruction. Do not link everything.

## Relation Types

| Type | Use |
| --- | --- |
| `related` | General connection |
| `parent` | Broader concept |
| `child` | Narrower concept |
| `supersedes` | New decision replaces an older one |
| `references` | Bug fix or note cites another memory |
| `depends_on` | One item depends on another |
| `similar` | Similar pattern or duplicate candidate |

## Commands

```text
link(source_id="<id>", target_id="<id>", relation_type="references")
get_links(memory_id="<id>", direction="both", limit=20)
unlink(source_id="<id>", target_id="<id>", relation_type="references")
```

## Use Cases

- Link a bug fix to the root-cause memory with `references`.
- Link a replacement decision to the older decision with `supersedes`.
- Link dependent architecture notes with `depends_on`.
