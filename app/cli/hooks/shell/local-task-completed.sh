#!/bin/bash
__VERSION_MARKER__
# TaskCompleted hook: auto-save completed tasks to mem-mesh (local mode)
# stdin: {task_id, task_subject, task_description, teammate_name, team_name, ...}

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)
TASK_SUBJECT=$(echo "$INPUT" | jq -r '.task_subject // empty')
TASK_DESC=$(echo "$INPUT" | jq -r '.task_description // empty')
TEAMMATE=$(echo "$INPUT" | jq -r '.teammate_name // empty')

[ -z "$TASK_SUBJECT" ] && exit 0

# Build content
CONTENT="## Task Completed: ${TASK_SUBJECT}"
[ -n "$TASK_DESC" ] && CONTENT="${CONTENT}\n\n${TASK_DESC}"
[ -n "$TEAMMATE" ] && CONTENT="${CONTENT}\n\nCompleted by: ${TEAMMATE}"
CONTENT=$(printf '%b' "$CONTENT" | head -c 5000)

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
            category='task',
            source='hook-local',
            tags=['auto-save', 'task-completed'],
        )

    asyncio.run(save())
except Exception:
    pass
" "$CONTENT" "$PROJECT_DIR" 2>/dev/null || true

exit 0
