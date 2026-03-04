#!/bin/bash
# mem-mesh-hooks prompt-version: 10
# Kiro agentResponse hook: keyword-based category matching + save to mem-mesh

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-https://meme.24x365.online}"

RESPONSE="${KIRO_RESULT:-}"
[ ${#RESPONSE} -lt 50 ] && exit 0

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

# Keyword decision (same logic as Claude Code stop-decide)
CATEGORY=$(python3 -c "
import sys, re
msg = sys.stdin.read().lower()

save_rules = [
    (r'(버그|bug).*(수정|fix|해결|resolved|patch)', 'bug'),
    (r'(수정|fix).*(버그|bug|에러|error|오류)', 'bug'),
    (r'(에러|error|exception|오류).*(해결|수정|fixed|resolved)', 'bug'),
    (r'(결정|decision).*(변경|선택|채택|chose|decided)', 'decision'),
    (r'(아키텍처|architecture|설계).*(결정|변경|선택)', 'decision'),
    (r'(전환|migration|마이그레이션)', 'decision'),
    (r'(구현|implement).*(완료|했습니다|done)', 'code_snippet'),
    (r'(장애|incident|outage).*(발생|occurred|detected)', 'incident'),
    (r'(아이디어|idea).*(제안|suggest|고려|consider)', 'idea'),
]

for pat, cat in save_rules:
    if re.search(pat, msg):
        print(cat)
        sys.exit(0)

print('SKIP')
" <<< "$RESPONSE" 2>/dev/null) || CATEGORY="SKIP"

# No keyword match -> skip saving (M3: task is system-only category)
[ "$CATEGORY" = "SKIP" ] && exit 0

SUMMARY=$(echo "$RESPONSE" | head -c 9500)

PAYLOAD=$(jq -n \
  --arg content "[kiro response] $SUMMARY" \
  --arg project_id "$PROJECT_DIR" \
  --arg category "$CATEGORY" \
  --arg source "kiro-hook" \
  --arg client "kiro" \
  '{
    content: $content,
    project_id: $project_id,
    category: $category,
    source: $source,
    client: $client,
    tags: ["auto-save", "keyword", $category, "kiro"]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
