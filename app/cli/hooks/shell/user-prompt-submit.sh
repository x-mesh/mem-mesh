#!/bin/bash
__VERSION_MARKER__
# Claude Code UserPromptSubmit hook → mem-mesh /api/hooks/claude/user-prompt-submit
#
# Thin forwarder: the server does keyword-matched memory search + save/pin
# reminders, driven by the event stream (not the local transcript). Tuning knobs
# (MEM_MESH_SEARCH_THRESHOLD / _LIMIT / MEM_MESH_SAVE_REMINDER_TURNS, ...) now
# live on the server side. Auth = shared hook token (~/.mem-mesh/hook_token).

set -euo pipefail
__PROJECT_ID_RESOLVER__
__HOOK_LOG__
mem_mesh_log "user-prompt-submit" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "user-prompt-submit" "abort" "jq not found"; exit 0; }
command -v curl >/dev/null 2>&1 || { mem_mesh_log "user-prompt-submit" "abort" "curl not found"; exit 0; }

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
PROJECT_DIR="$(mem_mesh_project_id_from_input "$INPUT")"
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"
PAYLOAD=$(printf '%s' "$INPUT" | jq -c \
  --arg pid "$PROJECT_DIR" \
  --arg source "__SOURCE_TAG__" \
  --arg client "__CLIENT_TAG__" \
  '. + {project_id: $pid, hook_source: $source, client: $client}' 2>/dev/null) || PAYLOAD="$INPUT"

# Capture HTTP status + timing alongside the body (-w appends "\n<code> <time>")
# so the log distinguishes a 401 / 000 from a 200 with no reminder. Body =
# everything before the final newline.
CURL_EXIT=0
RESP_RAW=$(curl -s --max-time 8 -w '\n%{http_code} %{time_total}' \
  -X POST "${API_URL}/api/hooks/claude/user-prompt-submit" \
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
mem_mesh_log "user-prompt-submit" "sent" "http=$HTTP_CODE bytes=${#RESP} project=$PROJECT_DIR"
mem_mesh_logv "user-prompt-submit" "config" "url=$API_URL auth=$AUTH_STATE key=$(mem_mesh_keytail "$HOOK_TOKEN") time=${META_LINE#* }s curl_exit=$CURL_EXIT"

# Emit hookSpecificOutput JSON if the server returned any; stay silent otherwise.
# The POST payload above is unchanged by this stdout mode.
if printf '%s' "$RESP" | jq -e . >/dev/null 2>&1; then
  mem_mesh_log "user-prompt-submit" "output" "json bytes=${#RESP}"
  case "$HOOK_OUTPUT_MODE" in
    quiet|none|off)
      exit 0
      ;;
    compact)
      COMPACT=$(printf '%s' "$RESP" | jq -c --arg event "UserPromptSubmit" '
        (.hookSpecificOutput.additionalContext // .additional_context // "") as $ctx |
        if ($ctx | length) > 0 then
          {
            hookSpecificOutput: {
              hookEventName: $event,
              additionalContext: ($ctx | .[0:1200])
            }
          }
        else
          empty
        end
      ' 2>/dev/null) || COMPACT=""
      if [ -n "$COMPACT" ]; then printf '%s\n' "$COMPACT"; fi
      ;;
    *)
      printf '%s\n' "$RESP"
      ;;
  esac
fi
exit 0
