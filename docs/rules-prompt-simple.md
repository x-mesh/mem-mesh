# mem-mesh Rules (Short)

- 작업 시작/전환 전 `mcp_mem_mesh_search(query, project_id, limit=3~5)` 필수
- 관련 메모리 있으면 `mcp_mem_mesh_context(memory_id, depth=2)`로 확장
- 작업 시작 시 `mcp_mem_mesh_pin_add`, 완료 시 `mcp_mem_mesh_pin_complete` (importance >= 4 → promote)
- 결정/버그/사고/재사용 코드/중요 요구사항 완료 즉시 `mcp_mem_mesh_add`
- `project_id`, `category`, `tags(3~6)`, `content(WHY/WHAT/IMPACT)` 필수
- 카테고리: `bug | decision | code_snippet | task | incident`
- 중복 금지: 기존 대체 시 `mcp_mem_mesh_update`
- 민감정보/PII/절대 경로 금지, 성공 전 “저장 완료” 금지

상세 규칙은 `docs/rules-prompt-full.md` 참조.