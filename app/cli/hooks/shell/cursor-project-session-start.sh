#!/bin/bash
__VERSION_MARKER__
# mem-mesh Session Start Hook for Cursor (project-local)
# Injects mem-mesh usage instructions into the session context.

set -euo pipefail
__PROJECT_ID_RESOLVER__

command -v jq >/dev/null 2>&1 || { echo '{}'; exit 0; }

HOOK_OUTPUT_MODE="${MEM_MESH_HOOK_OUTPUT_MODE:-__HOOK_OUTPUT_MODE__}"
INPUT=$(cat)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

RESUME_OUTPUT=""
RESUME_OUTPUT=$(python3 -c "
import sys, json
sys.path.insert(0, '$PROJECT_ROOT')
try:
    from app.core.services.pin_service import PinService
    from app.core.storage.direct import DirectStorageManager
    import asyncio

    async def get_resume():
        storage = DirectStorageManager()
        await storage.initialize()
        pin_svc = PinService(storage)
        result = await pin_svc.session_resume('__PROJECT_ID__', expand='smart')
        return json.dumps(result, ensure_ascii=False, default=str)

    print(asyncio.run(get_resume()))
except Exception as e:
    print(json.dumps({'error': str(e)}))
" 2>/dev/null) || RESUME_OUTPUT='{"error": "mem-mesh not available"}'

RULES_TEXT="__RULES_TEXT__"

CONTEXT="## mem-mesh Memory Integration (Auto-loaded)

### 세션 복원 결과
\`\`\`json
${RESUME_OUTPUT}
\`\`\`

### 작업 규칙
$RULES_TEXT"

case "$HOOK_OUTPUT_MODE" in
  quiet|none|off)
    exit 0
    ;;
  compact)
    CONTEXT="mem-mesh session context available. Detailed hook output suppressed; use mem-mesh MCP tools when prior context is needed."
    ;;
esac

jq -n --arg ctx "$CONTEXT" '{
  hookSpecificOutput: {
    hookEventName: "SessionStart",
    additionalContext: $ctx
  }
}'
