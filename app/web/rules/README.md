# mem-mesh Rule Assets

These files back the Settings page Rule Manager and `/api/rules`.

For normal agent setup, prefer the generated hook rules because they share the
same renderer and prompt version as the installed hooks:

```bash
mem-mesh hooks rules --project-id <project-id> --format plain
mem-mesh hooks rules --project-id <project-id> --format claude
```

## Preset

| File | Purpose |
| --- | --- |
| `DEFAULT_PROMPT.md` | Standalone prompt for projects that use mem-mesh MCP without installed hooks |

## Optional Modules

The Settings Rule Manager exposes only these composable modules:

| Module | Purpose |
| --- | --- |
| `modules/core.md` | Session Gate, Pin Gate, Search Gate, and core tools |
| `modules/search.md` | Search timing, query shape, and useful parameters |
| `modules/memory-log.md` | Permanent memory categories, format, and duplicate control |
| `modules/pins.md` | Pin workflow, status, and importance guidance |
| `modules/relations.md` | Relation types and when to link memories |
| `modules/batch.md` | When to use `batch_operations` |
| `modules/security.md` | Secret handling and honesty rules |

Removed legacy modules:

- `minimal.md`: replaced by generated `hooks rules --format plain`
- `quick-start.md`: setup belongs on the Connect page and README
- `api-usage.md`: API docs belong in `/docs`, not agent prompt modules
- `team-context.md`: too vague for direct prompt use
- `mcp-helper.md`: meta-instructions duplicated the Rule Manager itself
