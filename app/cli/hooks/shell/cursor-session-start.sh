#!/bin/bash
__VERSION_MARKER__
# Cursor SessionStart hook → mem-mesh /api/hooks/claude/session-start
#
# Thin forwarder: POST the Cursor hook event (camelCase fields normalized to
# snake_case); the server resumes context and renders the rules block —
# returning hookSpecificOutput. Auth = shared hook token
# (~/.mem-mesh/hook_token).

set -euo pipefail
__PROJECT_ID_RESOLVER__
__HOOK_LOG__
mem_mesh_log "session-start" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "session-start" "abort" "jq not found"; echo '{}'; exit 0; }
command -v curl >/dev/null 2>&1 || { mem_mesh_log "session-start" "abort" "curl not found"; echo '{}'; exit 0; }

API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)"
HOOK_TOKEN="$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)"
HOOK_OUTPUT_MODE="${MEM_MESH_HOOK_OUTPUT_MODE:-__HOOK_OUTPUT_MODE__}"
AUTH=()
AUTH_STATE=absent
if [ -n "$HOOK_TOKEN" ]; then
  AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}")
  AUTH_STATE=present
fi

INPUT=$(cat)

# Explicit project_id from init/config, with basename fallback for compatibility.
PROJECT_DIR="$(mem_mesh_project_id)"
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"

# Normalize Cursor camelCase fields to snake_case and inject project_id.
# Cursor sends sessionId / transcriptPath; the server expects snake_case.
PAYLOAD=$(printf '%s' "$INPUT" | jq -c \
  --arg pid "$PROJECT_DIR" \
  --arg source "__SOURCE_TAG__" \
  --arg client "__CLIENT_TAG__" \
  '. + {
  session_id: (.session_id // .sessionId // null),
  transcript_path: (.transcript_path // .transcriptPath // null),
  project_id: $pid,
  hook_source: $source,
  client: $client
}' 2>/dev/null) || PAYLOAD="$INPUT"

CURL_EXIT=0
RESP=$(curl -s --max-time 8 \
  -X POST "${API_URL}/api/hooks/claude/session-start" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null) || { CURL_EXIT=$?; RESP=""; }

# Server returns hookSpecificOutput JSON, or an empty body on no-op. Emit valid
# JSON verbatim; fall back to {} so the output schema check passes. The logging
# block only writes to ~/.mem-mesh/hooks.log, never stdout, so it never
# corrupts the JSON Cursor reads here.
if printf '%s' "$RESP" | jq -e . >/dev/null 2>&1; then
  mem_mesh_log "session-start" "sent" "resp=json project=$PROJECT_DIR"
  case "$HOOK_OUTPUT_MODE" in
    quiet|none|off)
      exit 0
      ;;
    compact)
      COMPACT=$(printf '%s' "$RESP" | jq -c --arg event "SessionStart" '
        (.hookSpecificOutput.additionalContext // .additional_context // "") as $ctx |
        if ($ctx | length) > 0 then
          {
            hookSpecificOutput: {
              hookEventName: $event,
              additionalContext: "mem-mesh session context available. Detailed hook output suppressed; use mem-mesh MCP tools when prior context is needed."
            }
          }
        else
          .
        end
      ' 2>/dev/null) || COMPACT=""
      if [ -n "$COMPACT" ]; then printf '%s\n' "$COMPACT"; else printf '%s\n' "$RESP"; fi
      ;;
    *)
      printf '%s\n' "$RESP"
      ;;
  esac
else
  mem_mesh_log "session-start" "sent" "resp=empty project=$PROJECT_DIR"
  case "$HOOK_OUTPUT_MODE" in
    quiet|none|off) exit 0 ;;
    *) echo '{}' ;;
  esac
fi
mem_mesh_logv "session-start" "config" "url=$API_URL auth=$AUTH_STATE key=$(mem_mesh_keytail "$HOOK_TOKEN") curl_exit=$CURL_EXIT"
