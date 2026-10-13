#!/bin/bash
__VERSION_MARKER__
# SubagentStart hook: inject project context into subagents
# stdin: {agent_id, agent_type, session_id, ...}
# Output: {hookSpecificOutput: {hookEventName: "SubagentStart", additionalContext: "..."}}

set -euo pipefail
__PROJECT_ID_RESOLVER__
__HOOK_LOG__
mem_mesh_log "subagent-start" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "subagent-start" "abort" "jq not found"; exit 0; }
command -v curl >/dev/null 2>&1 || { mem_mesh_log "subagent-start" "abort" "curl not found"; exit 0; }

API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)"
HOOK_TOKEN="$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)"
HOOK_OUTPUT_MODE="${MEM_MESH_HOOK_OUTPUT_MODE:-__HOOK_OUTPUT_MODE__}"
AUTH=()
AUTH_STATE=absent
if [ -n "$HOOK_TOKEN" ]; then AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}"); AUTH_STATE=present; fi

INPUT=$(cat)
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // empty')

# Skip for lightweight agents
case "$AGENT_TYPE" in
  Explore|Glob|Grep|Read) mem_mesh_log "subagent-start" "skip" "lightweight agent=$AGENT_TYPE"; exit 0 ;;
esac

PROJECT_DIR="$(mem_mesh_project_id_from_input "$INPUT")"

# Fetch key decisions/rules (lightweight: limit=5, category=decision).
# -w appends "\n<code> <time>" so the log carries status + latency like the
# forwarders do; a failed request logs http=000 instead of vanishing.
CURL_EXIT=0
mem_mesh_logv "subagent-start" "posting" "agent=$AGENT_TYPE"
RESP_RAW=$(curl -s --max-time 3 -w '\n%{http_code} %{time_total}' \
  -G "${API_URL}/api/memories/search" \
  --data-urlencode "query=project rules architecture decision" \
  --data-urlencode "project_id=${PROJECT_DIR}" \
  --data-urlencode "category=decision" \
  --data-urlencode "limit=5" \
  ${AUTH[@]+"${AUTH[@]}"} \
  2>/dev/null) || CURL_EXIT=$?
if [ -n "$RESP_RAW" ]; then
  HTTP_META="${RESP_RAW##*$'\n'}"
  RESPONSE="${RESP_RAW%$'\n'*}"
else
  HTTP_META=""; RESPONSE=""
fi
HTTP_CODE="${HTTP_META%% *}"
[ -n "$HTTP_CODE" ] || HTTP_CODE="000"
mem_mesh_log "subagent-start" "sent" "http=$HTTP_CODE bytes=${#RESPONSE} project=$PROJECT_DIR"
mem_mesh_logv "subagent-start" "config" "url=$API_URL auth=$AUTH_STATE key=$(mem_mesh_keytail "$HOOK_TOKEN") time=${HTTP_META#* }s curl_exit=$CURL_EXIT agent=$AGENT_TYPE"
[ "$CURL_EXIT" -eq 0 ] || exit 0

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

[ -z "$CONTEXT" ] && { mem_mesh_log "subagent-start" "output" "none"; exit 0; }

case "$HOOK_OUTPUT_MODE" in
  quiet|none|off)
    exit 0
    ;;
  compact)
    CONTEXT=$(printf '%s' "$CONTEXT" | jq -Rrsr '.[0:1200]')
    ;;
esac

mem_mesh_log "subagent-start" "output" "chars=${#CONTEXT}"
jq -n --arg ctx "$CONTEXT" '{
  hookSpecificOutput: {
    hookEventName: "SubagentStart",
    additionalContext: $ctx
  }
}'
exit 0
