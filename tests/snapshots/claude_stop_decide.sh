#!/bin/bash
# mem-mesh-hooks prompt-version: 12
# Stop hook: keyword-based category matching + structured save (요약+원본)
# stdin: {"stop_hook_active":bool,"last_assistant_message":"...","transcript_path":"..."} JSON
# No LLM, no API key — regex keyword matching, skip if no match

set -uo pipefail  # no -e: prevent silent failures in async hook
command -v jq >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-https://meme.24x365.online}"
LOG_FILE="${HOME}/.claude/hooks/stop-hook-debug.log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE" 2>/dev/null || true
}

INPUT=$(cat)
log "=== Stop hook fired === INPUT length: ${#INPUT}"

# Guard: prevent infinite loop
ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null) || ACTIVE="false"
[ "$ACTIVE" = "true" ] && { log "SKIP: stop_hook_active=true"; exit 0; }

# Extract fields
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty' 2>/dev/null) || MESSAGE=""
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null) || TRANSCRIPT_PATH=""
log "MESSAGE length: ${#MESSAGE}, preview: ${MESSAGE:0:150}"
[ ${#MESSAGE} -lt 50 ] && { log "SKIP: message too short (${#MESSAGE})"; echo "SKIP: message too short"; exit 0; }

# Already saved via MCP
if echo "$MESSAGE" | grep -q 'mcp__mem-mesh__add'; then
  log "SKIP: already contains mcp__mem-mesh__add"
  echo "SKIP: already saved via MCP"
  exit 0
fi

# Two-pass keyword decision:
#   Pass 1: detect completion (did the AI finish something?)
#   Pass 2: categorize what was completed
# Env override: MEM_MESH_HOOK_EXTRA_KEYWORDS (comma-separated category:pattern pairs)
EXTRA_KW="${MEM_MESH_HOOK_EXTRA_KEYWORDS:-}"
CATEGORY=$(python3 -c "
import sys, re, os

msg = sys.stdin.read().lower()
extra_kw = os.environ.get('EXTRA_KW', '')

# Pass 1: completion indicators (must match at least one)
completion = [
    r'(완료|했습니다|합니다|됩니다|done|finished|completed|resolved|fixed)',
    r'(수정|변경|추가|삭제|생성|구현|적용|배포|설치)',
    r'(updated|changed|added|removed|created|implemented|deployed|installed)',
    r'(이제|now|successfully|정상)',
    r'(커밋|commit|push|merge|PR|pull request)',
]

has_completion = any(re.search(p, msg) for p in completion)
if not has_completion:
    print('SKIP')
    sys.exit(0)

# Pass 2: categorize (each pattern is a vote; highest score wins)
category_rules = [
    # bug: error/fix related
    ('bug', [
        r'(버그|bug|에러|error|오류|exception|crash|TypeError|ValueError|KeyError)',
        r'(수정|fix|해결|resolved|patch|디버그|debug)',
        r'\b(hotfix|핫픽스)\b',
        r'\bfix:\s',
        r'(문제|issue|problem).{0,40}(해결|수정|fix)',
        r'(실패|fail).{0,40}(수정|fix|해결)',
        r'(root\s*cause|원인).{0,40}(was|은|는|확인|파악)',
        r'(regression|리그레션)',
        r'(보안|security).{0,40}(취약|vulnerab|fix|수정|패치|patch)',
    ]),
    # decision: architecture/design choices
    ('decision', [
        r'(결정|decision|decided|chose|선택|채택)',
        r'(아키텍처|architecture|설계|design).{0,60}(변경|변환|전환|decided|chose)',
        r'(전환|migration|마이그레이션|migrate)',
        r'(대신|instead|rather).{0,40}(사용|use)',
        r'(방식|approach|strategy).{0,40}(변경|바꾸|switch)',
        r'\b(breaking[\s-]?change|호환[\s-]?변경)\b',
        r'(trade[\s-]?off|트레이드)',
        r'(선택|chose|picked).{0,40}(over|instead|대신|보다)',
        r'(replace|교체|대체).{0,40}(with|로|으로)',
        r'\b(deprecated?|폐기)\b',
        r'(의존성|dependency|deps).{0,40}(추가|변경|제거|added|changed|removed|upgrade)',
    ]),
    # code_snippet: implementation
    ('code_snippet', [
        r'(구현|implement|개발|develop)',
        r'(추가|add|생성|create).{0,60}(기능|feature|함수|function|메서드|method|클래스|class|API|엔드포인트|endpoint)',
        r'(리팩토링|refactor|개선|improve|최적화|optimize)',
        r'(배포|deploy|릴리즈|release)',
        r'\bfeat:\s',
        r'\brefactor:\s',
        r'\bperf:\s',
        r'implementation\s+complete',
        r'구현\s*(완료|했습니다|끝|했음)',
        r'(새로운|new)\s+(모듈|module|파일|file|클래스|class|함수|function)',
        r'\d+\s+passed',
        r'(성능|performance).{0,40}(개선|improve|최적화|optimiz)',
    ]),
    # incident: outage/incident
    ('incident', [
        r'(장애|incident|outage|다운타임|downtime)',
        r'(서버|server|서비스|service).{0,30}(죽|down|중단|stop)',
        r'\b(rollback|롤백)\b',
        r'(production|프로덕션|운영).{0,40}(issue|error|장애|문제)',
    ]),
    # idea: suggestions
    ('idea', [
        r'(아이디어|idea|제안|suggest|proposal)',
        r'(고려|consider|검토|review).{0,40}(해볼|해보|worth)',
        r'(향후|future|나중에|later).{0,60}(개선|improvement|고려|consider|추가)',
        r'(개선\s*사항|improvement).{0,40}(제안|suggest|필요|need)',
    ]),
]

# Add extra keywords from env
if extra_kw:
    for pair in extra_kw.split(','):
        pair = pair.strip()
        if ':' in pair:
            cat, pat = pair.split(':', 1)
            for rules in category_rules:
                if rules[0] == cat.strip():
                    rules[1].append(pat.strip())
                    break

# Score each category: count how many patterns match
best_cat = 'SKIP'
best_score = 0
for cat, patterns in category_rules:
    score = sum(1 for p in patterns if re.search(p, msg))
    if score > best_score:
        best_score = score
        best_cat = cat

# Require at least 1 category pattern match
if best_score < 1:
    best_cat = 'SKIP'

print(best_cat)
" <<< "$MESSAGE" 2>/dev/null) || CATEGORY="SKIP"

log "CATEGORY: $CATEGORY"

# ── Section A: Save memory (only if keyword matched) ──
if [ "$CATEGORY" != "SKIP" ]; then
  log "MATCH: saving as category=$CATEGORY"

  # Build content: Q&A from transcript + answer (no LLM summary)
  CONTENT=$(python3 -c "
import sys, json

message = sys.argv[1]
transcript_path = sys.argv[2]

user_question = ''
if transcript_path:
    try:
        with open(transcript_path, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get('type') == 'user':
                        msg = entry.get('message', {})
                        content = msg.get('content', '')
                        if isinstance(content, list):
                            texts = [c.get('text','') for c in content if c.get('type')=='text']
                            content = ' '.join(texts)
                        if isinstance(content, str) and len(content.strip()) > 5:
                            user_question = content.strip()[:500]
                except:
                    pass
    except:
        pass

if user_question:
    print(f'Q: {user_question}\n\nA: {message[:9000]}'[:9500])
else:
    print(message[:9500])
" "$MESSAGE" "$TRANSCRIPT_PATH" 2>/dev/null) || CONTENT="$MESSAGE"

  PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

  PAYLOAD=$(jq -n \
    --arg content "$CONTENT" \
    --arg project_id "$PROJECT_DIR" \
    --arg category "$CATEGORY" \
    --arg source "claude-code-hook" \
    --arg client "claude_code" \
    '{
      content: $content,
      project_id: $project_id,
      category: $category,
      source: $source,
      client: $client,
      tags: ["auto-save", "keyword", $category]
    }')

  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    -X POST "${API_URL}/api/memories" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" 2>/dev/null) || HTTP_CODE="000"

  if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ]; then
    SAVE_MSG="Saved memory as ${CATEGORY} (project=${PROJECT_DIR})"
  else
    SAVE_MSG="Save failed (HTTP ${HTTP_CODE}), category=${CATEGORY}"
  fi
  log "Memory save: $SAVE_MSG"
  echo "$SAVE_MSG"
else
  log "SKIP: no keyword match for memory save"
  echo "SKIP: no keyword match"
fi

# ── Section B: Auto-pin completion ──
# Complete auto-pins when completion indicators are present in the message
if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
  PIN_RESULT=$(python3 -c "
import sys, re, json
try:
    import urllib.request
except ImportError:
    sys.exit(0)

message = sys.argv[1]
transcript_path = sys.argv[2]
api_url = sys.argv[3]
msg_lower = message.lower()

# Check completion indicators (same as Pass 1)
completion = [
    r'(완료|했습니다|합니다|됩니다|done|finished|completed|resolved|fixed)',
    r'(수정|변경|추가|삭제|생성|구현|적용|배포|설치)',
    r'(updated|changed|added|removed|created|implemented|deployed|installed)',
    r'(이제|now|successfully|정상)',
    r'(커밋|commit|push|merge|PR|pull request)',
]

has_completion = any(re.search(p, msg_lower) for p in completion)
if not has_completion:
    sys.exit(0)

# Scan transcript for most recent auto-pin ID
# Pattern: [Auto-Pin] 작업 핀 생성됨: {uuid}
pin_id = None
try:
    with open(transcript_path, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                msg = entry.get('message', {})
                content = msg.get('content', '')
                if isinstance(content, list):
                    content = ' '.join(
                        c.get('text', '') for c in content if isinstance(c, dict)
                    )
                content_str = str(content)
                m = re.search(r'\[Auto-Pin\].*?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', content_str)
                if m:
                    pin_id = m.group(1)  # keep updating to get the LAST one
            except:
                pass
except:
    sys.exit(0)

if not pin_id:
    sys.exit(0)

# Complete the pin
req = urllib.request.Request(
    f'{api_url}/api/work/pins/{pin_id}/complete',
    method='PUT',
    headers={'Content-Type': 'application/json'},
)
try:
    resp = urllib.request.urlopen(req, timeout=3)
    data = json.loads(resp.read())
    print(f'Pin {pin_id} completed (status={data.get(\"status\",\"?\")})')
except urllib.error.HTTPError as e:
    if e.code == 404:
        print(f'Pin {pin_id} not found (already completed or deleted)')
    elif e.code == 400:
        print(f'Pin {pin_id} already completed')
    else:
        print(f'Pin {pin_id} complete failed: HTTP {e.code}')
except Exception as e:
    print(f'Pin {pin_id} complete failed: {e}')
" "$MESSAGE" "$TRANSCRIPT_PATH" "$API_URL" 2>/dev/null) || PIN_RESULT=""

  if [ -n "$PIN_RESULT" ]; then
    log "Auto-pin: $PIN_RESULT"
  fi
fi

log "=== Stop hook complete ==="

exit 0
