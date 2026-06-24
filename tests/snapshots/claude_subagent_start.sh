#!/bin/bash
# mem-mesh-hooks prompt-version: 21
# SubagentStart hook: inject project context into subagents
# stdin: {agent_id, agent_type, session_id, ...}
# Output: {hookSpecificOutput: {hookEventName: "SubagentStart", additionalContext: "..."}}

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
mem_mesh_log "subagent-start" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "subagent-start" "abort" "jq not found"; exit 0; }
command -v curl >/dev/null 2>&1 || { mem_mesh_log "subagent-start" "abort" "curl not found"; exit 0; }

API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo https://meme.24x365.online)"
HOOK_TOKEN="$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)"
AUTH=()
AUTH_STATE=absent
if [ -n "$HOOK_TOKEN" ]; then AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}"); AUTH_STATE=present; fi

INPUT=$(cat)
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // empty')

# Skip for lightweight agents
case "$AGENT_TYPE" in
  Explore|Glob|Grep|Read) mem_mesh_log "subagent-start" "skip" "lightweight agent=$AGENT_TYPE"; exit 0 ;;
esac

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

mem_mesh_logv "subagent-start" "config" "url=$API_URL auth=$AUTH_STATE key=$(mem_mesh_keytail "$HOOK_TOKEN") agent=$AGENT_TYPE"

# Fetch key decisions/rules (lightweight: limit=5, category=decision)
RESPONSE=$(curl -s --max-time 3 \
  -G "${API_URL}/api/memories/search" \
  --data-urlencode "query=project rules architecture decision" \
  --data-urlencode "project_id=${PROJECT_DIR}" \
  --data-urlencode "category=decision" \
  --data-urlencode "limit=5" \
  ${AUTH[@]+"${AUTH[@]}"} \
  2>/dev/null) || { mem_mesh_log "subagent-start" "abort" "search request failed"; exit 0; }
mem_mesh_log "subagent-start" "sent" "search bytes=${#RESPONSE} project=$PROJECT_DIR"

CONTEXT=$(python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    results = data.get('results', [])
    if not results:
        sys.exit(0)
    lines = ['## Project Context (mem-mesh)', '']
    for r in results[:5]:
        content = r.get('content', '')[:200]
        lines.append(f'- {content}')
    print('\n'.join(lines))
except Exception:
    sys.exit(0)
" <<< "$RESPONSE" 2>/dev/null) || exit 0

[ -z "$CONTEXT" ] && exit 0

jq -n --arg ctx "$CONTEXT" '{
  hookSpecificOutput: {
    hookEventName: "SubagentStart",
    additionalContext: $ctx
  }
}'
exit 0
