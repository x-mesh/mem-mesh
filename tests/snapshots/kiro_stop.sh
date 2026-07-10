#!/bin/bash
# mem-mesh-hooks prompt-version: 28
# Agent response hook: save response to mem-mesh.
# Used by Kiro and other command-hook clients that provide the final response
# through an environment variable or stdin JSON.

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
# Client tag, substituted by the renderer at install time (kiro).
# Falls back to "hook" when the block is used unrendered (e.g. tests).
_MM_CLIENT="kiro"
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
mem_mesh_log() {
  [ "${_MM_LOG:-0}" -ge 1 ] 2>/dev/null || return 0
  _mm_hook="${1:-?}"; _mm_stage="${2:-?}"
  _mm_arm_kill_trap "$_mm_hook"
  _MM_STAGE="$_mm_stage"
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
mem_mesh_log "response" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "response" "abort" "jq not found"; exit 0; }

API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo https://meme.24x365.online)"
HOOK_TOKEN="$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)"
AUTH=()
AUTH_STATE=absent
if [ -n "$HOOK_TOKEN" ]; then AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}"); AUTH_STATE=present; fi

RAW_INPUT="$(cat)"
HOOK_WORKSPACE_PATH="$(printf '%s' "$RAW_INPUT" | jq -r '
  [.workspacePaths, .workspace_paths, .workspacePath, .workspace_path, .cwd]
  | map(if type == "array" then .[0] elif type == "string" then . else empty end)
  | map(select(. != null and . != ""))
  | .[0] // empty
' 2>/dev/null || true)"
RESPONSE="${KIRO_RESULT:-}"
if [ -z "$RESPONSE" ]; then
  RESPONSE="$(printf '%s' "$RAW_INPUT" | jq -r '
    .response
    // .assistant_response
    // .agentResponse
    // .assistantResponse
    // .lastAssistantMessage
    // .last_assistant_message
    // .result
    // .content
    // .text
    // empty
  ' 2>/dev/null || true)"
fi
if [ -z "$RESPONSE" ]; then
  TRANSCRIPT_PATH="$(printf '%s' "$RAW_INPUT" | jq -r '.transcriptPath // empty' 2>/dev/null || true)"
  if [ -n "$TRANSCRIPT_PATH" ] && [ -r "$TRANSCRIPT_PATH" ]; then
    RESPONSE="$(jq -rs '
      [.[] | select(.source == "MODEL" and ((.content // "") != "")) | .content]
      | last // empty
    ' "$TRANSCRIPT_PATH" 2>/dev/null || true)"
  fi
fi
if [ -z "$RESPONSE" ] && [ -n "$RAW_INPUT" ]; then
  RESPONSE="$(printf '%s' "$RAW_INPUT" | jq -c . 2>/dev/null || printf '%s' "$RAW_INPUT")"
fi
[ ${#RESPONSE} -lt 100 ] && { mem_mesh_log "response" "skip" "too-short len=${#RESPONSE}"; exit 0; }

# Noise guard: skip system artifacts (parity with keywords.is_noise / server _is_noise)
if printf '%s' "$RESPONSE" | grep -qF -e '<task-notification>' -e '</task-notification>' -e '<task-id>' -e '<tool-use-id>' -e '<system-reminder>'; then
  mem_mesh_log "response" "skip" "noise"
  exit 0
fi

# Noise guard: skip only the raw Kiro hook envelope. The raw-input fallback above
# dumps it verbatim when no response field could be extracted; it carries no
# assistant content, only transport metadata (hook_event_name/cwd/...). Genuine
# assistant output that happens to be JSON — panel verdicts, code-review findings —
# holds real, FTS-searchable text and MUST be saved ("Kiro's LLM handles filtering").
if printf '%s' "$RESPONSE" | jq -e 'type == "object" and has("hook_event_name")' >/dev/null 2>&1; then
  mem_mesh_log "response" "skip" "hook-envelope"
  exit 0
fi

# Content-quality guard: some clients (notably agy/Antigravity) fire Stop on every
# turn, so trivial output that clears the 100-char length gate still reaches here.
# Two precise, low-false-positive skips — they must NOT catch genuine responses
# (prose, code, panel verdicts, review findings), only obvious non-work output:
#   1. Repetitive padding — a run of 30+ identical chars (e.g. a probe padded "xxxx…").
#   2. Model-identity banner — a short session greeting like "You are currently using <model>…".
if printf '%s' "$RESPONSE" | jq -Rrse 'test("(.)\\1{29,}")' >/dev/null 2>&1; then
  mem_mesh_log "response" "skip" "low-value-padding"
  exit 0
fi
if [ ${#RESPONSE} -lt 300 ] && printf '%s' "$RESPONSE" | head -c 160 | grep -qiE "^[[:space:]]*[*_ ]*you('re| are) (currently )?using[[:space:]*_]+(gemini|gpt|chatgpt|claude|opus|sonnet|haiku)"; then
  mem_mesh_log "response" "skip" "model-banner"
  exit 0
fi

# Readability transform: panel/review runs on kiro/agy emit their final answer
# as a raw findings JSON envelope, sometimes ```json-fenced. Saved verbatim it
# is a one-line unreadable blob. Render it as markdown — one bullet per finding
# with severity/file:line/claim/evidence — so the stored memory reads and
# FTS-searches as prose. Non-envelope JSON and normal prose pass through as-is.
_MM_BODY="$(printf '%s\n' "$RESPONSE" | sed -e '1{/^[[:space:]]*```[a-zA-Z]*[[:space:]]*$/d;}' -e '${/^[[:space:]]*```[[:space:]]*$/d;}')"
_MM_FINDINGS_MD="$(printf '%s' "$_MM_BODY" | jq -r '
  select(type == "object" and (.findings | type == "array") and (.findings | length > 0))
  | "## Review findings (\(.findings | length))\n\n" +
    ([ .findings[]
       | "- [\(.severity // "?")] `\(.file // "?")\(if .line != null then ":\(.line)" else "" end)` — \(.claim // .summary // .title // "")"
         + (if (.evidence // "") != "" then "\n  - evidence: \(.evidence | gsub("[\\n\\r]+"; " "))" else "" end)
     ] | join("\n"))
' 2>/dev/null || true)"
if [ -n "$_MM_FINDINGS_MD" ]; then
  mem_mesh_log "response" "transform" "findings-envelope -> markdown"
  RESPONSE="$_MM_FINDINGS_MD"
fi

PROJECT_DIR="$(mem_mesh_project_id_from_input "$RAW_INPUT")"
[ -n "$PROJECT_DIR" ] || PROJECT_DIR="unknown"
# agy spawns its hooks from ~/.gemini/... (not the caller's directory), and a
# print-mode run without a registered workspace sends workspacePaths: [] — the
# cwd fallback then misfiles every memory under "config". When the envelope
# carried no workspace and we're running out of the client's own config tree,
# "unknown" is the honest project id.
if [ -z "$HOOK_WORKSPACE_PATH" ]; then
  case "$PWD" in
    "$HOME/.gemini"|"$HOME/.gemini/"*) PROJECT_DIR="unknown" ;;
  esac
fi

# Char-safe truncation: jq slices by Unicode codepoint (no UTF-8 byte corruption)
SUMMARY=$(printf '%s' "$RESPONSE" | jq -Rrs '.[0:9500]')

PAYLOAD=$(jq -n \
  --arg content "[kiro response] $SUMMARY" \
  --arg project_id "$PROJECT_DIR" \
  --arg category "code_snippet" \
  --arg source "kiro-hook" \
  --arg client "kiro" \
  --arg ide "kiro" \
  '{
    content: $content,
    project_id: $project_id,
    category: $category,
    source: $source,
    client: $client,
    tags: ["auto-save", $ide]
  }')

CURL_EXIT=0
# 8s (not 5): the remote API occasionally exceeds 5s right after a deploy
# reload — a lost save (curl_exit=28) costs more than three extra seconds.
# Stays under agy's 10s Stop-hook budget.
# Verbose breadcrumb BEFORE the network send: if the host kills this hook
# mid-curl, the kill trap logs last_stage=posting — the exact stalled stage.
mem_mesh_logv "response" "posting"
HTTP_META=$(curl -s -o /dev/null --max-time 8 -w '%{http_code} %{time_total}' \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null) || CURL_EXIT=$?
HTTP_CODE="${HTTP_META%% *}"
[ -n "$HTTP_CODE" ] || HTTP_CODE="000"
mem_mesh_log "response" "sent" "http=$HTTP_CODE project=$PROJECT_DIR"
mem_mesh_logv "response" "config" "url=$API_URL auth=$AUTH_STATE key=$(mem_mesh_keytail "$HOOK_TOKEN") time=${HTTP_META#* }s curl_exit=$CURL_EXIT"

exit 0
