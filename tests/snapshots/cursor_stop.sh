#!/bin/bash
# mem-mesh-hooks prompt-version: 8
# Cursor stop hook: conditionally suggest saving to mem-mesh
# stdin: {"last_assistant_message":"...", "transcript":[...]} JSON

set -euo pipefail

INPUT=$(cat)

# Check if there were meaningful tool uses (file edits, code changes)
HAS_TOOL_USE=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    transcript = data.get('transcript', [])
    meaningful = any(
        msg.get('type') == 'tool_use' and
        msg.get('tool_name', '') in ('Edit', 'Write', 'Bash', 'NotebookEdit')
        for msg in transcript
        if isinstance(msg, dict)
    )
    print('true' if meaningful else 'false')
except Exception:
    print('false')
" 2>/dev/null) || HAS_TOOL_USE="false"

if [ "$HAS_TOOL_USE" = "true" ]; then
    python3 -c "
import json
print(json.dumps({'followup_message': '''방금 완료한 작업이 중요하다면, mem-mesh에 기록해주세요.

**저장 기준**: 버그 진단/해결, 아키텍처 또는 설계 결정, 중요 설정 변경 또는 마이그레이션
**스킵 기준**: 단순 질문/답변 ("뭐야?", "보여줘"), 파일 읽기만 한 경우, 이미 저장된 내용의 반복, hook/설정 자체의 점검·수정·메타 대화 (hook 동작 확인, settings.json 수정 포함)

저장 시: 버그 수정은 category="bug", 설계 결정은 category="decision", 코드 패턴은 category="code_snippet"으로 add(project_id="mem-mesh")를 호출하세요.
일상적 작업이었다면 무시하세요.'''}))
"
else
    echo '{}'
fi
