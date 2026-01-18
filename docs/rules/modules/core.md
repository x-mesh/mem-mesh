# Core Rules

## MCP 사용 방법 (요약)
- mem-mesh MCP 도구를 우선 사용 (다른 저장소/노트로 분산 금지)
- 조회: `mcp_mem_mesh_search(query, project_id, limit=3~5)`
- 맥락 확장: `mcp_mem_mesh_context(memory_id, depth=2)`
- 저장: `mcp_mem_mesh_add(content, project_id, category, tags)`
- 업데이트: `mcp_mem_mesh_update(memory_id, content, category, tags)`
- 세션 핀: `mcp_mem_mesh_pin_add` → `mcp_mem_mesh_pin_complete` (importance >= 4면 promote)

## 기본 규칙
- 작업 시작/전환 전 `search(query, project_id, limit=3~5)` 필수
- 필요할 때만 `context(memory_id, depth=2)` 호출
- 저장 트리거 발생 시 즉시 `add(...)` 호출
- 중복 방지: 대체 시 `update(old_id)` 사용
