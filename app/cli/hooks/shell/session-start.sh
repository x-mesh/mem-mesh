#!/bin/bash
__VERSION_MARKER__
# Claude Code SessionStart hook: inject mem-mesh session context
# Fires on session start AND after compaction (context re-injection)
# Returns additional_context JSON via /api/work/sessions/resume/{project_id}
#
# Features:
# 1. Session resume data injection (existing)
# 2. Context continuation detection — reminds AI to call session_resume (new)

set -euo pipefail
command -v jq >/dev/null 2>&1 || { echo '{}'; exit 0; }
command -v curl >/dev/null 2>&1 || { echo '{}'; exit 0; }

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

INPUT=$(cat)

# Detect project from CWD
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"

# ── Extract IDE session_id from hook stdin ──
IDE_SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)

# ── Detect context continuation ──
# Claude Code fires SessionStart both on fresh start AND after context compaction.
# After compaction, the transcript_path still exists with prior entries,
# and session_id is preserved. We detect this to inject a stronger reminder.
IS_CONTINUATION="false"
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
  # If transcript has assistant entries, this is a continuation (post-compaction)
  HAS_ASSISTANT=$(python3 -c "
import json, sys
try:
    count = 0
    with open(sys.argv[1], 'r') as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get('type') == 'assistant':
                    count += 1
                    if count >= 2:
                        print('true')
                        sys.exit(0)
            except (ValueError, KeyError, TypeError):
                pass
    print('false')
except Exception:
    print('false')
" "$TRANSCRIPT_PATH" 2>/dev/null) || HAS_ASSISTANT="false"
  IS_CONTINUATION="$HAS_ASSISTANT"
fi

# Fetch session resume data (same API as Cursor — consistent cross-IDE)
# Pass IDE session_id as query param for session correlation
RESUME_PARAMS="expand=smart"
[ -n "$IDE_SESSION_ID" ] && RESUME_PARAMS="${RESUME_PARAMS}&ide_session_id=${IDE_SESSION_ID}&client_type=claude-ai"
RESUME_DATA=$(curl -s --max-time 5 \
  "${API_URL}/api/work/sessions/resume/${PROJECT_DIR}?${RESUME_PARAMS}" \
  2>/dev/null) || RESUME_DATA='{"error": "mem-mesh API not available"}'

# Extract compact summary from session_resume response
SESSION_SUMMARY=$(echo "$RESUME_DATA" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if 'error' in data:
        print('[WARNING] mem-mesh API 연결 실패 — 오프라인 모드')
    else:
        lines = []
        pins = data.get('pins', [])
        open_list = [p for p in pins if p.get('status') in ('open', 'in_progress')]
        if open_list:
            lines.append('**미완료 작업:**')
            for p in open_list:
                content = p.get('content', '?')[:100]
                lines.append(f'- [pin] {content}')
        if not lines:
            lines.append('No recent activity.')
        print('\n'.join(lines))
except Exception:
    print('mem-mesh not available')
" 2>/dev/null) || SESSION_SUMMARY="mem-mesh not available"

# Build context with continuation-aware reminder
CONTINUATION_REMINDER=""
if [ "$IS_CONTINUATION" = "true" ]; then
  CONTINUATION_REMINDER="
### [IMPORTANT] Context Continuation Detected
This session was compacted and resumed. Previous context may be lost.
**You MUST call \`session_resume(project_id=\"${PROJECT_DIR}\", expand=\"smart\")\` immediately** to restore mem-mesh context.
If there were unsaved decisions, bugs, or design changes in the previous context, save them with \`mcp__mem-mesh__add\` before continuing.
"
fi

CONTEXT="## mem-mesh Session Context (Auto-injected)
${CONTINUATION_REMINDER}
### Recent Activity (${PROJECT_DIR})
${SESSION_SUMMARY}

### Rules
__RULES_TEXT__"

jq -n --arg ctx "$CONTEXT" '{ additional_context: $ctx }'
