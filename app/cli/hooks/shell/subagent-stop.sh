#!/bin/bash
__VERSION_MARKER__
# Claude Code SubagentStop hook → mem-mesh /api/hooks/claude/subagent-stop
#
# Thin forwarder: the server keyword-matches the subagent result and saves the
# notable ones (prefixing the agent type). Auth = shared hook token (env or file).

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v curl >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)}"
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
  -X POST "${API_URL}/api/hooks/claude/subagent-stop" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
