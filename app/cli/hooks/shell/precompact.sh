#!/bin/bash
__VERSION_MARKER__
# Claude Code PreCompact hook: save reminder + auto-end session before compaction
# Ensures unsaved decisions are flagged and session data is preserved
# Returns {additionalContext: "..."} to remind AI to save before compaction

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v curl >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

INPUT=$(cat)
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)

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

    # Patterns that suggest important saveable content
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
                # Check for important patterns in recent turns
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

# ── End session via API ──
curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/work/sessions/end-by-project/${PROJECT_DIR}?summary=Auto-ended%20by%20PreCompact%20hook" \
  2>/dev/null || true

# ── Return save reminder as additionalContext ──
if [ -n "$SAVE_HINT" ]; then
  CONTEXT="## [IMPORTANT] Context Compaction — Save Checkpoint

${SAVE_HINT}

**컨텍스트가 압축됩니다.** 압축 전에 중요한 결정/버그 수정/설계 변경을 mcp__mem-mesh__add로 저장하세요.
저장 대상: decision, bug, incident, idea, code_snippet 카테고리만.
일상적 작업은 pin_add로 충분합니다."

  jq -n --arg ctx "$CONTEXT" '{additionalContext: $ctx}'
else
  exit 0
fi
