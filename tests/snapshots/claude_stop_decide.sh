#!/bin/bash
# mem-mesh-hooks prompt-version: 16
# Claude Code Stop hook (decide variant) → mem-mesh /api/hooks/claude/stop
#
# Thin forwarder: the server keyword-matches the finished turn, pairs the
# question from the event stream, redacts secrets, and saves it only when the
# content matches a save category. This variant is structurally identical to
# stop.sh; the "decide" label reflects its origin as a keyword-decision hook —
# that logic now lives server-side. Auth = shared hook token (env or file).

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
ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null) || ACTIVE="false"
[ "$ACTIVE" = "true" ] && exit 0

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"
PAYLOAD=$(printf '%s' "$INPUT" | jq -c --arg pid "$PROJECT_DIR" '. + {project_id: $pid}' 2>/dev/null) || PAYLOAD="$INPUT"

curl -s -o /dev/null --max-time 8 \
  -X POST "${API_URL}/api/hooks/claude/stop" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
