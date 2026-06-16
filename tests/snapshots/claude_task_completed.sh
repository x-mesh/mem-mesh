#!/bin/bash
# mem-mesh-hooks prompt-version: 16
# TaskCompleted hook → mem-mesh /api/hooks/claude/task-completed
#
# Thin forwarder: the server builds the task summary and saves it. Auth = shared
# hook token (env or ~/.mem-mesh/hook_token). stdin carries task_subject /
# task_description / teammate_name (team-driven); forwarded as-is.

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
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"
PAYLOAD=$(printf '%s' "$INPUT" | jq -c --arg pid "$PROJECT_DIR" '. + {project_id: $pid}' 2>/dev/null) || PAYLOAD="$INPUT"

curl -s -o /dev/null --max-time 8 \
  -X POST "${API_URL}/api/hooks/claude/task-completed" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
