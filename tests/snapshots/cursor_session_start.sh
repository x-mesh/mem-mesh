#!/bin/bash
# mem-mesh-hooks prompt-version: 22
# Cursor SessionStart hook → mem-mesh /api/hooks/claude/session-start
#
# Thin forwarder: POST the Cursor hook event (camelCase fields normalized to
# snake_case); the server resumes context and renders the rules block —
# returning hookSpecificOutput. Auth = shared hook token
# (~/.mem-mesh/hook_token).

set -euo pipefail
# --- mem-mesh hook logging (opt-in: MEM_MESH_HOOK_LOG) -------------------------
# Append a per-stage trace to ~/.mem-mesh/hooks.log so you can tell whether this
# shell hook actually fired and where it exited — surfacing the otherwise-silent
# failure modes (jq/curl missing, server down, auth 401, timeout). Each line is
# tagged with the client (claude_code / cursor / kiro / codex) so a single log
# distinguishes which tool's hook fired. Levels:
#   unset / 0 / false  -> off (no-op, zero overhead)
#   1 / on / true      -> concise: fired / abort / sent (http) / output
#   2 / debug / verbose-> + a "config" line per request: url, auth present?,
#                          hook-key tail (last 4 chars), curl time + exit code
#                          (metadata only, never the full token or any content)
case "${MEM_MESH_HOOK_LOG:-}" in
  ""|0|false|no|off|FALSE|NO|OFF) _MM_LOG=0 ;;
  2|3|debug|DEBUG|verbose|VERBOSE|trace|TRACE) _MM_LOG=2 ;;
  *) _MM_LOG=1 ;;
esac
# Client tag, substituted by the renderer at install time (cursor).
# Falls back to "hook" when the block is used unrendered (e.g. tests).
_MM_CLIENT="cursor"
mem_mesh_log() {
  [ "${_MM_LOG:-0}" -ge 1 ] 2>/dev/null || return 0
  _mm_hook="${1:-?}"; _mm_stage="${2:-?}"
  if [ "$#" -gt 2 ]; then shift 2; _mm_detail=" $*"; else _mm_detail=""; fi
  _mm_ts="$(date '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || echo '-')"
  mkdir -p "${HOME}/.mem-mesh" 2>/dev/null || true
  printf '%s [%s/%s] pid=%s %s%s\n' \
    "$_mm_ts" "${_MM_CLIENT:-hook}" "$_mm_hook" "$$" "$_mm_stage" "$_mm_detail" \
    >>"${HOME}/.mem-mesh/hooks.log" 2>/dev/null || true
}
# Verbose channel: only emits at level >= 2. Detail is connection metadata
# (url / auth-present / key tail / timing / curl exit) — never request or
# response bodies, and never the full token.
mem_mesh_logv() {
  [ "${_MM_LOG:-0}" -ge 2 ] 2>/dev/null || return 0
  mem_mesh_log "$@"
}
# Mask a token to its last 4 chars for verbose logs (never the full secret).
# Empty / unset -> "none". Used in the level-2 "config" line as key=...<tail>.
mem_mesh_keytail() {
  if [ -n "${1:-}" ]; then
    printf '...%s' "$(printf '%s' "$1" | tail -c 4)"
  else
    printf 'none'
  fi
}
mem_mesh_log "session-start" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "session-start" "abort" "jq not found"; echo '{}'; exit 0; }
command -v curl >/dev/null 2>&1 || { mem_mesh_log "session-start" "abort" "curl not found"; echo '{}'; exit 0; }

API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo https://meme.24x365.online)"
HOOK_TOKEN="$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)"
HOOK_OUTPUT_MODE="${MEM_MESH_HOOK_OUTPUT_MODE:-full}"
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

# Normalize Cursor camelCase fields to snake_case and inject project_id.
# Cursor sends sessionId / transcriptPath; the server expects snake_case.
PAYLOAD=$(printf '%s' "$INPUT" | jq -c \
  --arg pid "$PROJECT_DIR" \
  --arg source "cursor-hook" \
  --arg client "cursor" \
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
