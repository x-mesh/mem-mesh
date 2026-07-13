#!/bin/bash
__VERSION_MARKER__
# Claude Code PreToolUse hook → mem-mesh /api/hooks/claude/pre-tool-use
#
# Cross-project context injection. Before an edit lands on a contract surface
# (OpenAPI spec, schema, .env, auth, ports, compose), this asks the server what
# the PEER project already recorded, and injects the answer.
#
# It does not tell the model to go search — a prose rule is what does NOT fire
# (the anchors rule, explicitly mandated in the hook prompt, sits at 0%
# compliance across 15k code-tied memories). The runtime fires on the path and
# hands the model facts.
#
# Opt-in and silent by default: with no .mem-mesh/cross-project.json holding
# peers, this exits immediately and costs nothing.

set -euo pipefail
__PROJECT_ID_RESOLVER__
__HOOK_LOG__

command -v jq >/dev/null 2>&1 || { exit 0; }
command -v curl >/dev/null 2>&1 || { exit 0; }

INPUT=$(cat)

TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // .toolName // ""' 2>/dev/null || true)"
FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .toolInput.file_path // .tool_input.filePath // ""' 2>/dev/null || true)"
[ -n "$FILE_PATH" ] || exit 0

CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // ""' 2>/dev/null || true)"
[ -n "$CWD" ] && [ -d "$CWD" ] || CWD="$PWD"

# Config lives with the repo, not on the server: the peer set is a property of
# this checkout, and the council rejected a server-side project_links table.
CONFIG=""
SEARCH_DIR="$CWD"
for _ in 1 2 3 4 5 6; do
  if [ -f "$SEARCH_DIR/.mem-mesh/cross-project.json" ]; then
    CONFIG="$SEARCH_DIR/.mem-mesh/cross-project.json"
    break
  fi
  [ "$SEARCH_DIR" = "/" ] && break
  SEARCH_DIR="$(dirname "$SEARCH_DIR")"
done
[ -n "$CONFIG" ] || exit 0

PEERS="$(jq -c '.peers // []' "$CONFIG" 2>/dev/null || echo '[]')"
[ "$PEERS" != "[]" ] || exit 0
GLOBS="$(jq -c '.globs // []' "$CONFIG" 2>/dev/null || echo '[]')"

mem_mesh_log "pre-tool-use" "fired" "file=$FILE_PATH peers=$PEERS"

API_URL="$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)"
HOOK_TOKEN="$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)"
AUTH=()
if [ -n "$HOOK_TOKEN" ]; then
  AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}")
fi

PROJECT_DIR="$(cd "$CWD" 2>/dev/null && mem_mesh_project_id || true)"
[ -n "$PROJECT_DIR" ] || PROJECT_DIR="$(mem_mesh_project_id)"
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"

PAYLOAD=$(printf '%s' "$INPUT" | jq -c \
  --arg pid "$PROJECT_DIR" \
  --arg tool "$TOOL_NAME" \
  --arg file "$FILE_PATH" \
  --arg source "__SOURCE_TAG__" \
  --arg client "__CLIENT_TAG__" \
  --argjson peers "$PEERS" \
  --argjson globs "$GLOBS" \
  '{
    project_id: $pid,
    tool_name: $tool,
    file_path: $file,
    peers: $peers,
    globs: $globs,
    hook_source: $source,
    client: $client,
    cwd: (.cwd // ""),
    session_id: (.session_id // .sessionId // "")
  }' 2>/dev/null) || exit 0

# The edit must not wait on this: a slow/dead server degrades to "no injection",
# never to a stalled tool call.
RESP=$(curl -s --max-time 5 \
  -X POST "${API_URL}/api/hooks/claude/pre-tool-use" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null) || RESP=""

# Server returns hookSpecificOutput on a hit, an empty body on a no-op.
if [ -n "$RESP" ] && printf '%s' "$RESP" | jq -e '.hookSpecificOutput.additionalContext' >/dev/null 2>&1; then
  mem_mesh_log "pre-tool-use" "injected" "file=$FILE_PATH"
  printf '%s\n' "$RESP"
else
  mem_mesh_log "pre-tool-use" "noop" "file=$FILE_PATH"
fi

exit 0
