"""Single source of truth for the opt-in shell-hook logging block.

The forwarder hooks (``shell/*.sh``) swallow every failure silently
(``2>/dev/null``, ``|| true``, ``command -v jq || exit 0``), so when a hook
"doesn't fire" there is no signal telling you which stage failed: jq/curl
missing, server down, auth 401, or an 8-second timeout. This block adds opt-in
observability.

The block is injected into every instrumented template via the ``__HOOK_LOG__``
placeholder at install time — the same single-source pattern used for
``__KEYWORD_MATCHER__`` (see ``keywords.py``). It defines a ``mem_mesh_log``
shell function that appends one timestamped line per stage to
``~/.mem-mesh/hooks.log`` **only** when ``MEM_MESH_HOOK_LOG`` is set to a truthy
value. Unset / ``0`` / ``false`` is a no-op with zero overhead, so installed
hooks behave exactly as before unless the user opts in.

Usage inside a template::

    set -euo pipefail
    __HOOK_LOG__
    mem_mesh_log "stop" "fired" "cwd=$PWD"
    command -v jq >/dev/null 2>&1 || { mem_mesh_log "stop" "abort" "jq missing"; exit 0; }
    ...
    mem_mesh_log "stop" "sent" "http=$HTTP_CODE"

Design notes
------------
* **Pure bash** — uses only builtins plus ``date``/``mkdir``; it must run before
  the jq/curl availability checks so a missing dependency is itself logged.
* **``set -e`` safe** — every call returns 0 (the gate uses ``|| return 0`` and
  the final ``printf`` is guarded with ``|| true``) so logging never aborts a
  hook.
* **Namespaced vars** (``_MM_LOG`` / ``_mm_*``) avoid colliding with template
  variables (INPUT, PAYLOAD, RESP, ...). No ``__TOKEN__`` substrings, so the
  renderer's unresolved-placeholder guard stays happy.
* **Fixed path** ``~/.mem-mesh/hooks.log`` — alongside the existing
  ``~/.mem-mesh/{api_url,hook_token}`` files.
"""

# NOTE: no leading/trailing newline — the placeholder occupies its own line in
# the template, so the surrounding newlines come from the .sh source.
HOOK_LOG_BLOCK = r"""# --- mem-mesh hook logging (opt-in: MEM_MESH_HOOK_LOG) -------------------------
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
# Client tag, substituted by the renderer at install time (__CLIENT_TAG__).
# Falls back to "hook" when the block is used unrendered (e.g. tests).
_MM_CLIENT="__CLIENT_TAG__"
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
}"""
