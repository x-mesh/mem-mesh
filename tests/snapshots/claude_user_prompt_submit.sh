#!/bin/bash
# mem-mesh-hooks prompt-version: 23
# Claude Code UserPromptSubmit hook → mem-mesh /api/hooks/claude/user-prompt-submit
#
# Thin forwarder: the server does keyword-matched memory search + save/pin
# reminders, driven by the event stream (not the local transcript). Tuning knobs
# (MEM_MESH_SEARCH_THRESHOLD / _LIMIT / MEM_MESH_SAVE_REMINDER_TURNS, ...) now
# live on the server side. Auth = shared hook token (~/.mem-mesh/hook_token).

set -euo pipefail
# --- mem-mesh project id resolution ------------------------------------------
mem_mesh_project_id() {
  _mm_start="${1:-}"
  if [ -n "${MEM_MESH_PROJECT_ID:-}" ]; then
    printf '%s\n' "$MEM_MESH_PROJECT_ID"
    return 0
  fi

  _mm_pid="$(_mm_git "$_mm_start" config --local --get mem-mesh.project-id 2>/dev/null || true)"
  if [ -n "$_mm_pid" ]; then
    printf '%s\n' "$_mm_pid"
    return 0
  fi

  _mm_root="$(_mm_git "$_mm_start" rev-parse --show-toplevel 2>/dev/null || true)"
  if [ -z "$_mm_root" ]; then
    if [ -n "$_mm_start" ] && [ -d "$_mm_start" ]; then
      _mm_root="$(_mm_cd_pwd "$_mm_start")"
    else
      _mm_root="$(pwd)"
    fi
  fi
  _mm_file="${_mm_root}/.mem-mesh/project-id"
  if [ -f "$_mm_file" ]; then
    _mm_pid="$(sed -n '1{s/[[:space:]]*$//;p;}' "$_mm_file" 2>/dev/null || true)"
    if [ -n "$_mm_pid" ]; then
      printf '%s\n' "$_mm_pid"
      return 0
    fi
  fi

  _mm_base="$(basename "$_mm_root" 2>/dev/null || true)"
  if [ -n "$_mm_base" ]; then
    printf '%s\n' "$_mm_base"
  else
    printf '%s\n' "unknown"
  fi
}

_mm_cd_pwd() {
  (cd "$1" 2>/dev/null && pwd) || printf '%s\n' "$1"
}

_mm_git() {
  _mm_git_start="${1:-}"
  shift || true
  if [ -n "$_mm_git_start" ] && [ -d "$_mm_git_start" ]; then
    git -C "$_mm_git_start" "$@"
  else
    git "$@"
  fi
}

mem_mesh_hook_workspace_path() {
  printf '%s' "${1:-}" | jq -r '
    [
      .workspace.current_dir,
      .cwd,
      (if (.workspace_roots // empty) | type == "array" then .workspace_roots[0] else .workspace_roots end),
      (if (.workspaceRoots // empty) | type == "array" then .workspaceRoots[0] else .workspaceRoots end),
      (if (.workspacePaths // empty) | type == "array" then .workspacePaths[0] else .workspacePaths end),
      (if (.workspace_paths // empty) | type == "array" then .workspace_paths[0] else .workspace_paths end),
      .workspacePath,
      .workspace_path,
      .current_dir,
      .project_dir,
      .workspace.project_dir
    ]
    | map(select(type == "string" and . != ""))
    | .[0] // empty
  ' 2>/dev/null || true
}

mem_mesh_project_id_from_input() {
  _mm_input="${1:-}"
  _mm_workspace="$(mem_mesh_hook_workspace_path "$_mm_input")"
  if [ -n "$_mm_workspace" ] && [ -d "$_mm_workspace" ]; then
    mem_mesh_project_id "$_mm_workspace"
  else
    mem_mesh_project_id
  fi
}

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
mem_mesh_log "user-prompt-submit" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "user-prompt-submit" "abort" "jq not found"; exit 0; }
command -v curl >/dev/null 2>&1 || { mem_mesh_log "user-prompt-submit" "abort" "curl not found"; exit 0; }

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
PROJECT_DIR="$(mem_mesh_project_id_from_input "$INPUT")"
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"
PAYLOAD=$(printf '%s' "$INPUT" | jq -c \
  --arg pid "$PROJECT_DIR" \
  --arg source "claude-code-hook" \
  --arg client "claude_code" \
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
