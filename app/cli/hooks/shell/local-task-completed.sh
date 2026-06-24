#!/bin/bash
__VERSION_MARKER__
# TaskCompleted hook: auto-save completed tasks to mem-mesh (local mode)
# stdin: {task_id, task_subject, task_description, teammate_name, team_name, ...}

set -euo pipefail
__PROJECT_ID_RESOLVER__
command -v jq >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

MEM_MESH_PATH=__MEM_MESH_PATH__

INPUT=$(cat)
TASK_SUBJECT=$(echo "$INPUT" | jq -r '.task_subject // empty')
TASK_DESC=$(echo "$INPUT" | jq -r '.task_description // empty')
TEAMMATE=$(echo "$INPUT" | jq -r '.teammate_name // empty')

[ -z "$TASK_SUBJECT" ] && exit 0

# Build content
CONTENT="## Task Completed: ${TASK_SUBJECT}"
[ -n "$TASK_DESC" ] && CONTENT="${CONTENT}\n\n${TASK_DESC}"
[ -n "$TEAMMATE" ] && CONTENT="${CONTENT}\n\nCompleted by: ${TEAMMATE}"
CONTENT=$(printf '%b' "$CONTENT" | python3 -c 'import sys; print(sys.stdin.read()[:5000], end="")')

PROJECT_DIR="$(mem_mesh_project_id)"

python3 - "$MEM_MESH_PATH" "$CONTENT" "$PROJECT_DIR" <<'PY' 2>/dev/null || true
import sys, asyncio, json
mem_mesh_path, content, project_dir = sys.argv[1:4]
sys.path.insert(0, mem_mesh_path)
try:
    from app.core.storage.direct import DirectStorageManager

    async def save():
        s = DirectStorageManager()
        await s.initialize()
        await s.add_memory(
            content=content,
            project_id=project_dir,
            category='task',
            source='hook-local',
            tags=['auto-save', 'task-completed'],
        )

    asyncio.run(save())
except Exception:
    pass
PY

exit 0
