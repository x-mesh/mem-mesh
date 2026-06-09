#!/bin/bash
__VERSION_MARKER__
# SubagentStop hook: auto-save important subagent results (local mode)
# stdin: {stop_hook_active, agent_id, agent_type, last_assistant_message, ...}
# Reuses keyword matching logic from stop-decide

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

MEM_MESH_PATH=__MEM_MESH_PATH__

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
CONTENT=$(printf '%s' "$CONTENT" | python3 -c 'import sys; print(sys.stdin.read()[:9500], end="")')

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

python3 - "$MEM_MESH_PATH" "$CONTENT" "$PROJECT_DIR" "$CATEGORY" <<'PY' 2>/dev/null || true
import sys, asyncio, json
mem_mesh_path, content, project_dir, category = sys.argv[1:5]
sys.path.insert(0, mem_mesh_path)
try:
    from app.core.storage.direct import DirectStorageManager

    async def save():
        s = DirectStorageManager()
        await s.initialize()
        await s.add_memory(
            content=content,
            project_id=project_dir,
            category=category,
            source='hook-local',
            tags=['auto-save', 'subagent', category],
        )

    asyncio.run(save())
except Exception:
    pass
PY

exit 0
