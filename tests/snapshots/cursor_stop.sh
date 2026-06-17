#!/bin/bash
# mem-mesh-hooks prompt-version: 17
# Cursor Stop hook → mem-mesh /api/hooks/claude/stop
#
# Thin forwarder: the server keyword-matches the finished turn, redacts secrets,
# and saves if the content matches a save category. Auth = shared hook token
# (MEM_MESH_HOOK_TOKEN env or ~/.mem-mesh/hook_token).

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v curl >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-$(cat ~/.mem-mesh/api_url 2>/dev/null || echo https://meme.24x365.online)}"
HOOK_TOKEN="${MEM_MESH_HOOK_TOKEN:-$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)}"
AUTH=()
if [ -n "$HOOK_TOKEN" ]; then
  AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}")
fi

INPUT=$(cat)

# Loop guard locally to skip a needless request (server also enforces this).
# Cursor may send stopHookActive (camelCase); handle both.
ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // .stopHookActive // false' 2>/dev/null) || ACTIVE="false"
[ "$ACTIVE" = "true" ] && exit 0

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"

# Normalize Cursor camelCase fields to snake_case and inject project_id.
# Cursor may send: stopHookActive, lastAssistantMessage (or assistant_message / result).
PAYLOAD=$(printf '%s' "$INPUT" | jq -c --arg pid "$PROJECT_DIR" '. + {
  stop_hook_active: (.stop_hook_active // .stopHookActive // false),
  last_assistant_message: (.last_assistant_message // .lastAssistantMessage // .assistant_message // .result // null),
  project_id: $pid
}' 2>/dev/null) || PAYLOAD="$INPUT"

curl -s -o /dev/null --max-time 8 \
  -X POST "${API_URL}/api/hooks/claude/stop" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
