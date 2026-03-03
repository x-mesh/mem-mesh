#!/bin/bash
__VERSION_MARKER__
# Claude Code SessionStart hook: inject mem-mesh session context (local mode)
# Fires on session start AND after compaction (context re-injection)
# Returns additional_context JSON

set -euo pipefail
command -v python3 >/dev/null 2>&1 || { echo '{}'; exit 0; }

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"

RESUME_DATA=$(python3 -c "
import sys, json
sys.path.insert(0, '$MEM_MESH_PATH')
try:
    from app.core.services.pin_service import PinService
    from app.core.storage.direct import DirectStorageManager
    import asyncio

    async def get_resume():
        storage = DirectStorageManager()
        await storage.initialize()
        pin_svc = PinService(storage)
        result = await pin_svc.session_resume('$PROJECT_DIR', expand='smart')
        return json.dumps(result, ensure_ascii=False, default=str)

    print(asyncio.run(get_resume()))
except Exception as e:
    print(json.dumps({'error': str(e)}))
" 2>/dev/null) || RESUME_DATA='{"error": "mem-mesh not available"}'

RULES_TEXT="__RULES_TEXT__"

CONTEXT="## mem-mesh Session Context (Auto-injected)

### Previous Session
${RESUME_DATA}

### Rules
${RULES_TEXT}"

python3 -c "
import json, sys
ctx = sys.stdin.read()
print(json.dumps({'additional_context': ctx}))
" <<< "$CONTEXT"
