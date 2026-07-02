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
}"""
