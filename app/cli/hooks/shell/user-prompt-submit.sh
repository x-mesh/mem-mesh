#!/bin/bash
__VERSION_MARKER__
# UserPromptSubmit hook: keyword-filtered context search + save reminder
# stdin: {prompt, session_id, transcript_path, cwd, ...}
# Output: {hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: "..."}} or exit 0
#
# Two independent functions:
# 1. Keyword-matched memory search (existing)
# 2. Save reminder after N turns without mcp__mem-mesh__add (new)

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v curl >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
[ -z "$PROMPT" ] && exit 0

PARTS=()

# ── Part 1: Keyword-filtered memory search ──
if [ ${#PROMPT} -ge 30 ]; then
  DEFAULT_KEYWORDS='이전|지난|결정|기존|왜.*했|변경.*이유|remember|previous|decided|why did|last time|before'
  EXTRA_KEYWORDS="${MEM_MESH_SEARCH_KEYWORDS:-}"
  if [ -n "$EXTRA_KEYWORDS" ]; then
    KEYWORDS="${DEFAULT_KEYWORDS}|${EXTRA_KEYWORDS}"
  else
    KEYWORDS="$DEFAULT_KEYWORDS"
  fi

  if echo "$PROMPT" | grep -qiE "$KEYWORDS"; then
    PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
    QUERY=$(echo "$PROMPT" | head -c 200)
    THRESHOLD="${MEM_MESH_SEARCH_THRESHOLD:-0.75}"
    LIMIT="${MEM_MESH_SEARCH_LIMIT:-3}"

    RESPONSE=$(curl -s --max-time 3 \
      -G "${API_URL}/api/memories/search" \
      --data-urlencode "query=${QUERY}" \
      --data-urlencode "project_id=${PROJECT_DIR}" \
      --data-urlencode "limit=${LIMIT}" \
      --data-urlencode "search_mode=hybrid" \
      2>/dev/null) || RESPONSE=""

    if [ -n "$RESPONSE" ]; then
      SEARCH_CTX=$(python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    results = data.get('results', [])
    if not results:
        sys.exit(0)
    threshold = float(sys.argv[1])
    relevant = [r for r in results if r.get('similarity_score', 0) > threshold]
    if not relevant:
        sys.exit(0)
    lines = ['## Related Memories (auto-retrieved)', '']
    for r in relevant[:int(sys.argv[2])]:
        cat = r.get('category', 'unknown')
        content = r.get('content', '')[:300]
        created = r.get('created_at', '')[:10]
        lines.append(f'- [{cat}] ({created}) {content}')
    print('\n'.join(lines))
except Exception:
    sys.exit(0)
" "$THRESHOLD" "$LIMIT" <<< "$RESPONSE" 2>/dev/null) || SEARCH_CTX=""
      [ -n "$SEARCH_CTX" ] && PARTS+=("$SEARCH_CTX")
    fi
  fi
fi

# ── Part 2: Save reminder + Pin completion reminder ──
SAVE_REMINDER_INTERVAL="${MEM_MESH_SAVE_REMINDER_TURNS:-5}"

if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
  REMINDER=$(python3 -c "
import sys, json

transcript_path = sys.argv[1]
interval = int(sys.argv[2])

try:
    assistant_turns = 0
    last_save_turn = 0
    turn = 0
    pin_add_count = 0
    pin_complete_count = 0

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
                content_str = str(content)
                if 'mcp__mem-mesh__add' in content_str or 'mcp__mem-mesh__pin_add' in content_str:
                    last_save_turn = turn
                # Track pin_add / pin_complete balance
                if 'mcp__mem-mesh__pin_add' in content_str or 'pin_add' in content_str:
                    pin_add_count += content_str.count('pin_add')
                if 'mcp__mem-mesh__pin_complete' in content_str or 'pin_complete' in content_str:
                    pin_complete_count += content_str.count('pin_complete')
                assistant_turns = turn

    parts = []
    turns_since_save = assistant_turns - last_save_turn
    if turns_since_save >= interval and assistant_turns >= interval:
        parts.append(f'mem-mesh에 {turns_since_save}턴 동안 저장하지 않았습니다. 중요한 결정/버그 수정/설계 변경이 있었다면 mcp__mem-mesh__add로 저장하세요.')

    # Pin balance check: if pins were added but none completed
    if pin_add_count > 0 and pin_complete_count == 0 and assistant_turns >= 3:
        parts.append(f'이 세션에서 pin_add가 {pin_add_count}회 호출되었지만 pin_complete는 0회입니다. 완료된 작업이 있다면 pin_complete를 호출하세요.')

    if parts:
        print('\n'.join(parts))
except Exception:
    pass
" "$TRANSCRIPT_PATH" "$SAVE_REMINDER_INTERVAL" 2>/dev/null) || REMINDER=""

  [ -n "$REMINDER" ] && PARTS+=("$REMINDER")
fi

# ── Combine and output ──
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
  hookSpecificOutput: {
    hookEventName: "UserPromptSubmit",
    additionalContext: $ctx
  }
}'
exit 0
