#!/bin/bash
__VERSION_MARKER__
# Cursor stop hook: conditionally suggest saving to mem-mesh
# stdin: {"last_assistant_message":"...", "transcript":[...]} JSON

set -euo pipefail

INPUT=$(cat)

# Check if there were meaningful tool uses (file edits, code changes)
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
    python3 -c "
import json
print(json.dumps({'followup_message': '''__FOLLOWUP_MSG__'''}))
"
else
    echo '{}'
fi
