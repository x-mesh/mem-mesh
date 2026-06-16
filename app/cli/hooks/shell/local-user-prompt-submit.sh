#!/bin/bash
__VERSION_MARKER__
# UserPromptSubmit hook: keyword-filtered context search + save reminder + pin tracking (local mode)
# stdin: {prompt, session_id, transcript_path, cwd, ...}
# Output: {hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: "..."}} or exit 0

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

MEM_MESH_PATH=__MEM_MESH_PATH__

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
[ -z "$PROMPT" ] && exit 0

# ── Write-signal gate ──
# Reminders are evidence-based: they fire only when the transcript shows a real
# file edit (Edit/Write/MultiEdit/NotebookEdit) since the last save — never on a
# read-only turn. Set MEM_MESH_REMINDER_REQUIRE_WRITE=0 to disable (legacy).
REQUIRE_WRITE="${MEM_MESH_REMINDER_REQUIRE_WRITE:-1}"
WORK_DONE=1
case "$(printf '%s' "$REQUIRE_WRITE" | tr '[:upper:]' '[:lower:]')" in
  0|false|no|off) WORK_DONE=1 ;;  # gate disabled → always allow
  *)
    WORK_DONE=0
    if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
      WORK_DONE=$(python3 -c "
import sys, json
transcript_path = sys.argv[1]
WRITE_TOOLS = {'Edit', 'Write', 'MultiEdit', 'NotebookEdit'}
turn = last_save_turn = last_write_turn = 0
try:
    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get('type') != 'assistant':
                continue
            turn += 1
            content = entry.get('message', {}).get('content', '')
            if isinstance(content, list):
                names = [c.get('name', '') for c in content if isinstance(c, dict)]
                text = ' '.join(c.get('text', '') for c in content if isinstance(c, dict))
            else:
                names, text = [], str(content)
            if 'mcp__mem-mesh__add' in text or 'mcp__mem-mesh__pin_add' in text or \
               'mcp__mem-mesh__add' in ' '.join(names) or 'mcp__mem-mesh__pin_add' in ' '.join(names):
                last_save_turn = turn
            if any(n in WRITE_TOOLS for n in names):
                last_write_turn = turn
    print('1' if last_write_turn > last_save_turn else '0')
except Exception:
    print('0')
" "$TRANSCRIPT_PATH" 2>/dev/null) || WORK_DONE=0
    fi
    ;;
esac

PARTS=()

# ── Part 1: Keyword-filtered memory search (local) ──
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
    QUERY=$(printf '%s' "$PROMPT" | python3 -c 'import sys; print(sys.stdin.read()[:200], end="")')
    THRESHOLD="${MEM_MESH_SEARCH_THRESHOLD:-0.75}"
    LIMIT="${MEM_MESH_SEARCH_LIMIT:-3}"

    SEARCH_CTX=$(python3 - "$MEM_MESH_PATH" "$QUERY" "$PROJECT_DIR" "$THRESHOLD" "$LIMIT" 2>/dev/null <<'PY'
import sys, asyncio, json
mem_mesh_path, query, project_dir, threshold_raw, limit_raw = sys.argv[1:6]
sys.path.insert(0, mem_mesh_path)
try:
    from app.core.storage.direct import DirectStorageManager

    async def search():
        s = DirectStorageManager()
        await s.initialize()
        results = await s.search_memories(
            query=query,
            project_id=project_dir,
            limit=int(limit_raw),
        )
        if not results:
            sys.exit(0)
        threshold = float(threshold_raw)
        relevant = [r for r in results if r.get('similarity_score', 0) > threshold]
        if not relevant:
            sys.exit(0)
        lines = ['## Related Memories (auto-retrieved)', '']
        for r in relevant[:int(limit_raw)]:
            cat = r.get('category', 'unknown')
            content = r.get('content', '')[:300]
            created = str(r.get('created_at', ''))[:10]
            lines.append(f'- [{cat}] ({created}) {content}')
        print('\n'.join(lines))

    asyncio.run(search())
except Exception:
    sys.exit(0)
PY
) || SEARCH_CTX=""
    [ -n "$SEARCH_CTX" ] && PARTS+=("$SEARCH_CTX")
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
    assistant_turns = 0
    last_save_turn = 0
    turn = 0

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
                assistant_turns = turn

    parts = []
    turns_since_save = assistant_turns - last_save_turn
    if turns_since_save >= interval and assistant_turns >= interval:
        parts.append(f'mem-mesh에 {turns_since_save}턴 동안 저장하지 않았습니다. 중요한 결정/버그 수정/설계 변경이 있었다면 mcp__mem-mesh__add로 저장하세요.')

    if parts:
        print('\n'.join(parts))
except Exception:
    pass
" "$TRANSCRIPT_PATH" "$SAVE_REMINDER_INTERVAL" 2>/dev/null) || REMINDER=""

  [ -n "$REMINDER" ] && [ "$WORK_DONE" = "1" ] && PARTS+=("$REMINDER")
fi

# ── Part 3: Pin tracking reminder (no auto-creation) ──
# "Tracked" = open OR in_progress (pin_add creates in_progress by default).
# in_progress first so the common case needs one request; the status filter
# is exact-match, so each status is its own request.
LOCAL_API_URL="${MEM_MESH_API_URL:-http://localhost:8000}"
HOOK_TOKEN="${MEM_MESH_HOOK_TOKEN:-$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)}"
AUTH=()
if [ -n "$HOOK_TOKEN" ]; then
  AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}")
fi
if [ ${#PROMPT} -ge 15 ] && [ "$WORK_DONE" = "1" ]; then
  PIN_PROJECT=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
  NO_TRACKED_PINS=1
  for PIN_STATUS in in_progress open; do
    PIN_COUNT=$(curl -s --max-time 2 \
      ${AUTH[@]+"${AUTH[@]}"} \
      "${LOCAL_API_URL}/api/work/pins?project_id=${PIN_PROJECT}&status=${PIN_STATUS}&limit=1" \
      2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
if isinstance(data, list):
    pins = data
elif 'pins' in data or 'results' in data:
    pins = data.get('pins') or data.get('results') or []
else:
    sys.exit(1)
print(len(pins))
" 2>/dev/null) || PIN_COUNT=""
    # Non-zero count = tracked pin found; empty = API error. Both stay quiet.
    if [ "$PIN_COUNT" != "0" ]; then
      NO_TRACKED_PINS=0
      break
    fi
  done
  if [ "$NO_TRACKED_PINS" -eq 1 ]; then
    PARTS+=('현재 추적 중인 pin이 없습니다. 작업 요청이라면 pin_add를 호출하세요.')
  fi
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
