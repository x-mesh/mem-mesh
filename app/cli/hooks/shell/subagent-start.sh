#!/bin/bash
__VERSION_MARKER__
# SubagentStart hook: inject project context into subagents
# stdin: {agent_id, agent_type, session_id, ...}
# Output: {hookSpecificOutput: {hookEventName: "SubagentStart", additionalContext: "..."}}

set -euo pipefail
__HOOK_LOG__
mem_mesh_log "subagent-start" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "subagent-start" "abort" "jq not found"; exit 0; }
command -v curl >/dev/null 2>&1 || { mem_mesh_log "subagent-start" "abort" "curl not found"; exit 0; }

API_URL="${MEM_MESH_API_URL:-$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)}"
HOOK_TOKEN="${MEM_MESH_HOOK_TOKEN:-$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)}"
AUTH=()
AUTH_STATE=absent
if [ -n "$HOOK_TOKEN" ]; then AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}"); AUTH_STATE=present; fi

INPUT=$(cat)
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // empty')

# Skip for lightweight agents
case "$AGENT_TYPE" in
  Explore|Glob|Grep|Read) mem_mesh_log "subagent-start" "skip" "lightweight agent=$AGENT_TYPE"; exit 0 ;;
esac

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

mem_mesh_logv "subagent-start" "config" "url=$API_URL auth=$AUTH_STATE agent=$AGENT_TYPE"

# Fetch key decisions/rules (lightweight: limit=5, category=decision)
RESPONSE=$(curl -s --max-time 3 \
  -G "${API_URL}/api/memories/search" \
  --data-urlencode "query=project rules architecture decision" \
  --data-urlencode "project_id=${PROJECT_DIR}" \
  --data-urlencode "category=decision" \
  --data-urlencode "limit=5" \
  ${AUTH[@]+"${AUTH[@]}"} \
  2>/dev/null) || { mem_mesh_log "subagent-start" "abort" "search request failed"; exit 0; }
mem_mesh_log "subagent-start" "sent" "search bytes=${#RESPONSE} project=$PROJECT_DIR"

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
