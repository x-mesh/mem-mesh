#!/bin/bash
__VERSION_MARKER__
# Agent response hook: save response to mem-mesh.
# Used by Kiro and other command-hook clients that provide the final response
# through an environment variable or stdin JSON.

set -euo pipefail
__PROJECT_ID_RESOLVER__
__HOOK_LOG__
mem_mesh_log "response" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "response" "abort" "jq not found"; exit 0; }

API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)"
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

PROJECT_DIR="$(mem_mesh_project_id_from_input "$RAW_INPUT")"
[ -n "$PROJECT_DIR" ] || PROJECT_DIR="unknown"

# Char-safe truncation: jq slices by Unicode codepoint (no UTF-8 byte corruption)
SUMMARY=$(printf '%s' "$RESPONSE" | jq -Rrs '.[0:9500]')

PAYLOAD=$(jq -n \
  --arg content "[__IDE_TAG__ response] $SUMMARY" \
  --arg project_id "$PROJECT_DIR" \
  --arg category "code_snippet" \
  --arg source "__SOURCE_TAG__" \
  --arg client "__CLIENT_TAG__" \
  --arg ide "__IDE_TAG__" \
  '{
    content: $content,
    project_id: $project_id,
    category: $category,
    source: $source,
    client: $client,
    tags: ["auto-save", $ide]
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
