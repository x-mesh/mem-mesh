#!/bin/bash
# mem-mesh-hooks prompt-version: 10
# Stop hook: keyword-based category matching + structured save (요약+원본)
# stdin: {"stop_hook_active":bool,"last_assistant_message":"...","transcript_path":"..."} JSON
# No LLM, no API key — regex keyword matching, skip if no match

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-https://meme.24x365.online}"

INPUT=$(cat)

# Guard: prevent infinite loop
ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

# Extract fields
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
[ ${#MESSAGE} -lt 50 ] && exit 0

# Already saved via MCP
echo "$MESSAGE" | grep -q 'mcp__mem-mesh__add' && exit 0

# Keyword decision (regex matching, SAVE patterns first)
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
" <<< "$MESSAGE" 2>/dev/null) || CATEGORY="SKIP"

# No keyword match -> skip saving (M3: task is system-only category)
[ "$CATEGORY" = "SKIP" ] && exit 0

# Build content: Q&A from transcript + answer (no LLM summary)
CONTENT=$(python3 -c "
import sys, json

message = sys.argv[1]
transcript_path = sys.argv[2]

# Extract last user question from transcript
# Claude Code JSONL format: {type:'user', message:{role:'user', content:'...'}}
user_question = ''
if transcript_path:
    try:
        with open(transcript_path, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get('type') == 'user':
                        msg = entry.get('message', {})
                        content = msg.get('content', '')
                        if isinstance(content, list):
                            texts = [c.get('text','') for c in content if c.get('type')=='text']
                            content = ' '.join(texts)
                        if isinstance(content, str) and len(content.strip()) > 5:
                            user_question = content.strip()[:500]
                except:
                    pass
    except:
        pass

if user_question:
    print(f'Q: {user_question}\n\nA: {message[:9000]}'[:9500])
else:
    print(message[:9500])
" "$MESSAGE" "$TRANSCRIPT_PATH" 2>/dev/null) || CONTENT="$MESSAGE"

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

# Save to mem-mesh API
PAYLOAD=$(jq -n \
  --arg content "$CONTENT" \
  --arg project_id "$PROJECT_DIR" \
  --arg category "$CATEGORY" \
  --arg source "claude-code-hook" \
  --arg client "claude_code" \
  '{
    content: $content,
    project_id: $project_id,
    category: $category,
    source: $source,
    client: $client,
    tags: ["auto-save", "keyword", $category]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
