#!/bin/bash
__VERSION_MARKER__
# Claude Code PostToolUse hook → mem-mesh /api/hooks/claude/post-tool-use
#
# Write-signal recorder (fire-and-forget). After a file-mutating tool runs, this
# tells the server "real work happened this turn". The server uses that signal
# to gate the pin/save reminders so they fire only after an actual edit — never
# on a read-only question/analysis turn. Settings install this hook with a
# matcher restricted to write tools, and the server re-checks the tool name, so
# non-write tools are ignored on both sides. Auth = shared hook token.

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

# Fire-and-forget: never block the session on the write-signal POST.
curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/hooks/claude/post-tool-use" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" >/dev/null 2>&1 || true

exit 0
