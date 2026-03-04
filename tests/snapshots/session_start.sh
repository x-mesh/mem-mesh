#!/bin/bash
# mem-mesh-hooks prompt-version: 8
# Claude Code SessionStart hook: inject mem-mesh session context
# Fires on session start AND after compaction (context re-injection)
# Returns additional_context JSON via /api/work/sessions/resume/{project_id}

set -euo pipefail
command -v jq >/dev/null 2>&1 || { echo '{}'; exit 0; }
command -v curl >/dev/null 2>&1 || { echo '{}'; exit 0; }

API_URL="${MEM_MESH_API_URL:-https://meme.24x365.online}"

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
1. **코딩 응답 우선** — 코드와 답변을 먼저 출력. mem-mesh 호출은 답변 완료 후 수행. 응답 서두에 '메모리를 검색하겠습니다' 같은 안내를 넣지 않는다.
2. **Pin으로 작업 추적** — 작업 시작 시 pin_add(content, project_id="mem-mesh", importance=3), 완료 시 pin_complete. (importance: 3=일반, 4=중요, 5=아키텍처)
3. **영구 메모리는 선별적** — decision, bug, incident, idea, code_snippet만 add()로 저장. 일상적 작업 상태는 pin으로 충분.
4. **맥락 검색 활용** — 과거 결정/작업/설계가 언급되면 코드 작성 전에 search()로 기존 맥락 확인.
5. **세션 종료** — 사용자가 완료를 명시하면 요청 처리 후 session_end(project_id="mem-mesh")."

jq -n --arg ctx "$CONTEXT" '{ additional_context: $ctx }'
