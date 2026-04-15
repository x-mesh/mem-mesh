"""
MCP Tool Descriptions - 16개 도구 설명의 Single Source of Truth.

3-tier 전략:
- T1 (매 세션): session_resume, search, add, pin_add, pin_complete, session_end
- T2 (자주): context, update, batch_operations
- T3 (가끔): delete, stats, pin_promote, link, unlink, get_links, weekly_review

개선 원칙:
- Front-load: 동사로 시작, 핵심 정보 첫 문장
- 워크플로우 힌트: 선행/후행 도구 명시
- Negative guidance: 오용 방지 (add vs pin_add)
- 예시 최대 1개, enum 중복 나열 제거
- 목표: ~600 토큰 (현재 ~1,034에서 42% 절감)
"""

TOOL_DESCRIPTIONS: dict[str, str] = {
    # ===== T1: Used every session (2-3 sentences + 1 example) =====
    "session_resume": (
        "Query the active session for a project and restore its pins/context. "
        "Call at the START of every conversation. If no active session exists, "
        'returns {"status": "no_session"} — start working immediately; the next '
        "pin_add/add call auto-creates a fresh session. "
        "Auto-cleans stale pins (in_progress 7d, open 30d → completed). "
        'Use expand="smart" for optimal token efficiency.'
    ),
    "search": (
        "Search memories using hybrid search (vector + FTS5). "
        'Use query="" for recent memories sorted by date. '
        "Supports project_id, category, time_range, date_from/date_to, and recency_weight filters. "
        'Example: {"query": "auth decision", "project_id": "my-app", "limit": 5}'
    ),
    "add": (
        "Save a permanent memory (decision, bug, idea, code_snippet, incident). "
        "For short-term work tracking, use pin_add instead. "
        'Example: {"content": "Chose PostgreSQL because...", "category": "decision"}\n'
        "Set client to your tool/IDE name (e.g. 'claude_code', 'cursor', 'kiro', 'vscode') "
        "so memories are tagged with their source."
    ),
    "pin_add": (
        "Track a short-term work item in the current session. "
        "Default status: in_progress. Use open status for pre-planned future tasks. "
        "Importance is auto-determined if omitted. Returns compact: {id, importance, status}. "
        "Client auto-detected: HTTP(initialize/User-Agent), stdio(MEM_MESH_CLIENT env)."
    ),
    "pin_complete": (
        "Mark a pin as completed. Returns a promotion suggestion if importance >= 4. "
        "Use promote=true to complete and promote in one call (saves a round-trip). "
        "pin_promote is still available for promoting already-completed pins separately."
    ),
    "session_end": (
        "End the current session for a project. "
        "Call when work is done. Optionally provide a summary for session history. "
        "auto_complete_pins strategy: 'none'(default), 'in_progress'(complete active only), 'all'(complete everything)."
    ),
    # ===== T2: Frequently used (1-2 sentences) =====
    "context": (
        "Retrieve a memory and its related neighbors by memory_id. "
        "Use after search to explore connections between memories."
    ),
    "update": "Update content, category, or tags of an existing memory by memory_id.",
    "batch_operations": (
        "Execute multiple add/search operations in a single call. "
        "Reduces round-trips and token usage by 30-50%. "
        "MCP-only: no dedicated REST endpoint — HTTP clients must call "
        "POST /mcp/tools/call with name='batch_operations'."
    ),
    # ===== T3: Occasionally used (1 sentence) =====
    "delete": "Permanently delete a memory by memory_id.",
    "stats": "Get memory count, category breakdown, and project distribution statistics.",
    "pin_promote": "Promote a completed pin to a permanent memory for long-term retention.",
    "link": (
        "Create a typed relation (related, parent, child, supersedes, references, depends_on, similar) "
        "between two memories."
    ),
    "unlink": "Remove a relation between two memories. Omit relation_type to remove all.",
    "get_links": "List relations for a memory. Filter by direction (outgoing, incoming, both) and relation_type.",
    "weekly_review": "Generate a review report with incomplete pins, recent memories, and recommendations for a project.",
}
