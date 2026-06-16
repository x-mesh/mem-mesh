#!/bin/bash
__VERSION_MARKER__
# Claude Code UserPromptSubmit hook → mem-mesh /api/hooks/claude/user-prompt-submit
#
# Thin forwarder: the server does keyword-matched memory search + save/pin
# reminders, driven by the event stream (not the local transcript). Tuning knobs
# (MEM_MESH_SEARCH_THRESHOLD / _LIMIT / MEM_MESH_SAVE_REMINDER_TURNS, ...) now
# live on the server side. Auth = shared hook token (env or ~/.mem-mesh file).

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
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"
PAYLOAD=$(printf '%s' "$INPUT" | jq -c --arg pid "$PROJECT_DIR" '. + {project_id: $pid}' 2>/dev/null) || PAYLOAD="$INPUT"

RESP=$(curl -s --max-time 8 \
  -X POST "${API_URL}/api/hooks/claude/user-prompt-submit" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null) || RESP=""

# Emit hookSpecificOutput JSON if the server returned any; stay silent otherwise.
if printf '%s' "$RESP" | jq -e . >/dev/null 2>&1; then
  printf '%s\n' "$RESP"
fi
exit 0
