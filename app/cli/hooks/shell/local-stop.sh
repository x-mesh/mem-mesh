#!/bin/bash
__VERSION_MARKER__
# Stop hook: save conversation summary to mem-mesh (local mode)

set -euo pipefail
__PROJECT_ID_RESOLVER__
command -v python3 >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

MEM_MESH_PATH=__MEM_MESH_PATH__

INPUT=$(cat)
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 50 ] && exit 0

SUMMARY=$(printf '%s' "$MESSAGE" | python3 -c 'import sys; print(sys.stdin.read()[:9500], end="")')
PROJECT_DIR="$(mem_mesh_project_id)"

python3 - "$MEM_MESH_PATH" "$PROJECT_DIR" "$SUMMARY" <<'PY' 2>/dev/null || true
import sys, asyncio, json
mem_mesh_path, project_dir, summary = sys.argv[1:4]
sys.path.insert(0, mem_mesh_path)
from app.core.storage.direct import DirectStorageManager
async def save():
    s = DirectStorageManager()
    await s.initialize()
    await s.add_memory(
        content='[conversation summary] ' + summary,
        project_id=project_dir,
        category='git-history',
        source='hook-local',
        tags=['auto-save', 'conversation'],
    )
asyncio.run(save())
PY

exit 0
