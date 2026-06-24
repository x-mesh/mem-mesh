#!/bin/bash
__VERSION_MARKER__
# Cursor Stop hook → mem-mesh /api/hooks/claude/stop
#
# Thin forwarder: the server keyword-matches the finished turn, redacts secrets,
# and saves if the content matches a save category. Auth = shared hook token
# (~/.mem-mesh/hook_token).

set -euo pipefail
__PROJECT_ID_RESOLVER__
__HOOK_LOG__
mem_mesh_log "stop" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "stop" "abort" "jq not found"; exit 0; }
command -v curl >/dev/null 2>&1 || { mem_mesh_log "stop" "abort" "curl not found"; exit 0; }

API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)"
HOOK_TOKEN="$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)"
AUTH=()
AUTH_STATE=absent
if [ -n "$HOOK_TOKEN" ]; then
  AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}")
  AUTH_STATE=present
fi

INPUT=$(cat)

# Loop guard locally to skip a needless request (server also enforces this).
# Cursor may send stopHookActive (camelCase); handle both.
ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // .stopHookActive // false' 2>/dev/null) || ACTIVE="false"
[ "$ACTIVE" = "true" ] && { mem_mesh_log "stop" "skip" "stop_hook_active"; exit 0; }

PROJECT_DIR="$(mem_mesh_project_id)"
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"

# Normalize Cursor camelCase fields to snake_case and inject project_id.
# Cursor may send: stopHookActive, lastAssistantMessage (or assistant_message / result).
PAYLOAD=$(printf '%s' "$INPUT" | jq -c \
  --arg pid "$PROJECT_DIR" \
  --arg source "__SOURCE_TAG__" \
  --arg client "__CLIENT_TAG__" \
  '. + {
  stop_hook_active: (.stop_hook_active // .stopHookActive // false),
  last_assistant_message: (.last_assistant_message // .lastAssistantMessage // .assistant_message // .result // null),
  project_id: $pid,
  hook_source: $source,
  client: $client
}' 2>/dev/null) || PAYLOAD="$INPUT"

CURL_EXIT=0
HTTP_META=$(curl -s -o /dev/null --max-time 8 -w '%{http_code} %{time_total}' \
  -X POST "${API_URL}/api/hooks/claude/stop" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null) || CURL_EXIT=$?
HTTP_CODE="${HTTP_META%% *}"
[ -n "$HTTP_CODE" ] || HTTP_CODE="000"
mem_mesh_log "stop" "sent" "http=$HTTP_CODE project=$PROJECT_DIR"
mem_mesh_logv "stop" "config" "url=$API_URL auth=$AUTH_STATE key=$(mem_mesh_keytail "$HOOK_TOKEN") time=${HTTP_META#* }s curl_exit=$CURL_EXIT"

exit 0
