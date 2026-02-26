#!/bin/bash
# mem-mesh-hooks prompt-version: 1
# mem-mesh Session Start Hook for Cursor (project-local)
# Injects mem-mesh usage instructions into the session context.

set -euo pipefail

INPUT=$(cat)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

RESUME_OUTPUT=""
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

RULES_TEXT="1. **코딩 응답 우선** — 코드와 답변을 먼저 출력. mem-mesh 호출은 답변 완료 후 수행. 응답 서두에 '메모리를 검색하겠습니다' 같은 안내를 넣지 않는다.
2. **Pin으로 작업 추적** — 작업 시작 시 pin_add(content, project_id="mem-mesh", importance=3), 완료 시 pin_complete. (importance: 3=일반, 4=중요, 5=아키텍처)
3. **영구 메모리는 선별적** — decision, bug, incident, idea, code_snippet만 add()로 저장. 일상적 작업 상태는 pin으로 충분.
4. **맥락 검색 활용** — 과거 결정/작업/설계가 언급되면 코드 작성 전에 search()로 기존 맥락 확인.
5. **세션 종료** — 사용자가 완료를 명시하면 요청 처리 후 session_end(project_id="mem-mesh")."

CONTEXT="## mem-mesh Memory Integration (Auto-loaded)

### 세션 복원 결과
\`\`\`json
${RESUME_OUTPUT}
\`\`\`

### 작업 규칙
$RULES_TEXT"

python3 -c "
import json, sys
ctx = sys.stdin.read()
print(json.dumps({'additional_context': ctx}))
" <<< "$CONTEXT"
