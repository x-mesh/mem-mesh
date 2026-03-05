#!/bin/bash
__VERSION_MARKER__
# SubagentStop hook: auto-save important subagent results (local mode)
# stdin: {stop_hook_active, agent_id, agent_type, last_assistant_message, ...}
# Reuses keyword matching logic from stop-decide

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)

# Guard: prevent loop
ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 100 ] && exit 0

# Already saved via MCP
echo "$MESSAGE" | grep -q 'mcp__mem-mesh__add' && exit 0

# Keyword decision (injected from keywords.py at install time)
CATEGORY=$(python3 -c "
__KEYWORD_MATCHER__
" <<< "$MESSAGE" 2>/dev/null) || CATEGORY="SKIP"

[ "$CATEGORY" = "SKIP" ] && exit 0

# Build content with agent type prefix
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // "unknown"')
CONTENT="[${AGENT_TYPE} agent] ${MESSAGE}"
CONTENT=$(echo "$CONTENT" | head -c 9500)

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

python3 -c "
import sys, asyncio, json
sys.path.insert(0, '$MEM_MESH_PATH')
try:
    from app.core.storage.direct import DirectStorageManager

    async def save():
        s = DirectStorageManager()
        await s.initialize()
        await s.add_memory(
            content=sys.argv[1],
            project_id=sys.argv[2],
            category=sys.argv[3],
            source='hook-local',
            tags=['auto-save', 'subagent', sys.argv[3]],
        )

    asyncio.run(save())
except Exception:
    pass
" "$CONTENT" "$PROJECT_DIR" "$CATEGORY" 2>/dev/null || true

exit 0
