[mem-mesh Hard Rules]

- Start work: mem-mesh.search(query, project_id, limit=3~5). If relevant: mem-mesh.context(id, depth=2).
- Always log via mem-mesh.add when you make: decision / bug+fix / incident / reusable snippet / important task update.
- Each add MUST include: project_id, category, tags(3~6), and content in 2~5 bullets (why + what + impact).
- If superseded: mem-mesh.update(old_id) (don’t duplicate).
- Never store secrets/PII.
- All memories MUST be written in Korean.


[mem-mesh Hard Rules v2]

- Before work: CALL mem-mesh.search(query, project_id, limit=3~5). Use results.
- After any decision/bugfix/incident/reusable snippet/major change: CALL mem-mesh.add immediately.
- All mem-mesh content MUST be written in Korean.
- mem-mesh.add MUST include: project_id, category, tags(3~6), content(2~5 bullets: why/what/impact).
- If new info replaces old: CALL mem-mesh.update(old_id). No duplicates.
- NEVER claim “saved/recorded” unless the tool call succeeded. If tools are unavailable/blocked, say so and provide the exact payload you would have sent.
- Never store secrets/PII.

[mem-mesh Hard Rules v3]

- Before work: CALL mem-mesh.search(query, project_id, limit=3~5). Use results.
- After any decision/bugfix/incident/reusable snippet/major change: CALL mem-mesh.add immediately.
- All mem-mesh content MUST be written in Korean.
- mem-mesh.add MUST include: project_id, category, tags(3~6), content(2~5 bullets: why/what/impact).
- If new info replaces old: CALL mem-mesh.update(old_id). No duplicates.
- NEVER claim "saved/recorded" unless the tool call succeeded. If tools are unavailable/blocked, say so and provide the exact payload you would have sent.
- Never store secrets/PII.
- Q&A pairs are automatically saved via Kiro hooks for conversation tracking and analysis.
- Use mem-mesh.context(memory_id, depth=2) to explore related memories and conversation history.
- Both app.pure_mcp and app.mcp servers support all mem-mesh operations with identical functionality.


# [mem-mesh Integrated Protocol v2.0]

## 1. Retrieval Strategy (First Action)
- **Mandatory Check:** At the start of ANY new task or context switch, you MUST first consult the memory.
- **Action:** Call `mem-mesh.search(query=user_intent, project_id=current_project, limit=5)`.
- **Usage:** Actively apply retrieved memories (coding styles, past bug fixes, rules) to your current response. Do not ignore them.

## 2. Archival Strategy (Event-Driven)
- **Trigger Events:** You MUST call `mem-mesh.add` immediately when:
  1. A bug is diagnosed and resolved.
  2. An architectural decision or trade-off is made.
  3. A reusable code pattern/snippet is written.
  4. A significant project requirement is clarified.
- **Update Logic:** Before adding, consider if this replaces old information. If yes, search for the `old_id` and call `mem-mesh.update` instead of `add`. **No duplicates allowed.**

## 3. Data Formatting Standards (Strict)
- **Language:** All content inside `mem-mesh` MUST be written in **Korean (한국어)**.
- **Category Enforcement:** Use ONLY these categories:
  - `bug`: Error fixes, issues.
  - `decision`: Architecture choices, library selection.
  - `code_snippet`: Reusable functions, patterns.
  - `task`: Requirements, todo status.
  - `incident`: Server crashes, critical failures.
- **Content Structure (JSON String):** The `content` field must follow this bullet format:
  - `WHY (배경)`: What was the problem or context?
  - `WHAT (내용)`: What exactly changed or was decided?
  - `IMPACT (영향)`: What is the result or caution?
- **Tagging Rule:** 3~6 tags required. Must include: [Tech Stack], [Module Name], [Action Type]. (e.g., `["Python", "Auth", "Refactor", "Timeout"]`)

## 4. Integrity & Security
- **Honesty:** NEVER say "I have saved it" unless the tool call explicitly returns `success`. If the tool fails, output: "⚠️ Memory Save Failed. Intended Payload: ```json ... ```".
- **Security:** sanitize all inputs. NEVER store API Keys, passwords, tokens, or PII.

---