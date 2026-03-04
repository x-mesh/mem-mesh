#!/bin/bash
# mem-mesh-hooks prompt-version: 9
# Stop hook (enhanced): Haiku API decides save/skip, then saves via mem-mesh API
# Requires ANTHROPIC_API_KEY env var
# stdin: {"stop_hook_active":bool,"last_assistant_message":"..."} JSON

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

[ -z "${ANTHROPIC_API_KEY:-}" ] && exit 0

API_URL="${MEM_MESH_API_URL:-https://meme.24x365.online}"

INPUT=$(cat)

# Prevent infinite loop
ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

# Extract message + minimum length filter
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 100 ] && exit 0

# Check if already saved in this turn
echo "$MESSAGE" | grep -q 'mcp__mem-mesh__add' && exit 0

# Truncate to fit within API limits
CONVERSATION=$(echo "$MESSAGE" | head -c 6000)

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

# Call Haiku for save/skip decision, then save if needed
python3 -c "
import json, urllib.request, urllib.error, os, sys

api_key = os.environ.get('ANTHROPIC_API_KEY', '')
if not api_key:
    sys.exit(0)

conversation = sys.stdin.read()
prompt = '''Analyze the conversation and decide whether to save it to mem-mesh.

## Save criteria (save if ANY match)
- 버그 진단/해결
- 아키텍처 또는 설계 결정
- 중요 설정 변경 또는 마이그레이션

## Skip criteria (skip takes priority)
- 단순 질문/답변 ("뭐야?", "보여줘")
- 파일 읽기만 한 경우
- 이미 저장된 내용의 반복
- hook/설정 자체의 점검·수정·메타 대화 (hook 동작 확인, settings.json 수정 포함)

## Output format (EXACTLY one line, no markdown)
Save: SAVE|CATEGORY|one-line summary (50 chars max)
  CATEGORY: bug, decision, code_snippet, idea, incident
Skip: SKIP

Examples:
  SAVE|bug|Fixed ZeroDivisionError in search tests
  SAVE|decision|Chose hybrid approach for stop hook
  SKIP'''

payload = json.dumps({
    'model': 'claude-haiku-4-5-20251001',
    'max_tokens': 100,
    'messages': [{'role': 'user', 'content': f'{prompt}\n\n---\n\n{conversation}'}],
}).encode()

req = urllib.request.Request(
    'https://api.anthropic.com/v1/messages',
    data=payload,
    headers={
        'Content-Type': 'application/json',
        'x-api-key': api_key,
        'anthropic-version': '2023-06-01',
    },
)

try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        result = json.loads(resp.read())
        text = result.get('content', [{}])[0].get('text', '').strip()
except Exception:
    sys.exit(0)

if not text or text == 'SKIP' or not text.startswith('SAVE|'):
    sys.exit(0)

# Parse SAVE|category|summary
parts = text.split('|', 2)
if len(parts) < 3:
    sys.exit(0)

category = parts[1].strip()
summary = parts[2].strip()[:200]

valid_categories = ('bug', 'decision', 'code_snippet', 'idea', 'incident')
if category not in valid_categories:
    category = 'decision'

# Build payload with json.dumps for safety
content = summary + '\n\n---\n\n' + conversation[:3000]
save_payload = json.dumps({
    'content': content[:9500],
    'project_id': '$PROJECT_DIR',
    'category': category,
    'source': 'hook-enhanced',
    'tags': ['auto-save', 'enhanced', category],
})

# Save via mem-mesh API
save_req = urllib.request.Request(
    '$API_URL' + '/api/memories',
    data=save_payload.encode(),
    headers={'Content-Type': 'application/json'},
)
try:
    with urllib.request.urlopen(save_req, timeout=5) as resp:
        pass
except Exception:
    pass
" <<< "$CONVERSATION" 2>/dev/null || true

exit 0
