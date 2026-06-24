# mem-mesh Default Prompt Rules

Use this prompt when a project has mem-mesh MCP tools available but does not
use installed hooks. Copy the block between the separators into `CLAUDE.md`,
Cursor rules, Kiro steering, or another agent instruction file.

---

````markdown
## mem-mesh Memory

You have access to mem-mesh, a persistent memory layer exposed through MCP
tools. Use it to restore project context, track active work, and preserve
important decisions. Code and direct answers come first.

### Project ID

Use the repository directory name as `project_id` unless the project explicitly
defines another value. Normalize paths and names to kebab-case.

Example: `/Users/dev/work/MyProject` -> `project_id="my-project"`.

### Session Gate

At the start of a new session, call:

```text
session_resume(project_id="<project_id>", expand="smart")
```

Report the useful counts only: `pins_count`, `in_progress_pins`, `open_pins`,
and `completed_pins`. If there is no active session, continue with the task.
The first `pin_add` or `add` call creates the session.

When the user explicitly ends the work session, finish the requested work and
then call:

```text
session_end(project_id="<project_id>")
```

### Pin Gate

Before starting task work, decide whether this request needs a pin.

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
- basic status checks
- discussion about hooks or rules themselves

When creating a pin, call:

```text
pin_add(content="<one-line task summary>", project_id="<project_id>", importance=3, tags=[...])
```

Then state exactly one marker in the response:

```text
Pin created: <id>
```

or

```text
No pin created: <reason>
```

When the task is complete, call `pin_complete(pin_id="<id>")` immediately.
Do not leave an active pin before the final response. Use importance `4` for
important work and `5` for architecture-level work.

### Search Gate

Search before coding when the user refers to prior decisions, previous bugs,
project conventions, or earlier unfinished work.

Use specific queries:

```text
search(query="token auth hook decision", project_id="<project_id>", limit=5)
```

Avoid one-word searches such as `auth` or `token`.

### Permanent Memory Gate

Use `add()` only when the result should survive beyond this task. Routine task
state belongs in pins.

Save these categories:

- `decision`: architecture choices, tradeoffs, policy changes
- `bug`: root cause and fix for a meaningful bug
- `incident`: outage, data loss, recovery, or operational failure
- `idea`: concrete future improvement
- `code_snippet`: reusable pattern with enough context to reuse later

Do not save:

- short Q&A
- file reads
- repeated information already saved
- raw status updates
- secrets, tokens, passwords, PII, `.env` contents

### Memory Format

```markdown
## <one-line summary>

### WHY
<why this mattered>

### WHAT
- <changed decision, bug cause, or reusable pattern>

### IMPACT
<what future agents should know>
```

Use 3-6 tags that describe the module, technology, and action.

### Batch and Relations

Use `batch_operations` when making several memory calls in one turn. Link
related memories when it adds real value:

- `supersedes` for updated decisions
- `references` for bug fixes connected to root causes
- `depends_on` for dependency relationships

### Priority

Do the user's work first. Use mem-mesh to keep context accurate, but never let
memory calls replace implementation, verification, or a direct answer.
````

---

## Target Files

Claude Code:

```text
CLAUDE.md
```

Cursor:

```text
.cursor/rules/mem-mesh.mdc
```

Kiro:

```text
.kiro/steering/memory.md
```

For generated hook rules that match the installed hook prompt version, prefer:

```bash
mem-mesh hooks rules --project-id <project-id> --format plain
mem-mesh hooks rules --project-id <project-id> --format claude
```
