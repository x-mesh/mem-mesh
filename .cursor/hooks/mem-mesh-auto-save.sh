#!/bin/bash
# mem-mesh Auto-Save Hook for Cursor (stop event)
# After the agent finishes responding, suggests saving important conversations.
# Uses Cursor's followup_message to trigger a new agent turn if needed.

set -euo pipefail

INPUT=$(cat)

# Extract conversation transcript length/content indicators
# Only suggest saving for substantial conversations (not simple Q&A)
HAS_TOOL_USE=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    # Check if there were meaningful tool uses (file edits, code changes)
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
    # Suggest the agent save the conversation
    python3 -c "
import json
print(json.dumps({
    'followup_message': '방금 완료한 작업이 중요하다면, mem-mesh에 기록해주세요: 버그 수정은 category=\"bug\", 설계 결정은 category=\"decision\", 코드 패턴은 category=\"code_snippet\"으로 add()를 호출하세요. 일상적 작업이었다면 무시하세요.'
}))
"
else
    # No meaningful changes, skip
    echo '{}'
fi
