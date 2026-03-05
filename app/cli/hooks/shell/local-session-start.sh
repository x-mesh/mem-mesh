#!/bin/bash
__VERSION_MARKER__
# Claude Code SessionStart hook: inject mem-mesh session context (local mode)
# Fires on session start AND after compaction (context re-injection)
# Returns hookSpecificOutput JSON
#
# Features:
# 1. Session resume data injection (existing)
# 2. Context continuation detection (new)

set -euo pipefail
command -v python3 >/dev/null 2>&1 || { echo '{}'; exit 0; }
command -v jq >/dev/null 2>&1 || { echo '{}'; exit 0; }

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"

# ── Extract IDE session_id from hook stdin ──
IDE_SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)

# ── Detect context continuation ──
IS_CONTINUATION="false"
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
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

RESUME_DATA=$(python3 -c "
import sys, json
sys.path.insert(0, '$MEM_MESH_PATH')
try:
    from app.core.services.session import SessionService
    from app.core.database.base import Database
    import asyncio

    async def get_resume():
        db = Database()
        await db.initialize()
        svc = SessionService(db)

        # IDE session_id가 있으면 세션에 연결
        ide_sid = '$IDE_SESSION_ID' or None
        if ide_sid:
            await svc.get_or_create_active_session(
                '$PROJECT_DIR', ide_session_id=ide_sid, client_type='claude-ai'
            )

        ctx = await svc.resume_last_session('$PROJECT_DIR', expand='smart')
        if ctx is None:
            return json.dumps({'status': 'no_session'})
        return json.dumps(ctx.model_dump(), ensure_ascii=False, default=str)

    print(asyncio.run(get_resume()))
except Exception as e:
    print(json.dumps({'error': str(e)}))
" 2>/dev/null) || RESUME_DATA='{"error": "mem-mesh not available"}'

RULES_TEXT="__RULES_TEXT__"

# Build continuation reminder
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
### Previous Session
${RESUME_DATA}

### Rules
${RULES_TEXT}"

python3 -c "
import json, sys
ctx = sys.stdin.read()
print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': ctx}}))
" <<< "$CONTEXT"
