#!/bin/bash
__VERSION_MARKER__
# SubagentStart hook: inject project context into subagents
# stdin: {agent_id, agent_type, session_id, ...}
# Output: {hookSpecificOutput: {hookEventName: "SubagentStart", additionalContext: "..."}}

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v curl >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

INPUT=$(cat)
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // empty')

# Skip for lightweight agents
case "$AGENT_TYPE" in
  Explore|Glob|Grep|Read) exit 0 ;;
esac

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

# Fetch key decisions/rules (lightweight: limit=5, category=decision)
RESPONSE=$(curl -s --max-time 3 \
  -G "${API_URL}/api/memories/search" \
  --data-urlencode "query=project rules architecture decision" \
  --data-urlencode "project_id=${PROJECT_DIR}" \
  --data-urlencode "category=decision" \
  --data-urlencode "limit=5" \
  2>/dev/null) || exit 0

CONTEXT=$(python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    results = data.get('results', [])
    if not results:
        sys.exit(0)
    lines = ['## Project Context (mem-mesh)', '']
    for r in results[:5]:
        content = r.get('content', '')[:200]
        lines.append(f'- {content}')
    print('\n'.join(lines))
except Exception:
    sys.exit(0)
" <<< "$RESPONSE" 2>/dev/null) || exit 0

[ -z "$CONTEXT" ] && exit 0

jq -n --arg ctx "$CONTEXT" '{
  hookSpecificOutput: {
    hookEventName: "SubagentStart",
    additionalContext: $ctx
  }
}'
exit 0
