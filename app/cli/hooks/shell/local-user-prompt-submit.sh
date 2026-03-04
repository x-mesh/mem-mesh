#!/bin/bash
__VERSION_MARKER__
# UserPromptSubmit hook: keyword-filtered context search + save reminder + auto pin (local mode)
# stdin: {prompt, session_id, transcript_path, cwd, ...}
# Output: {hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: "..."}} or exit 0

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
[ -z "$PROMPT" ] && exit 0

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
    QUERY=$(echo "$PROMPT" | head -c 200)
    THRESHOLD="${MEM_MESH_SEARCH_THRESHOLD:-0.75}"
    LIMIT="${MEM_MESH_SEARCH_LIMIT:-3}"

    SEARCH_CTX=$(python3 -c "
import sys, asyncio, json
sys.path.insert(0, '$MEM_MESH_PATH')
try:
    from app.core.storage.direct import DirectStorageManager

    async def search():
        s = DirectStorageManager()
        await s.initialize()
        results = await s.search_memories(
            query=sys.argv[1],
            project_id=sys.argv[2],
            limit=int(sys.argv[4]),
        )
        if not results:
            sys.exit(0)
        threshold = float(sys.argv[3])
        relevant = [r for r in results if r.get('similarity_score', 0) > threshold]
        if not relevant:
            sys.exit(0)
        lines = ['## Related Memories (auto-retrieved)', '']
        for r in relevant[:int(sys.argv[4])]:
            cat = r.get('category', 'unknown')
            content = r.get('content', '')[:300]
            created = str(r.get('created_at', ''))[:10]
            lines.append(f'- [{cat}] ({created}) {content}')
        print('\n'.join(lines))

    asyncio.run(search())
except Exception:
    sys.exit(0)
" "$QUERY" "$PROJECT_DIR" "$THRESHOLD" "$LIMIT" 2>/dev/null) || SEARCH_CTX=""
    [ -n "$SEARCH_CTX" ] && PARTS+=("$SEARCH_CTX")
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
                if 'mcp__mem-mesh__pin_add' in content_str or 'pin_add' in content_str:
                    pin_add_count += content_str.count('pin_add')
                if 'mcp__mem-mesh__pin_complete' in content_str or 'pin_complete' in content_str:
                    pin_complete_count += content_str.count('pin_complete')
                assistant_turns = turn

    parts = []
    turns_since_save = assistant_turns - last_save_turn
    if turns_since_save >= interval and assistant_turns >= interval:
        parts.append(f'mem-mesh에 {turns_since_save}턴 동안 저장하지 않았습니다. 중요한 결정/버그 수정/설계 변경이 있었다면 mcp__mem-mesh__add로 저장하세요.')

    if pin_add_count > 0 and pin_complete_count == 0 and assistant_turns >= 3:
        parts.append(f'이 세션에서 pin_add가 {pin_add_count}회 호출되었지만 pin_complete는 0회입니다. 완료된 작업이 있다면 pin_complete를 호출하세요.')

    if parts:
        print('\n'.join(parts))
except Exception:
    pass
" "$TRANSCRIPT_PATH" "$SAVE_REMINDER_INTERVAL" 2>/dev/null) || REMINDER=""

  [ -n "$REMINDER" ] && PARTS+=("$REMINDER")
fi

# ── Part 3: Auto pin creation for task-like prompts ──
AUTO_PIN_ENABLED="${MEM_MESH_AUTO_PIN:-true}"
LOCAL_API_URL="${MEM_MESH_API_URL:-http://localhost:8000}"

if [ "$AUTO_PIN_ENABLED" = "true" ] && [ ${#PROMPT} -ge 15 ]; then
  PIN_RESULT=$(python3 -c "
import sys, re, json, os
try:
    import urllib.request
except ImportError:
    sys.exit(0)

prompt = sys.argv[1]
api_url = sys.argv[2]
prompt_lower = prompt.lower().strip()

# Skip: questions, greetings, short commands
skip_patterns = [
    r'^(what|how|why|where|when|who|which|can |does |is |are |do )',
    r'^(뭐|무엇|어떻|왜|어디|언제|누가|몇|할 수)',
    r'^(hi|hello|hey|안녕|ㅎㅇ|감사|고마워|ㄳ|ok|ㅇㅋ)',
    r'^(ls|cd|cat|git (log|status|diff)|pwd)',
    r'^(show|list|print|display|explain|describe|tell)',
    r'^(보여|알려|설명|확인해|점검|리뷰|분석)',
    r'^(계속|continue|yes|no|네|아니|ㅇㅇ|ㄴㄴ)',
]
if any(re.search(p, prompt_lower) for p in skip_patterns):
    sys.exit(0)

# Detect: task-like prompts (imperative action)
task_patterns = [
    r'(수정|고쳐|fix|patch|hotfix)',
    r'(구현|만들어|만들자|implement|build|create)',
    r'(추가|넣어|add|include)',
    r'(삭제|제거|remove|delete)',
    r'(변경|바꿔|change|update|modify|rename)',
    r'(리팩토링|refactor|개선|improve|optimize|최적화)',
    r'(배포|deploy|release)',
    r'(설치|install|setup|설정)',
    r'(테스트|test|검증)',
    r'(이동|move|migrate|전환)',
    r'(해줘|해봐|하자|해주세요|합시다)',
    r'(write|작성)',
]

extra_task_kw = os.environ.get('MEM_MESH_AUTO_PIN_KEYWORDS', '')
if extra_task_kw:
    task_patterns.extend(extra_task_kw.split(','))

if not any(re.search(p, prompt_lower) for p in task_patterns):
    sys.exit(0)

content = prompt.strip()[:200]
if len(content) < 10:
    content = content + ' (auto-pin)'

project_dir = os.path.basename(os.popen('git rev-parse --show-toplevel 2>/dev/null || pwd').read().strip())

payload = json.dumps({
    'content': content,
    'project_id': project_dir,
    'importance': 3,
    'tags': ['auto-pin'],
}).encode()

req = urllib.request.Request(
    f'{api_url}/api/work/pins',
    data=payload,
    headers={'Content-Type': 'application/json'},
    method='POST',
)
try:
    resp = urllib.request.urlopen(req, timeout=3)
    data = json.loads(resp.read())
    pin_id = data.get('id', '')
    if pin_id:
        print(f'[Auto-Pin] 작업 핀 생성됨: {pin_id} — 작업 완료 시 pin_complete(\"{pin_id}\")를 호출하세요. 별도로 pin_add를 호출하지 마세요.')
except Exception:
    sys.exit(0)
" "$PROMPT" "$LOCAL_API_URL" 2>/dev/null) || PIN_RESULT=""

  [ -n "$PIN_RESULT" ] && PARTS+=("$PIN_RESULT")
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
