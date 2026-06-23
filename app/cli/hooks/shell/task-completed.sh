#!/bin/bash
__VERSION_MARKER__
# TaskCompleted hook → mem-mesh /api/hooks/claude/task-completed
#
# Thin forwarder: the server builds the task summary and saves it. Auth = shared
# hook token (env or ~/.mem-mesh/hook_token). stdin carries task_subject /
# task_description / teammate_name (team-driven); forwarded as-is.

set -euo pipefail
__HOOK_LOG__
mem_mesh_log "task-completed" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "task-completed" "abort" "jq not found"; exit 0; }
command -v curl >/dev/null 2>&1 || { mem_mesh_log "task-completed" "abort" "curl not found"; exit 0; }

API_URL="${MEM_MESH_API_URL:-$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)}"
HOOK_TOKEN="${MEM_MESH_HOOK_TOKEN:-$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)}"
AUTH=()
AUTH_STATE=absent
if [ -n "$HOOK_TOKEN" ]; then
  AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}")
  AUTH_STATE=present
fi

INPUT=$(cat)
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"
PAYLOAD=$(printf '%s' "$INPUT" | jq -c --arg pid "$PROJECT_DIR" '. + {project_id: $pid}' 2>/dev/null) || PAYLOAD="$INPUT"

CURL_EXIT=0
HTTP_META=$(curl -s -o /dev/null --max-time 8 -w '%{http_code} %{time_total}' \
  -X POST "${API_URL}/api/hooks/claude/task-completed" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null) || CURL_EXIT=$?
HTTP_CODE="${HTTP_META%% *}"
[ -n "$HTTP_CODE" ] || HTTP_CODE="000"
mem_mesh_log "task-completed" "sent" "http=$HTTP_CODE project=$PROJECT_DIR"
mem_mesh_logv "task-completed" "config" "url=$API_URL auth=$AUTH_STATE time=${HTTP_META#* }s curl_exit=$CURL_EXIT"

exit 0
