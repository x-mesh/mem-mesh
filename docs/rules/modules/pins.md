# Session Pins Rules

- 세션 시작: `session_resume(expand=false, limit=10)`
- 작업 시작: `pin_add(project_id, content, importance=1~5, tags)`
- 작업 완료: `pin_complete(pin_id)`
- importance >= 4: `pin_promote(pin_id)` 제안
