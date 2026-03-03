#!/bin/bash
__VERSION_MARKER__
# UserPromptSubmit hook: keyword-filtered context search (local mode)
# stdin: {prompt, session_id, transcript_path, cwd, ...}
# Output: {additionalContext: "..."} or exit 0 (no injection)

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

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

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
QUERY=$(echo "$PROMPT" | head -c 200)
THRESHOLD="${MEM_MESH_SEARCH_THRESHOLD:-0.75}"
LIMIT="${MEM_MESH_SEARCH_LIMIT:-3}"

CONTEXT=$(python3 -c "
import sys, asyncio, json
sys.path.insert(0, '$MEM_MESH_PATH')
try:
    from app.core.storage.direct import DirectStorageManager

    async def search():
        s = DirectStorageManager()
        await s.initialize()
        results = await s.search_memories(
            query=sys.argv[1],
            project_id=sys.argv[2],
            limit=int(sys.argv[4]),
        )
        if not results:
            sys.exit(0)
        threshold = float(sys.argv[3])
        relevant = [r for r in results if r.get('similarity_score', 0) > threshold]
        if not relevant:
            sys.exit(0)
        lines = ['## Related Memories (auto-retrieved)', '']
        for r in relevant[:int(sys.argv[4])]:
            cat = r.get('category', 'unknown')
            content = r.get('content', '')[:300]
            created = str(r.get('created_at', ''))[:10]
            lines.append(f'- [{cat}] ({created}) {content}')
        print('\n'.join(lines))

    asyncio.run(search())
except Exception:
    sys.exit(0)
" "$QUERY" "$PROJECT_DIR" "$THRESHOLD" "$LIMIT" 2>/dev/null) || exit 0

[ -z "$CONTEXT" ] && exit 0

jq -n --arg ctx "$CONTEXT" '{additionalContext: $ctx}'
exit 0
