# Session Pin Rules

Pins track active work. They are the right place for routine task state.

## Pin Gate

Create a pin for:

- file edits
- implementation
- bug fixes
- refactoring
- migrations
- multi-step investigation
- work that may continue into a later turn

Do not create a pin for:

- simple questions
- explanations
- lookups
- read-only analysis
- basic checks
- hook or rules discussion

## Workflow

```text
session_resume(project_id="<project_id>", expand="smart")
pin_add(content="<one-line task summary>", project_id="<project_id>", importance=3)
pin_complete(pin_id="<pin_id>")
```

State exactly one marker in the visible response:

```text
Pin created: <id>
No pin created: <reason>
```

Do not leave an active pin before the final response.

## Status and Importance

| Field | Guidance |
| --- | --- |
| `open` | Planned future work |
| `in_progress` | Active work, default for `pin_add` |
| `completed` | Finished work |
| `importance=3` | Normal task |
| `importance=4` | Important cross-module work |
| `importance=5` | Architecture-level work |

Promote only when the completed pin contains durable knowledge worth keeping
as a permanent memory.
