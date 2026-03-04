#!/bin/bash
__VERSION_MARKER__
# Stop hook (enhanced, local): LLM reflection — analyze conversation and save structured insights
# Requires ANTHROPIC_API_KEY env var
# Writes directly to local SQLite via Python

set -euo pipefail
command -v python3 >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

[ -z "${ANTHROPIC_API_KEY:-}" ] && exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 100 ] && exit 0

CONVERSATION=$(echo "$MESSAGE" | head -c 6000)
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

python3 -c "
import sys, asyncio, json, urllib.request, urllib.error, os

api_key = os.environ.get('ANTHROPIC_API_KEY', '')
if not api_key:
    sys.exit(0)

conversation = sys.stdin.read()
prompt = '''__REFLECT_PROMPT__'''

# Call Haiku for analysis
payload = json.dumps({
    'model': '__REFLECT_MODEL__',
    'max_tokens': __REFLECT_MAX_TOKENS__,
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
        analysis = result.get('content', [{}])[0].get('text', '')
except Exception:
    sys.exit(0)

if not analysis:
    sys.exit(0)

raw_summary = conversation[:3000]
content = f'## Raw Context\n{raw_summary}\n\n## LLM Analysis\n{analysis}'
content = content[:9500]

sys.path.insert(0, '$MEM_MESH_PATH')
from app.core.storage.direct import DirectStorageManager

async def save():
    s = DirectStorageManager()
    await s.initialize()
    await s.add_memory(
        content=content,
        project_id='$PROJECT_DIR',
        category='decision',
        source='hook-reflect',
        tags=['auto-save', 'llm-reflection', 'enhanced'],
    )

asyncio.run(save())
" <<< "$CONVERSATION" 2>/dev/null || true

exit 0
