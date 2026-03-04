#!/bin/bash
# mem-mesh-hooks prompt-version: 11
# TaskCompleted hook: auto-save completed tasks to mem-mesh
# stdin: {task_id, task_subject, task_description, teammate_name, team_name, ...}

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-https://meme.24x365.online}"

INPUT=$(cat)
TASK_SUBJECT=$(echo "$INPUT" | jq -r '.task_subject // empty')
TASK_DESC=$(echo "$INPUT" | jq -r '.task_description // empty')
TEAMMATE=$(echo "$INPUT" | jq -r '.teammate_name // empty')

[ -z "$TASK_SUBJECT" ] && exit 0

# Build content
CONTENT="## Task Completed: ${TASK_SUBJECT}"
[ -n "$TASK_DESC" ] && CONTENT="${CONTENT}\n\n${TASK_DESC}"
[ -n "$TEAMMATE" ] && CONTENT="${CONTENT}\n\nCompleted by: ${TEAMMATE}"
CONTENT=$(printf '%b' "$CONTENT" | head -c 5000)

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

PAYLOAD=$(jq -n \
  --arg content "$CONTENT" \
  --arg project_id "$PROJECT_DIR" \
  --arg source "claude-code-hook" \
  --arg client "claude_code" \
  '{
    content: $content,
    project_id: $project_id,
    category: "task",
    source: $source,
    client: $client,
    tags: ["auto-save", "task-completed"]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
