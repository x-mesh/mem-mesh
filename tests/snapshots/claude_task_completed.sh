#!/bin/bash
# mem-mesh-hooks prompt-version: 31
# TaskCompleted hook → mem-mesh /api/hooks/claude/task-completed
#
# Thin forwarder: the server builds the task summary and saves it. Auth = shared
# hook token (~/.mem-mesh/hook_token). stdin carries task_subject /
# task_description / teammate_name (team-driven); forwarded as-is.

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
# The file is rotated once per hook run (at the "fired" stage) when it passes
# 10 MB: hooks.log -> hooks.log.1, one previous generation kept.
case "${MEM_MESH_HOOK_LOG:-}" in
  ""|0|false|no|off|FALSE|NO|OFF) _MM_LOG=0 ;;
  2|3|debug|DEBUG|verbose|VERBOSE|trace|TRACE) _MM_LOG=2 ;;
  *) _MM_LOG=1 ;;
esac
# Client tag, substituted by the renderer at install time (claude_code).
# Falls back to "hook" when the block is used unrendered (e.g. tests).
_MM_CLIENT="claude_code"
# Kill observability: when the host (Claude Code hook timeout, shell teardown)
# SIGTERMs this hook, the script used to die BEFORE its "sent" log line — the
# failure was invisible in hooks.log, which made timeout kills look like "no
# failure at all" and cost real diagnosis time. The first mem_mesh_log call
# arms a TERM/INT/HUP trap that writes one "killed" line carrying the LAST
# logged stage and the elapsed seconds, then exits 0 (the hook is best-effort;
# the kill is now observable in the log instead of as host-side error noise).
# SIGKILL cannot be trapped — a "fired"/"posting" line without a matching
# "sent"/"killed" line means a hard kill.
_MM_STAGE="init"
_MM_HOOK_NAME=""
_mm_on_kill() {
  trap - TERM INT HUP
  mem_mesh_log "${_MM_HOOK_NAME:-?}" "killed" \
    "signal=$1 last_stage=$_MM_STAGE elapsed=${SECONDS:-?}s"
  exit 0
}
_mm_arm_kill_trap() {
  [ -n "$_MM_HOOK_NAME" ] && return 0
  _MM_HOOK_NAME="$1"
  trap '_mm_on_kill TERM' TERM
  trap '_mm_on_kill INT' INT
  trap '_mm_on_kill HUP' HUP
}
# Delivery over cancel: forwarders that return nothing to the host call this
# right before their POST. A host TERM mid-send (session exit, hook cancel: 330
# of 343 stop-decide kills sat at "posting" with elapsed=0s) only loses the
# event, so from here TERM/HUP are ignored and the kill trap above no longer
# fires for them; curl inherits the ignore. curl --max-time still bounds the
# run (kept below the host timeout), and SIGKILL still ends it — a "posting"
# line with no "sent" line. Hooks whose stdout the host waits on must not use
# this: the host would block on a send it tried to cancel.
mem_mesh_post_shield() {
  trap '' TERM HUP
}
mem_mesh_log() {
  [ "${_MM_LOG:-0}" -ge 1 ] 2>/dev/null || return 0
  _mm_hook="${1:-?}"; _mm_stage="${2:-?}"
  _mm_arm_kill_trap "$_mm_hook"
  _MM_STAGE="$_mm_stage"
  if [ "$#" -gt 2 ]; then shift 2; _mm_detail=" $*"; else _mm_detail=""; fi
  _mm_ts="$(date '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || echo '-')"
  _mm_file="${HOME}/.mem-mesh/hooks.log"
  mkdir -p "${HOME}/.mem-mesh" 2>/dev/null || true
  # Rotation: append-only under a global MEM_MESH_HOOK_LOG=2 the file passed
  # 29 MB (every stage of every client). Checked once per run, at "fired", so
  # the other stages stay a single printf. `wc -c` pads on BSD; keep digits only
  # before the numeric compare. Not atomic across hooks firing in the same
  # second: two can both pass the check and the later mv overwrites .1 with a
  # near-empty file — the previous generation is best-effort for a trace log.
  if [ "$_mm_stage" = "fired" ] && [ -f "$_mm_file" ]; then
    _mm_size="$(wc -c <"$_mm_file" 2>/dev/null || echo 0)"
    _mm_size="${_mm_size//[^0-9]/}"
    if [ "${_mm_size:-0}" -gt 10485760 ] 2>/dev/null; then
      mv -f "$_mm_file" "${_mm_file}.1" 2>/dev/null || true
    fi
  fi
  printf '%s [%s/%s] pid=%s %s%s\n' \
    "$_mm_ts" "${_MM_CLIENT:-hook}" "$_mm_hook" "$$" "$_mm_stage" "$_mm_detail" \
    >>"$_mm_file" 2>/dev/null || true
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
# 4xx/5xx diagnosis: FastAPI returns the validation error in the response body,
# which the forwarders used to discard (-o /dev/null) — a 422 was undiagnosable.
# Level 2 only. Logs each error's loc/msg/type and never its "input" echo (that
# is the rejected value, i.e. turn content); the summary is capped at 300 chars.
mem_mesh_log_http_error() {
  [ "${_MM_LOG:-0}" -ge 2 ] 2>/dev/null || return 0
  _mm_hook="${1:-?}"; _mm_code="${2:-000}"; _mm_body="${3:-}"
  case "$_mm_code" in 4[0-9][0-9]|5[0-9][0-9]) ;; *) return 0 ;; esac
  [ -n "$_mm_body" ] || return 0
  _mm_err="$(printf '%s' "$_mm_body" | jq -c '
    if (.detail | type) == "array" then [.detail[] | {loc, msg, type}]
    elif (.detail | type) == "string" then {detail}
    else {keys: keys} end' 2>/dev/null | head -c 300)" || _mm_err=""
  [ -n "$_mm_err" ] || _mm_err="non-json body bytes=${#_mm_body}"
  mem_mesh_log "$_mm_hook" "error" "http=$_mm_code $_mm_err"
}
mem_mesh_log "task-completed" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "task-completed" "abort" "jq not found"; exit 0; }
command -v curl >/dev/null 2>&1 || { mem_mesh_log "task-completed" "abort" "curl not found"; exit 0; }

API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo https://meme.24x365.online)"
HOOK_TOKEN="$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)"
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

CURL_EXIT=0
# Shield the send, then leave a verbose breadcrumb: from here a host TERM is
# ignored so the event still lands (see mem_mesh_post_shield); a "posting"
# line with no "sent" line therefore means a hard kill.
mem_mesh_post_shield
mem_mesh_logv "task-completed" "posting"
HTTP_META=$(curl -s -o /dev/null --max-time 8 -w '%{http_code} %{time_total}' \
  -X POST "${API_URL}/api/hooks/claude/task-completed" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null) || CURL_EXIT=$?
HTTP_CODE="${HTTP_META%% *}"
[ -n "$HTTP_CODE" ] || HTTP_CODE="000"
mem_mesh_log "task-completed" "sent" "http=$HTTP_CODE project=$PROJECT_DIR"
mem_mesh_logv "task-completed" "config" "url=$API_URL auth=$AUTH_STATE key=$(mem_mesh_keytail "$HOOK_TOKEN") time=${HTTP_META#* }s curl_exit=$CURL_EXIT"

exit 0
