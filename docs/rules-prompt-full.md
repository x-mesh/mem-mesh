[Memory Logging Rules — mem-mesh]

You MUST use mem-mesh as the single source of truth for persistent project knowledge.

1) When to write (mandatory)
- After any architecture/tech choice, trade-off conclusion, or “we will do X” statement → mem-mesh.add(category="decision")
- After fixing or identifying a bug/incident and its cause or workaround → mem-mesh.add(category="bug" or "incident")
- After producing reusable code patterns/snippets → mem-mesh.add(category="code_snippet")
- After completing a meaningful task milestone or plan change → mem-mesh.add(category="task")
- After generating a strong idea/proposal worth revisiting → mem-mesh.add(category="idea")

2) When to read (mandatory)
- Before starting a task/feature/bugfix, search first:
  mem-mesh.search(query=..., project_id=..., category=..., limit=3~5)
- If a memory is highly relevant, fetch surrounding context:
  mem-mesh.context(memory_id=..., depth=2~3)

3) What to store (format)
Every mem-mesh.add MUST include:
- content: 2~8 bullet lines, concrete and reusable
- project_id: current project identifier
- category: one of [task, bug, idea, decision, incident, code_snippet]
- tags: 3~8 tags (tech + domain + keyword)
Include in content when applicable:
- Decision: options considered, 이유(why), constraints, consequences
- Bug/Incident: symptom, root cause, reproduction, fix, prevention
- Code snippet: short snippet + when to use + pitfalls

4) Quality bar
- Don’t store vague notes. Make it actionable.
- Avoid secrets (tokens, passwords, personal data). Redact if needed.
- If new info supersedes old, update the old memory (mem-mesh.update) instead of duplicating.

5) Minimal templates
Decision content template:
- Decision: ...
- Context: ...
- Options: A / B / C
- Rationale: ...
- Consequences: ...
- Follow-ups: ...

Bug/Incident template:
- Symptom: ...
- Root cause: ...
- Repro: ...
- Fix: ...
- Prevention: ...

Code snippet template:
- Purpose: ...
- Snippet: ...
- Usage: ...
- Pitfalls: ...
