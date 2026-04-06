#!/bin/bash
# mem-mesh-hooks prompt-version: 13
# Kiro agentResponse hook: save response to mem-mesh
# Kiro has LLM access for categorization — no keyword matching needed here.
# Category is set to code_snippet by default; Kiro's LLM handles filtering.

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-https://meme.24x365.online}"

RESPONSE="${KIRO_RESULT:-}"
[ ${#RESPONSE} -lt 50 ] && exit 0

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

SUMMARY=$(echo "$RESPONSE" | head -c 9500)

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

curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
