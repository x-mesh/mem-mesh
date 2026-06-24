#!/bin/bash
# mem-mesh-hooks prompt-version: 21
# Claude Code SessionStart hook → mem-mesh /api/hooks/claude/session-start
#
# Thin forwarder: POST the raw hook event; the server resumes context, detects
# continuation (from the event stream, not the local transcript), and renders
# the rules block — returning hookSpecificOutput. Auth is the shared hook token
# (~/.mem-mesh/hook_token) so every
# client authenticates against verify_hook_token uniformly.

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
# Client tag, substituted by the renderer at install time (claude_code).
# Falls back to "hook" when the block is used unrendered (e.g. tests).
_MM_CLIENT="claude_code"
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
PAYLOAD=$(printf '%s' "$INPUT" | jq -c \
  --arg pid "$PROJECT_DIR" \
  --arg source "claude-code-hook" \
  --arg client "claude_code" \
  '. + {project_id: $pid, hook_source: $source, client: $client}' 2>/dev/null) || PAYLOAD="$INPUT"

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
