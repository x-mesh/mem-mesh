#!/bin/bash
# mem-mesh-hooks prompt-version: 12
# SubagentStop hook: auto-save important subagent results (local mode)
# stdin: {stop_hook_active, agent_id, agent_type, last_assistant_message, ...}
# Reuses keyword matching logic from stop-decide

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

MEM_MESH_PATH="/Users/jinwoo/work/project/mem-mesh"

INPUT=$(cat)

# Guard: prevent loop
ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // .stopHookActive // false')
[ "$ACTIVE" = "true" ] && exit 0

MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // .assistant_message // .result // empty')
[ ${#MESSAGE} -lt 100 ] && exit 0

# Already saved via MCP
echo "$MESSAGE" | grep -q 'mcp__mem-mesh__add' && exit 0

# Keyword decision (same rules as stop-decide.sh)
CATEGORY=$(python3 -c "
import sys, re
msg = sys.stdin.read().lower()

save_rules = [
    (r'(버그|bug).*(수정|fix|해결|resolved|patch)', 'bug'),
    (r'(수정|fix).*(버그|bug|에러|error|오류)', 'bug'),
    (r'(에러|error|exception|오류).*(해결|수정|fixed|resolved)', 'bug'),
    (r'(결정|decision).*(변경|선택|채택|chose|decided)', 'decision'),
    (r'(아키텍처|architecture|설계).*(결정|변경|선택)', 'decision'),
    (r'(전환|migration|마이그레이션)', 'decision'),
    (r'(구현|implement).*(완료|했습니다|done)', 'code_snippet'),
    (r'(장애|incident|outage).*(발생|occurred|detected)', 'incident'),
    (r'(아이디어|idea).*(제안|suggest|고려|consider)', 'idea'),
]

for pat, cat in save_rules:
    if re.search(pat, msg):
        print(cat)
        sys.exit(0)

print('SKIP')
" <<< "$MESSAGE" 2>/dev/null) || CATEGORY="SKIP"

[ "$CATEGORY" = "SKIP" ] && exit 0

# Build content with agent type prefix
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // .subagent_type // .agentType // "unknown"')
CONTENT="[${AGENT_TYPE} agent] ${MESSAGE}"
CONTENT=$(echo "$CONTENT" | head -c 9500)

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

python3 -c "
import sys, asyncio, json
sys.path.insert(0, '$MEM_MESH_PATH')
try:
    from app.core.storage.direct import DirectStorageManager

    async def save():
        s = DirectStorageManager()
        await s.initialize()
        await s.add_memory(
            content=sys.argv[1],
            project_id=sys.argv[2],
            category=sys.argv[3],
            source='hook-local',
            client='cursor',
            tags=['auto-save', 'subagent', sys.argv[3]],
        )

    asyncio.run(save())
except Exception:
    pass
" "$CONTENT" "$PROJECT_DIR" "$CATEGORY" 2>/dev/null || true

exit 0
