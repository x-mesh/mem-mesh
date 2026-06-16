#!/bin/bash
# mem-mesh-hooks prompt-version: 16
# Claude Code SessionStart hook → mem-mesh /api/hooks/claude/session-start
#
# Thin forwarder: POST the raw hook event; the server resumes context, detects
# continuation (from the event stream, not the local transcript), and renders
# the rules block — returning hookSpecificOutput. Auth is the shared hook token
# (MEM_MESH_HOOK_TOKEN env, falling back to ~/.mem-mesh/hook_token) so every
# client authenticates against verify_hook_token uniformly.

set -euo pipefail
command -v jq >/dev/null 2>&1 || { echo '{}'; exit 0; }
command -v curl >/dev/null 2>&1 || { echo '{}'; exit 0; }

API_URL="${MEM_MESH_API_URL:-$(cat ~/.mem-mesh/api_url 2>/dev/null || echo https://meme.24x365.online)}"
HOOK_TOKEN="${MEM_MESH_HOOK_TOKEN:-$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)}"
AUTH=()
if [ -n "$HOOK_TOKEN" ]; then
  AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}")
fi

INPUT=$(cat)

# Explicit project_id (git toplevel basename); the server falls back to
# basename(cwd) but this is more accurate for worktrees.
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"
PAYLOAD=$(printf '%s' "$INPUT" | jq -c --arg pid "$PROJECT_DIR" '. + {project_id: $pid}' 2>/dev/null) || PAYLOAD="$INPUT"

RESP=$(curl -s --max-time 8 \
  -X POST "${API_URL}/api/hooks/claude/session-start" \
  -H "Content-Type: application/json" \
  ${AUTH[@]+"${AUTH[@]}"} \
  -d "$PAYLOAD" 2>/dev/null) || RESP=""

# Server returns hookSpecificOutput JSON, or an empty body on no-op. Emit valid
# JSON verbatim; fall back to {} so Claude Code's output schema check passes.
if printf '%s' "$RESP" | jq -e . >/dev/null 2>&1; then
  printf '%s\n' "$RESP"
else
  echo '{}'
fi
