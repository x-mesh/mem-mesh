#!/bin/bash
# mem-mesh-hooks prompt-version: 8
# UserPromptSubmit hook: keyword-filtered context search
# stdin: {prompt, session_id, transcript_path, cwd, ...}
# Output: {additionalContext: "..."} or exit 0 (no injection)

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v curl >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-https://meme.24x365.online}"

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')
[ -z "$PROMPT" ] && exit 0
[ ${#PROMPT} -lt 30 ] && exit 0

# Keyword filter: default + env override
DEFAULT_KEYWORDS='이전|지난|결정|기존|왜.*했|변경.*이유|remember|previous|decided|why did|last time|before'
EXTRA_KEYWORDS="${MEM_MESH_SEARCH_KEYWORDS:-}"
if [ -n "$EXTRA_KEYWORDS" ]; then
  KEYWORDS="${DEFAULT_KEYWORDS}|${EXTRA_KEYWORDS}"
else
  KEYWORDS="$DEFAULT_KEYWORDS"
fi

echo "$PROMPT" | grep -qiE "$KEYWORDS" || exit 0

# Search mem-mesh for related memories
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
QUERY=$(echo "$PROMPT" | head -c 200)
THRESHOLD="${MEM_MESH_SEARCH_THRESHOLD:-0.75}"
LIMIT="${MEM_MESH_SEARCH_LIMIT:-3}"

RESPONSE=$(curl -s --max-time 3 \
  -G "${API_URL}/api/memories/search" \
  --data-urlencode "query=${QUERY}" \
  --data-urlencode "project_id=${PROJECT_DIR}" \
  --data-urlencode "limit=${LIMIT}" \
  --data-urlencode "search_mode=hybrid" \
  2>/dev/null) || exit 0

# Parse results, skip if empty or low relevance
CONTEXT=$(python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    results = data.get('results', [])
    if not results:
        sys.exit(0)
    threshold = float(sys.argv[1])
    relevant = [r for r in results if r.get('similarity_score', 0) > threshold]
    if not relevant:
        sys.exit(0)
    lines = ['## Related Memories (auto-retrieved)', '']
    for r in relevant[:int(sys.argv[2])]:
        cat = r.get('category', 'unknown')
        content = r.get('content', '')[:300]
        created = r.get('created_at', '')[:10]
        lines.append(f'- [{cat}] ({created}) {content}')
    print('\n'.join(lines))
except Exception:
    sys.exit(0)
" "$THRESHOLD" "$LIMIT" <<< "$RESPONSE" 2>/dev/null) || exit 0

[ -z "$CONTEXT" ] && exit 0

# Return as additionalContext
jq -n --arg ctx "$CONTEXT" '{additionalContext: $ctx}'
exit 0
