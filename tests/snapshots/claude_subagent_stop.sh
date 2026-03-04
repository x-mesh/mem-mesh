#!/bin/bash
# mem-mesh-hooks prompt-version: 9
# SubagentStop hook: auto-save important subagent results
# stdin: {stop_hook_active, agent_id, agent_type, last_assistant_message, ...}
# Reuses keyword matching logic from stop-decide

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-https://meme.24x365.online}"

INPUT=$(cat)

# Guard: prevent loop
ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
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
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // "unknown"')
CONTENT="[${AGENT_TYPE} agent] ${MESSAGE}"
CONTENT=$(echo "$CONTENT" | head -c 9500)

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

PAYLOAD=$(jq -n \
  --arg content "$CONTENT" \
  --arg project_id "$PROJECT_DIR" \
  --arg category "$CATEGORY" \
  --arg source "claude-code-hook" \
  --arg client "claude_code" \
  '{
    content: $content,
    project_id: $project_id,
    category: $category,
    source: $source,
    client: $client,
    tags: ["auto-save", "subagent", $category]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
