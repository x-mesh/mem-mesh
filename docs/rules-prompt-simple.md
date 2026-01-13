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
