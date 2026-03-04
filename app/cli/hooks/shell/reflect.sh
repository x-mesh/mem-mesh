#!/bin/bash
__VERSION_MARKER__
# Stop hook (enhanced): LLM reflection — analyze conversation and save structured insights
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

# Truncate to fit within API limits (leave room for prompt + analysis output)
CONVERSATION=$(echo "$MESSAGE" | head -c 6000)

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

# Call Haiku for reflection analysis
ANALYSIS=$(python3 -c "
import json, urllib.request, urllib.error, os, sys

api_key = os.environ.get('ANTHROPIC_API_KEY', '')
if not api_key:
    sys.exit(0)

conversation = sys.stdin.read()
prompt = '''__REFLECT_PROMPT__'''

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
        text = result.get('content', [{}])[0].get('text', '')
        print(text)
except Exception:
    sys.exit(0)
" <<< "$CONVERSATION" 2>/dev/null) || exit 0

[ -z "$ANALYSIS" ] && exit 0

# Build combined content: raw context + LLM analysis
RAW_SUMMARY=$(echo "$CONVERSATION" | head -c 3000)
CONTENT="## Raw Context
${RAW_SUMMARY}

## LLM Analysis
${ANALYSIS}"

# Limit to API max (10000 chars)
CONTENT=$(echo "$CONTENT" | head -c 9500)

PAYLOAD=$(jq -n \
  --arg content "$CONTENT" \
  --arg project_id "$PROJECT_DIR" \
  --arg client "__CLIENT_TAG__" \
  '{
    content: $content,
    project_id: $project_id,
    category: "decision",
    source: "hook-reflect",
    client: $client,
    tags: ["auto-save", "llm-reflection", "enhanced"]
  }')

curl -s -o /dev/null --max-time 10 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
