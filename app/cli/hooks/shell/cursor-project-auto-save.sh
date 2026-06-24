#!/bin/bash
__VERSION_MARKER__
# mem-mesh Auto-Save Hook for Cursor (stop event, project-local)

set -euo pipefail

HOOK_OUTPUT_MODE="${MEM_MESH_HOOK_OUTPUT_MODE:-__HOOK_OUTPUT_MODE__}"
INPUT=$(cat)

HAS_TOOL_USE=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    transcript = data.get('transcript', [])
    meaningful = any(
        msg.get('type') == 'tool_use' and
        msg.get('tool_name', '') in ('Edit', 'Write', 'Bash', 'NotebookEdit')
        for msg in transcript
        if isinstance(msg, dict)
    )
    print('true' if meaningful else 'false')
except Exception:
    print('false')
" 2>/dev/null) || HAS_TOOL_USE="false"

if [ "$HAS_TOOL_USE" = "true" ]; then
    case "$HOOK_OUTPUT_MODE" in
      quiet|none|off) exit 0 ;;
    esac
    python3 -c "
import json
print(json.dumps({'followup_message': '''__FOLLOWUP_MSG__'''}))
"
else
    echo '{}'
fi
