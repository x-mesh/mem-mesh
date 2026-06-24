#!/bin/bash
__VERSION_MARKER__
# Kiro agentResponse hook: save response to mem-mesh
# Kiro has LLM access for categorization — no keyword matching needed here.
# Category is set to code_snippet by default; Kiro's LLM handles filtering.

set -euo pipefail
__HOOK_LOG__
mem_mesh_log "response" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "response" "abort" "jq not found"; exit 0; }

API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)"
HOOK_TOKEN="$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)"
AUTH=()
AUTH_STATE=absent
if [ -n "$HOOK_TOKEN" ]; then AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}"); AUTH_STATE=present; fi

RESPONSE="${KIRO_RESULT:-}"
[ ${#RESPONSE} -lt 50 ] && { mem_mesh_log "response" "skip" "too-short len=${#RESPONSE}"; exit 0; }

# Noise guard: skip system artifacts (parity with keywords.is_noise / server _is_noise)
if printf '%s' "$RESPONSE" | grep -qF -e '<task-notification>' -e '</task-notification>' -e '<task-id>' -e '<tool-use-id>' -e '<system-reminder>'; then
  mem_mesh_log "response" "skip" "noise"
  exit 0
fi

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

# Char-safe truncation: jq slices by Unicode codepoint (no UTF-8 byte corruption)
SUMMARY=$(printf '%s' "$RESPONSE" | jq -Rrs '.[0:9500]')

PAYLOAD=$(jq -n \
  --arg content "[kiro response] $SUMMARY" \
  --arg project_id "$PROJECT_DIR" \
  --arg category "code_snippet" \
  --arg source "kiro-hook" \
  --arg client "kiro" \
  '{
    content: $content,
    project_id: $project_id,
    category: $category,
    source: $source,
    client: $client,
    tags: ["auto-save", "kiro"]
  }')

CURL_EXIT=0
HTTP_META=$(curl -s -o /dev/null --max-time 5 -w '%{http_code} %{time_total}' \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null) || CURL_EXIT=$?
HTTP_CODE="${HTTP_META%% *}"
[ -n "$HTTP_CODE" ] || HTTP_CODE="000"
mem_mesh_log "response" "sent" "http=$HTTP_CODE project=$PROJECT_DIR"
mem_mesh_logv "response" "config" "url=$API_URL auth=$AUTH_STATE key=$(mem_mesh_keytail "$HOOK_TOKEN") time=${HTTP_META#* }s curl_exit=$CURL_EXIT"

exit 0
