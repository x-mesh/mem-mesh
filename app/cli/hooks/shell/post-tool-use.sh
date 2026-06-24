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
__HOOK_LOG__
mem_mesh_log "post-tool-use" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "post-tool-use" "abort" "jq not found"; exit 0; }
command -v curl >/dev/null 2>&1 || { mem_mesh_log "post-tool-use" "abort" "curl not found"; exit 0; }

API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)"
HOOK_TOKEN="$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)"
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

# Fire-and-forget: never block the session on the write-signal POST.
CURL_EXIT=0
HTTP_META=$(curl -s -o /dev/null --max-time 5 -w '%{http_code} %{time_total}' \
  -X POST "${API_URL}/api/hooks/claude/post-tool-use" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null) || CURL_EXIT=$?
HTTP_CODE="${HTTP_META%% *}"
[ -n "$HTTP_CODE" ] || HTTP_CODE="000"
mem_mesh_log "post-tool-use" "sent" "http=$HTTP_CODE project=$PROJECT_DIR"
mem_mesh_logv "post-tool-use" "config" "url=$API_URL auth=$AUTH_STATE key=$(mem_mesh_keytail "$HOOK_TOKEN") time=${HTTP_META#* }s curl_exit=$CURL_EXIT"

exit 0
