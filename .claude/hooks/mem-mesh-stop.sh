#!/bin/bash
# Stop hook: Claude 응답 완료 시 요약을 mem-mesh에 저장
# stdin: {"stop_hook_active":bool,"last_assistant_message":"..."} JSON

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)

# 무한 루프 방지
ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

# 메시지 추출 + 최소 길이 필터 (짧은 응답은 저장 가치 없음)
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 50 ] && exit 0

# 500자로 자르고 저장
SUMMARY=$(echo "$MESSAGE" | head -c 500)

PAYLOAD=$(jq -n \
  --arg content "[Claude 응답 요약] $SUMMARY" \
  --arg source "claude-code-hook" \
  '{
    content: $content,
    project_id: "mem-mesh",
    category: "git-history",
    source: $source,
    tags: ["auto-save", "conversation"]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "https://meme.24x365.online/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
