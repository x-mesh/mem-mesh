#!/bin/bash
__VERSION_MARKER__
# Claude Code Stop hook (decide variant) → mem-mesh /api/hooks/claude/stop
#
# Thin forwarder: the server keyword-matches the finished turn, pairs the
# question from the event stream, redacts secrets, and saves it only when the
# content matches a save category. This variant is structurally identical to
# stop.sh; the "decide" label reflects its origin as a keyword-decision hook —
# that logic now lives server-side. Auth = shared hook token (~/.mem-mesh/hook_token).

set -euo pipefail
__HOOK_LOG__
mem_mesh_log "stop-decide" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "stop-decide" "abort" "jq not found"; exit 0; }
command -v curl >/dev/null 2>&1 || { mem_mesh_log "stop-decide" "abort" "curl not found"; exit 0; }

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
ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null) || ACTIVE="false"
[ "$ACTIVE" = "true" ] && { mem_mesh_log "stop-decide" "skip" "stop_hook_active"; exit 0; }

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"
PAYLOAD=$(printf '%s' "$INPUT" | jq -c --arg pid "$PROJECT_DIR" '. + {project_id: $pid}' 2>/dev/null) || PAYLOAD="$INPUT"

CURL_EXIT=0
HTTP_META=$(curl -s -o /dev/null --max-time 8 -w '%{http_code} %{time_total}' \
  -X POST "${API_URL}/api/hooks/claude/stop" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null) || CURL_EXIT=$?
HTTP_CODE="${HTTP_META%% *}"
[ -n "$HTTP_CODE" ] || HTTP_CODE="000"
mem_mesh_log "stop-decide" "sent" "http=$HTTP_CODE project=$PROJECT_DIR"
mem_mesh_logv "stop-decide" "config" "url=$API_URL auth=$AUTH_STATE key=$(mem_mesh_keytail "$HOOK_TOKEN") time=${HTTP_META#* }s curl_exit=$CURL_EXIT"

exit 0
