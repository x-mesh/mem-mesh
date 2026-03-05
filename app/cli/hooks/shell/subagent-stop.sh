#!/bin/bash
__VERSION_MARKER__
# SubagentStop hook: auto-save important subagent results
# stdin: {stop_hook_active, agent_id, agent_type, last_assistant_message, ...}
# Reuses keyword matching logic from stop-decide

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

INPUT=$(cat)

# Guard: prevent loop
ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 100 ] && exit 0

# Already saved via MCP
echo "$MESSAGE" | grep -q 'mcp__mem-mesh__add' && exit 0

# Keyword decision (injected from keywords.py at install time)
CATEGORY=$(python3 -c "
__KEYWORD_MATCHER__
" <<< "$MESSAGE" 2>/dev/null) || CATEGORY="SKIP"

[ "$CATEGORY" = "SKIP" ] && exit 0

# Build content with agent type prefix
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // "unknown"')
CONTENT="[${AGENT_TYPE} agent] ${MESSAGE}"
CONTENT=$(echo "$CONTENT" | head -c 9500)

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

PAYLOAD=$(jq -n \
  --arg content "$CONTENT" \
  --arg project_id "$PROJECT_DIR" \
  --arg category "$CATEGORY" \
  --arg source "__SOURCE_TAG__" \
  --arg client "__CLIENT_TAG__" \
  '{
    content: $content,
    project_id: $project_id,
    category: $category,
    source: $source,
    client: $client,
    tags: ["auto-save", "subagent", $category]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
