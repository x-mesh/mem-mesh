#!/bin/bash
__VERSION_MARKER__
# Claude Code PreCompact hook: save reminder + auto-end session (local mode)
# Ensures unsaved decisions are flagged before context compaction
# Returns {continue: true, systemMessage: "..."} to remind AI to save

set -euo pipefail
command -v python3 >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
IDE_SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)

# Detect project from CWD
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && exit 0

# ── Analyze transcript for unsaved important content ──
SAVE_HINT=""
if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
  SAVE_HINT=$(python3 -c "
import sys, json, re

transcript_path = sys.argv[1]

try:
    assistant_turns = 0
    last_save_turn = 0
    turn = 0
    has_important = False
    important_hints = []

    save_patterns = [
        (r'(버그|bug).*(수정|fix|해결|resolved)', 'bug fix'),
        (r'(결정|decision|decided|chose)', 'decision'),
        (r'(아키텍처|architecture|설계|design)', 'architecture'),
        (r'(구현|implement).*(완료|done|했습니다)', 'implementation'),
        (r'(마이그레이션|migration|전환)', 'migration'),
        (r'(에러|error|exception).*(해결|수정|fixed)', 'error fix'),
    ]

    with open(transcript_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry_type = entry.get('type', '')
            if entry_type == 'assistant':
                turn += 1
                msg = entry.get('message', {})
                content = msg.get('content', '')
                if isinstance(content, list):
                    content = ' '.join(
                        c.get('text', '') + c.get('name', '')
                        for c in content
                        if isinstance(c, dict)
                    )
                content_str = str(content).lower()
                if 'mcp__mem-mesh__add' in content_str:
                    last_save_turn = turn
                for pattern, hint in save_patterns:
                    if re.search(pattern, content_str):
                        has_important = True
                        if hint not in important_hints:
                            important_hints.append(hint)
                assistant_turns = turn

    turns_since_save = assistant_turns - last_save_turn
    if has_important and turns_since_save > 0:
        hints_str = ', '.join(important_hints[:3])
        print(f'이 세션에서 저장되지 않은 중요 내용이 감지됨: {hints_str}. {turns_since_save}턴 동안 mem-mesh 저장 없음.')
    elif turns_since_save >= 3:
        print(f'{turns_since_save}턴 동안 mem-mesh 저장 없음.')
except Exception:
    pass
" "$TRANSCRIPT_PATH" 2>/dev/null) || SAVE_HINT=""
fi

# ── End session locally ──
python3 -c "
import sys, asyncio, json
sys.path.insert(0, '$MEM_MESH_PATH')
try:
    from app.core.services.session import SessionService
    from app.core.database.base import Database

    async def end_session():
        db = Database()
        await db.initialize()
        svc = SessionService(db)
        await svc.end_session_by_project('$PROJECT_DIR', summary='Auto-ended by PreCompact hook')

    asyncio.run(end_session())
except Exception:
    pass
" 2>/dev/null || true

# ── Return save reminder as hookSpecificOutput ──
if [ -n "$SAVE_HINT" ]; then
  CONTEXT="## [IMPORTANT] Context Compaction — Save Checkpoint

${SAVE_HINT}

**컨텍스트가 압축됩니다.** 압축 전에 중요한 결정/버그 수정/설계 변경을 mcp__mem-mesh__add로 저장하세요.
저장 대상: decision, bug, incident, idea, code_snippet 카테고리만.
일상적 작업은 pin_add로 충분합니다."
fi

# ── Query open pins locally ──
OPEN_PINS=""
OPEN_PINS=$(python3 -c "
import sys, json, asyncio
sys.path.insert(0, '$MEM_MESH_PATH')
try:
    from app.core.services.session import SessionService
    from app.core.database.base import Database

    async def get_open_pins():
        db = Database()
        await db.initialize()
        svc = SessionService(db)
        ctx = await svc.resume_last_session('$PROJECT_DIR', expand=False)
        if ctx is None:
            return
        pins = ctx.pins
        open_pins = [p for p in pins if hasattr(p, 'status') and p.status in ('open', 'in_progress')]
        if not open_pins:
            # Try dict format
            open_pins = [p for p in pins if isinstance(p, dict) and p.get('status') in ('open', 'in_progress')]
        if not open_pins:
            return
        lines = ['## 미완료 Pin (' + str(len(open_pins)) + '개)']
        lines.append('컨텍스트 압축 전에 완료된 작업은 pin_complete로 정리하세요.')
        for p in open_pins[:5]:
            if isinstance(p, dict):
                content = p.get('content', '?')[:80]
                pid = p.get('id', '?')
                client = p.get('client', '') or ''
            else:
                content = getattr(p, 'content', '?')[:80]
                pid = getattr(p, 'id', '?')
                client = getattr(p, 'client', '') or ''
            client_str = f'({client}) ' if client else ''
            lines.append(f'- [{pid}] {client_str}{content}')
        print('\n'.join(lines))

    asyncio.run(get_open_pins())
except Exception:
    pass
" 2>/dev/null) || OPEN_PINS=""

# ── Combine and output ──
PARTS=()
[ -n "$SAVE_HINT" ] && PARTS+=("$CONTEXT")
[ -n "$OPEN_PINS" ] && PARTS+=("$OPEN_PINS")

if [ ${#PARTS[@]} -eq 0 ]; then
  exit 0
fi

COMBINED=""
for part in "${PARTS[@]}"; do
  if [ -n "$COMBINED" ]; then
    COMBINED="${COMBINED}

${part}"
  else
    COMBINED="$part"
  fi
done

jq -n --arg ctx "$COMBINED" '{
  continue: true,
  systemMessage: $ctx
}'
