#!/bin/bash
__VERSION_MARKER__
# Claude Code SessionStart hook: inject mem-mesh session context
# Fires on session start AND after compaction (context re-injection)
# Returns additional_context JSON via /api/work/sessions/resume/{project_id}

set -euo pipefail
command -v jq >/dev/null 2>&1 || { echo '{}'; exit 0; }
command -v curl >/dev/null 2>&1 || { echo '{}'; exit 0; }

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

INPUT=$(cat)

# Detect project from CWD
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"

# Fetch session resume data (same API as Cursor — consistent cross-IDE)
RESUME_DATA=$(curl -s --max-time 5 \
  "${API_URL}/api/work/sessions/resume/${PROJECT_DIR}?expand=smart" \
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
        recent = data.get('recent_memories', [])
        if recent:
            lines.append('**최근 맥락:**')
            for r in recent:
                cat = r.get('category', '?')
                content = r.get('content', '')[:120].replace('\n', ' ')
                lines.append(f'- [{cat}] {content}')
        if not lines:
            lines.append('No recent activity.')
        print('\n'.join(lines))
except Exception:
    print('mem-mesh not available')
" 2>/dev/null) || SESSION_SUMMARY="mem-mesh not available"

CONTEXT="## mem-mesh Session Context (Auto-injected)

### Recent Activity (${PROJECT_DIR})
${SESSION_SUMMARY}

### Rules
__RULES_TEXT__"

jq -n --arg ctx "$CONTEXT" '{ additional_context: $ctx }'
