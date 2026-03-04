#!/bin/bash
# mem-mesh-hooks prompt-version: 10
# Cursor sessionStart hook: load mem-mesh session context
# Returns additional_context JSON for the agent

set -euo pipefail
command -v jq >/dev/null 2>&1 || { echo '{}'; exit 0; }
command -v curl >/dev/null 2>&1 || { echo '{}'; exit 0; }

API_URL="${MEM_MESH_API_URL:-https://meme.24x365.online}"

INPUT=$(cat)

# Detect project from CWD
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"

# Try to fetch session resume data from API
RESUME_DATA=$(curl -s --max-time 5 \
  "${API_URL}/api/work/sessions/resume/${PROJECT_DIR}?expand=smart" \
  2>/dev/null) || RESUME_DATA='{"error": "mem-mesh API not available"}'

CONTEXT="## mem-mesh Memory Integration (Auto-loaded)

### 세션 복원 결과
${RESUME_DATA}

### 작업 규칙
1. **코딩 응답 우선** — 코드와 답변을 먼저 출력. mem-mesh 호출은 답변 완료 후 수행. 응답 서두에 '메모리를 검색하겠습니다' 같은 안내를 넣지 않는다.
2. **Pin으로 작업 추적** — 작업 시작 시 pin_add(content, project_id="mem-mesh", importance=3), 완료 시 pin_complete. (importance: 3=일반, 4=중요, 5=아키텍처)
3. **영구 메모리는 선별적** — decision, bug, incident, idea, code_snippet만 add()로 저장. 일상적 작업 상태는 pin으로 충분.
4. **맥락 검색 활용** — 과거 결정/작업/설계가 언급되면 코드 작성 전에 search()로 기존 맥락 확인.
5. **세션 종료** — 사용자가 완료를 명시하면 요청 처리 후 session_end(project_id="mem-mesh")."

jq -n --arg ctx "$CONTEXT" '{ additional_context: $ctx }'
