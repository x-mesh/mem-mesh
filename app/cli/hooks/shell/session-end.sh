#!/bin/bash
__VERSION_MARKER__
# Claude Code SessionEnd hook: auto-end mem-mesh session via API
# Fires when the user closes the session or exits Claude Code
# Non-blocking: exits 0 on failure to avoid disrupting the IDE

set -euo pipefail
__PROJECT_ID_RESOLVER__
__HOOK_LOG__
mem_mesh_log "session-end" "fired" "cwd=$PWD"
command -v curl >/dev/null 2>&1 || { mem_mesh_log "session-end" "abort" "curl not found"; exit 0; }

API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)"
HOOK_TOKEN="$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)"
AUTH=()
AUTH_STATE=absent
if [ -n "$HOOK_TOKEN" ]; then AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}"); AUTH_STATE=present; fi

# Resolve the stable project id.
PROJECT_DIR="$(mem_mesh_project_id)"
[ -z "$PROJECT_DIR" ] && { mem_mesh_log "session-end" "abort" "no project dir"; exit 0; }

# End the most recent active session for this project
CURL_EXIT=0
HTTP_META=$(curl -s -o /dev/null --max-time 5 -w '%{http_code} %{time_total}' \
  -X POST "${API_URL}/api/work/sessions/end-by-project/${PROJECT_DIR}" \
  ${AUTH[@]+"${AUTH[@]}"} \
  2>/dev/null) || CURL_EXIT=$?
HTTP_CODE="${HTTP_META%% *}"
[ -n "$HTTP_CODE" ] || HTTP_CODE="000"
mem_mesh_log "session-end" "sent" "http=$HTTP_CODE project=$PROJECT_DIR"
mem_mesh_logv "session-end" "config" "url=$API_URL auth=$AUTH_STATE key=$(mem_mesh_keytail "$HOOK_TOKEN") time=${HTTP_META#* }s curl_exit=$CURL_EXIT"

exit 0
