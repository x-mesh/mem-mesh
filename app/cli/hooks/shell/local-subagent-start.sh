#!/bin/bash
__VERSION_MARKER__
# SubagentStart hook: inject project context into subagents (local mode)
# stdin: {agent_id, agent_type, session_id, ...}
# Output: {hookSpecificOutput: {hookEventName: "SubagentStart", additionalContext: "..."}}

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // empty')

# Skip for lightweight agents
case "$AGENT_TYPE" in
  Explore|Glob|Grep|Read) exit 0 ;;
esac

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

CONTEXT=$(python3 -c "
import sys, asyncio, json
sys.path.insert(0, '$MEM_MESH_PATH')
try:
    from app.core.storage.direct import DirectStorageManager

    async def search():
        s = DirectStorageManager()
        await s.initialize()
        results = await s.search_memories(
            query='project rules architecture decision',
            project_id='$PROJECT_DIR',
            category='decision',
            limit=5,
        )
        if not results:
            sys.exit(0)
        lines = ['## Project Context (mem-mesh)', '']
        for r in results[:5]:
            content = r.get('content', '')[:200]
            lines.append(f'- {content}')
        print('\n'.join(lines))

    asyncio.run(search())
except Exception:
    sys.exit(0)
" 2>/dev/null) || exit 0

[ -z "$CONTEXT" ] && exit 0

jq -n --arg ctx "$CONTEXT" '{
  hookSpecificOutput: {
    hookEventName: "SubagentStart",
    additionalContext: $ctx
  }
}'
exit 0
