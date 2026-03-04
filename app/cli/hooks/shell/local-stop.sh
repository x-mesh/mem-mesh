#!/bin/bash
__VERSION_MARKER__
# Stop hook: save conversation summary to mem-mesh (local mode)

set -euo pipefail
command -v python3 >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 50 ] && exit 0

SUMMARY=$(echo "$MESSAGE" | head -c 9500)
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

python3 -c "
import sys, asyncio, json
sys.path.insert(0, '$MEM_MESH_PATH')
from app.core.storage.direct import DirectStorageManager
async def save():
    s = DirectStorageManager()
    await s.initialize()
    await s.add_memory(
        content='[conversation summary] ' + $(python3 -c "import json; print(json.dumps('''$SUMMARY'''))"),
        project_id='$PROJECT_DIR',
        category='git-history',
        source='hook-local',
        tags=['auto-save', 'conversation'],
    )
asyncio.run(save())
" 2>/dev/null || true

exit 0
