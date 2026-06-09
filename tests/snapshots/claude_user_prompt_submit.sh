#!/bin/bash
# mem-mesh-hooks prompt-version: 14
# UserPromptSubmit hook: keyword-filtered context search + save reminder + pin tracking
# stdin: {prompt, session_id, transcript_path, cwd, ...}
# Output: {hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: "..."}} or exit 0
#
# Three independent functions:
# 1. Keyword-matched memory search
# 2. Save reminder after N turns without mcp__mem-mesh__add
# 3. Pin tracking reminder (no auto-creation)

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v curl >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-$(cat ~/.mem-mesh/api_url 2>/dev/null || echo https://meme.24x365.online)}"

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
    QUERY=$(printf '%s' "$PROMPT" | jq -Rrs '.[0:200]')
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

# ── Part 2: Save reminder + Pin tracking reminder ──
SAVE_REMINDER_INTERVAL="${MEM_MESH_SAVE_REMINDER_TURNS:-5}"

if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
  REMINDER=$(python3 -c "
import sys, json

transcript_path = sys.argv[1]
interval = int(sys.argv[2])

try:
    # Canonical counter (parity with server): number of *user-prompt* turns
    # since the last memory save. The save marker appears in an assistant turn,
    # so we snapshot the running user-turn count whenever a save is seen.
    user_turns = 0
    user_turns_at_last_save = 0

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
            if entry_type == 'user':
                user_turns += 1
            elif entry_type == 'assistant':
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
                    user_turns_at_last_save = user_turns

    turns_since_save = user_turns - user_turns_at_last_save
    if turns_since_save >= interval:
        print(f'mem-mesh에 {turns_since_save}턴 동안 저장하지 않았습니다. 중요한 결정/버그 수정/설계 변경이 있었다면 mcp__mem-mesh__add로 저장하세요.')
except Exception:
    pass
" "$TRANSCRIPT_PATH" "$SAVE_REMINDER_INTERVAL" 2>/dev/null) || REMINDER=""

  [ -n "$REMINDER" ] && PARTS+=("$REMINDER")
fi

# ── Part 3: Pin tracking reminder (no auto-creation) ──
if [ ${#PROMPT} -ge 15 ]; then
  PIN_REMINDER=$(curl -s --max-time 2 \
    "${API_URL}/api/work/pins?project_id=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")&status=open&limit=1" \
    2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    pins = data if isinstance(data, list) else data.get('pins', data.get('results', []))
    if len(pins) == 0:
        print('현재 추적 중인 pin이 없습니다. 작업 요청이라면 pin_add를 호출하세요.')
except Exception:
    pass
" 2>/dev/null) || PIN_REMINDER=""
  [ -n "$PIN_REMINDER" ] && PARTS+=("$PIN_REMINDER")
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
