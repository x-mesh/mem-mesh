#!/bin/bash
__VERSION_MARKER__
# Stop hook (enhanced, local): Haiku API decides save/skip, saves to local SQLite
# Requires ANTHROPIC_API_KEY env var

set -euo pipefail
command -v python3 >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

[ -z "${ANTHROPIC_API_KEY:-}" ] && exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)

ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 100 ] && exit 0

echo "$MESSAGE" | grep -q 'mcp__mem-mesh__add' && exit 0

CONVERSATION=$(echo "$MESSAGE" | head -c 6000)
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

python3 -c "
import sys, asyncio, json, urllib.request, urllib.error, os

api_key = os.environ.get('ANTHROPIC_API_KEY', '')
if not api_key:
    sys.exit(0)

conversation = sys.stdin.read()
prompt = '''__ENHANCED_PROMPT__'''

payload = json.dumps({
    'model': '__REFLECT_MODEL__',
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
    with urllib.request.urlopen(req, timeout=__REFLECT_TIMEOUT__) as resp:
        result = json.loads(resp.read())
        text = result.get('content', [{}])[0].get('text', '').strip()
except Exception:
    sys.exit(0)

if not text or text == 'SKIP' or not text.startswith('SAVE|'):
    sys.exit(0)

parts = text.split('|', 2)
if len(parts) < 3:
    sys.exit(0)

category = parts[1].strip()
summary = parts[2].strip()[:200]

valid_categories = ('bug', 'decision', 'code_snippet', 'idea', 'incident')
if category not in valid_categories:
    category = 'decision'

content = summary + '\n\n---\n\n' + conversation[:3000]
content = content[:9500]

sys.path.insert(0, '$MEM_MESH_PATH')
from app.core.storage.direct import DirectStorageManager

async def save():
    s = DirectStorageManager()
    await s.initialize()
    await s.add_memory(
        content=content,
        project_id='$PROJECT_DIR',
        category=category,
        source='hook-enhanced',
        tags=['auto-save', 'enhanced', category],
    )

asyncio.run(save())
" <<< "$CONVERSATION" 2>/dev/null || true

exit 0
