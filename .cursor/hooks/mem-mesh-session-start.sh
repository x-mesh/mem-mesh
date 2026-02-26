#!/bin/bash
# mem-mesh Session Start Hook for Cursor
# Injects mem-mesh usage instructions into the session context
# and attempts to load previous session pins.

set -euo pipefail

# Read stdin (Cursor session info)
INPUT=$(cat)

# Try to get session resume data from mem-mesh
RESUME_OUTPUT=""
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

RESUME_OUTPUT=$(python3 -c "
import sys, json
sys.path.insert(0, '$PROJECT_ROOT')
try:
    from app.core.services.pin_service import PinService
    from app.core.storage.direct import DirectStorageManager
    import asyncio

    async def get_resume():
        storage = DirectStorageManager()
        await storage.initialize()
        pin_svc = PinService(storage)
        result = await pin_svc.session_resume('mem-mesh', expand='smart')
        return json.dumps(result, ensure_ascii=False, default=str)

    print(asyncio.run(get_resume()))
except Exception as e:
    print(json.dumps({'error': str(e)}))
" 2>/dev/null) || RESUME_OUTPUT='{"error": "mem-mesh not available"}'

# Build additional context
CONTEXT="## mem-mesh Memory Integration (Auto-loaded by Cursor Hook)

이 프로젝트에는 mem-mesh MCP 서버가 연결되어 있습니다. 아래 규칙에 따라 작업하세요.

### 세션 복원 결과
\`\`\`json
${RESUME_OUTPUT}
\`\`\`

### 작업 규칙
1. **코딩 응답 우선** — 코드와 답변을 먼저 출력. mem-mesh 호출은 답변 후.
2. **Pin으로 작업 추적** — 작업 시작 시 \`pin_add(content, project_id=\"mem-mesh\", importance=3)\`, 완료 시 \`pin_complete\`.
3. **영구 메모리는 선별적** — decision, bug, incident, idea, code_snippet만 \`add\`로 저장.
4. **맥락 검색 활용** — 과거 결정/작업 언급 시 \`search\`로 확인.
5. **세션 종료** — 사용자가 완료를 명시하면 \`session_end(project_id=\"mem-mesh\")\`."

# Output JSON for Cursor
python3 -c "
import json, sys
ctx = sys.stdin.read()
print(json.dumps({'additional_context': ctx}))
" <<< "$CONTEXT"
