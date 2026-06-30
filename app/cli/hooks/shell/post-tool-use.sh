#!/bin/bash
__VERSION_MARKER__
# Claude Code PostToolUse hook → mem-mesh /api/hooks/claude/post-tool-use
#
# Write-signal recorder (fire-and-forget). After a file-mutating tool runs, this
# tells the server "real work happened this turn". The server uses that signal
# to gate the pin/save reminders so they fire only after an actual edit — never
# on a read-only question/analysis turn. Settings install this hook with a
# matcher restricted to write tools, and the server re-checks the tool name, so
# non-write tools are ignored on both sides. Auth = shared hook token.

set -euo pipefail
__PROJECT_ID_RESOLVER__
__HOOK_LOG__
mem_mesh_log "post-tool-use" "fired" "cwd=$PWD"
command -v jq >/dev/null 2>&1 || { mem_mesh_log "post-tool-use" "abort" "jq not found"; exit 0; }
command -v curl >/dev/null 2>&1 || { mem_mesh_log "post-tool-use" "abort" "curl not found"; exit 0; }

API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)"
HOOK_TOKEN="$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)"
AUTH=()
AUTH_STATE=absent
if [ -n "$HOOK_TOKEN" ]; then
  AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}")
  AUTH_STATE=present
fi

INPUT=$(cat)
HOOK_WORKSPACE_PATH="$(printf '%s' "$INPUT" | jq -r '
  [.workspacePaths, .workspace_paths, .workspacePath, .workspace_path, .cwd]
  | map(if type == "array" then .[0] elif type == "string" then . else empty end)
  | map(select(. != null and . != ""))
  | .[0] // empty
' 2>/dev/null || true)"
PROJECT_DIR=""
if [ -n "$HOOK_WORKSPACE_PATH" ] && [ -d "$HOOK_WORKSPACE_PATH" ]; then
  PROJECT_DIR="$(cd "$HOOK_WORKSPACE_PATH" 2>/dev/null && mem_mesh_project_id || true)"
fi
[ -n "$PROJECT_DIR" ] || PROJECT_DIR="$(mem_mesh_project_id)"
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"
PAYLOAD=$(printf '%s' "$INPUT" | jq -c \
  --arg pid "$PROJECT_DIR" \
  --arg source "__SOURCE_TAG__" \
  --arg client "__CLIENT_TAG__" \
  '
  def mem_mesh_tool_name:
    (.tool_name
      // .toolName
      // .toolCall.tool_name
      // .toolCall.toolName
      // .toolCall.name
      // .tool_call.tool_name
      // .tool_call.toolName
      // .tool_call.name
      // ""
    ) as $name
    | ($name | tostring | ascii_downcase) as $lower
    | if $lower == "write_to_file" or $lower == "write" then "Write"
      elif $lower == "replace_file_content" or $lower == "edit" then "Edit"
      elif $lower == "multi_replace_file_content" or $lower == "multiedit" or $lower == "multi_edit" then "MultiEdit"
      elif $lower == "notebookedit" or $lower == "notebook_edit" then "NotebookEdit"
      else ($name | tostring)
      end;

  . + {
    project_id: $pid,
    hook_source: $source,
    client: $client,
    session_id: (.session_id // .sessionId // .conversation_id // .conversationId // .conversationID // .session.id // ""),
    tool_name: mem_mesh_tool_name
  }' 2>/dev/null) || PAYLOAD="$INPUT"

# Validate that PAYLOAD is a non-empty valid JSON object, and contains a valid tool_name.
# Otherwise skip curl to avoid 422 errors on empty/malformed inputs.
VALID_JSON=$(printf '%s' "$PAYLOAD" | jq -e 'select(.tool_name != null and .tool_name != "")' 2>/dev/null || true)
if [ -z "$VALID_JSON" ]; then
  mem_mesh_log "post-tool-use" "skip" "empty-or-invalid-payload"
  exit 0
fi

# Fire-and-forget: never block the session on the write-signal POST.
CURL_EXIT=0
HTTP_META=$(curl -s -o /dev/null --max-time 5 -w '%{http_code} %{time_total}' \
  -X POST "${API_URL}/api/hooks/claude/post-tool-use" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null) || CURL_EXIT=$?
HTTP_CODE="${HTTP_META%% *}"
[ -n "$HTTP_CODE" ] || HTTP_CODE="000"
mem_mesh_log "post-tool-use" "sent" "http=$HTTP_CODE project=$PROJECT_DIR"
mem_mesh_logv "post-tool-use" "config" "url=$API_URL auth=$AUTH_STATE key=$(mem_mesh_keytail "$HOOK_TOKEN") time=${HTTP_META#* }s curl_exit=$CURL_EXIT"

exit 0
