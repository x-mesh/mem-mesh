#!/bin/bash
__VERSION_MARKER__
# Claude Code SessionStart hook → mem-mesh /api/hooks/claude/session-start
#
# Thin forwarder: POST the raw hook event; the server resumes context, detects
# continuation (from the event stream, not the local transcript), and renders
# the rules block — returning hookSpecificOutput. Auth is the shared hook token
# (~/.mem-mesh/hook_token) so every
# client authenticates against verify_hook_token uniformly.

set -euo pipefail
__HOOK_LOG__
mem_mesh_log "session-start" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "session-start" "abort" "jq not found"; echo '{}'; exit 0; }
command -v curl >/dev/null 2>&1 || { mem_mesh_log "session-start" "abort" "curl not found"; echo '{}'; exit 0; }

API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)"
HOOK_TOKEN="$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)"
AUTH=()
AUTH_STATE=absent
if [ -n "$HOOK_TOKEN" ]; then
  AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}")
  AUTH_STATE=present
fi

INPUT=$(cat)

# Explicit project_id (git toplevel basename); the server falls back to
# basename(cwd) but this is more accurate for worktrees.
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"
PAYLOAD=$(printf '%s' "$INPUT" | jq -c --arg pid "$PROJECT_DIR" '. + {project_id: $pid}' 2>/dev/null) || PAYLOAD="$INPUT"

# Capture HTTP status + timing alongside the body (-w appends "\n<code> <time>")
# so the log can distinguish a 401 (bad token) / 000 (server unreachable) from a
# 200 with an empty no-op body. The body is everything before the final newline.
CURL_EXIT=0
RESP_RAW=$(curl -s --max-time 8 -w '\n%{http_code} %{time_total}' \
  -X POST "${API_URL}/api/hooks/claude/session-start" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null) || CURL_EXIT=$?
if [ -n "$RESP_RAW" ]; then
  META_LINE="${RESP_RAW##*$'\n'}"
  RESP="${RESP_RAW%$'\n'*}"
else
  META_LINE=""; RESP=""
fi
HTTP_CODE="${META_LINE%% *}"
[ -n "$HTTP_CODE" ] || HTTP_CODE="000"
mem_mesh_log "session-start" "sent" "http=$HTTP_CODE bytes=${#RESP} project=$PROJECT_DIR"
mem_mesh_logv "session-start" "config" "url=$API_URL auth=$AUTH_STATE key=$(mem_mesh_keytail "$HOOK_TOKEN") time=${META_LINE#* }s curl_exit=$CURL_EXIT"

# Server returns hookSpecificOutput JSON, or an empty body on no-op. Emit valid
# JSON verbatim; fall back to {} so Claude Code's output schema check passes.
if printf '%s' "$RESP" | jq -e . >/dev/null 2>&1; then
  mem_mesh_log "session-start" "output" "json bytes=${#RESP}"
  printf '%s\n' "$RESP"
else
  mem_mesh_log "session-start" "output" "fallback {} (resp not json)"
  echo '{}'
fi
