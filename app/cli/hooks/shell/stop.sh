#!/bin/bash
__VERSION_MARKER__
# Stop hook: save conversation summary to mem-mesh
# stdin: {"stop_hook_active":bool,"last_assistant_message":"..."} JSON

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)}"

INPUT=$(cat)

# Prevent infinite loop
ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

# Extract message + minimum length filter (>=100 to match server min_content_length)
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 100 ] && exit 0

# Noise guard: even the unconditional-save minimal profile must skip system
# artifacts (parity with keywords.is_noise / server _is_noise).
if printf '%s' "$MESSAGE" | grep -qF -e '<task-notification>' -e '</task-notification>' -e '<task-id>' -e '<tool-use-id>' -e '<system-reminder>'; then
  exit 0
fi

# Char-safe truncation: jq slices by Unicode codepoint (no UTF-8 byte corruption)
SUMMARY=$(printf '%s' "$MESSAGE" | jq -Rrs '.[0:9500]')

# Extract project ID from CWD
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

PAYLOAD=$(jq -n \
  --arg content "[conversation summary] $SUMMARY" \
  --arg project_id "$PROJECT_DIR" \
  --arg source "__SOURCE_TAG__" \
  --arg client "__CLIENT_TAG__" \
  '{
    content: $content,
    project_id: $project_id,
    category: "git-history",
    source: $source,
    client: $client,
    tags: ["auto-save", "conversation", "__IDE_TAG__"]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
