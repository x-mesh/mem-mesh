#!/bin/bash
# PostToolUse hook: 코드 변경사항을 mem-mesh에 자동 기록
# stdin: {"tool_name":"Write|Edit","tool_input":{...}} JSON

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE_PATH" ] && exit 0

# 대상 파일 타입만 추적
case "$FILE_PATH" in
  *.py|*.ts|*.js|*.jsx|*.tsx|*.json|*.md|*.yaml|*.yml|*.toml|*.sh) ;;
  *) exit 0 ;;
esac

# .claude/ 내부 파일은 제외 (hook 자체 수정 등)
case "$FILE_PATH" in
  */.claude/*) exit 0 ;;
esac

# 프로젝트 ID 추출 (디렉토리명 기반)
PROJECT_DIR=$(echo "$FILE_PATH" | sed 's|.*/project/||;s|/.*||')
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"

# 변경 내용 요약 구성
if [ "$TOOL_NAME" = "Write" ]; then
  PREVIEW=$(echo "$INPUT" | jq -r '.tool_input.content // empty' | head -c 300)
  CONTENT="파일: ${FILE_PATH}\n변경: 새 파일 작성 또는 전체 덮어쓰기\n내용: ${PREVIEW}"
elif [ "$TOOL_NAME" = "Edit" ]; then
  OLD=$(echo "$INPUT" | jq -r '.tool_input.old_string // empty' | head -c 150)
  NEW=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty' | head -c 150)
  CONTENT="파일: ${FILE_PATH}\n변경: '${OLD}' → '${NEW}'\n이유: 코드 수정"
else
  exit 0
fi

# 최소 길이 검증 (API 요구: 10자 이상)
[ ${#CONTENT} -lt 15 ] && exit 0

# 파일 확장자로 태그 결정
EXT="${FILE_PATH##*.}"

PAYLOAD=$(jq -n \
  --arg content "$CONTENT" \
  --arg project_id "$PROJECT_DIR" \
  --arg source "claude-code-hook" \
  --arg ext "$EXT" \
  '{
    content: $content,
    project_id: $project_id,
    category: "code_snippet",
    source: $source,
    tags: ["auto-save", "file-change", $ext]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "https://meme.24x365.online/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
