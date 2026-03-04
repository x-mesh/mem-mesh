#!/bin/bash
__VERSION_MARKER__
# Stop hook (enhanced): Haiku API decides save/skip, then saves via mem-mesh API
# Requires ANTHROPIC_API_KEY env var
# stdin: {"stop_hook_active":bool,"last_assistant_message":"..."} JSON

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

[ -z "${ANTHROPIC_API_KEY:-}" ] && exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

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
