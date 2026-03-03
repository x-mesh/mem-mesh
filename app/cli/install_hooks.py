#!/usr/bin/env python3
"""mem-mesh-hooks: Install/uninstall mem-mesh hooks for Claude Code, Kiro, and Cursor.

Prompts and behavioral rules are defined in app.cli.prompts.behaviors (single
source of truth).  IDE-specific renderers in app.cli.prompts.renderers transform
those canonical definitions into each IDE's native format.

Bump PROMPT_VERSION in behaviors.py when rules change, then re-run:
    mem-mesh-hooks install --target all
    mem-mesh-hooks sync-project
"""

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.cli.prompts.behaviors import PROMPT_VERSION, REFLECT_CONFIG
from app.cli.prompts.renderers import (
    VERSION_MARKER,
    extract_prompt_version,
    render_cursor_followup,
    render_enhanced_stop_prompt,
    render_kiro_auto_create_pin,
    render_kiro_auto_save,
    render_kiro_load_context,
    render_reflect_prompt,
    render_rules_text,
)
from app.cli.hooks.templates import (
    LOCAL_PRECOMPACT_HOOK_TEMPLATE,
    LOCAL_SESSION_END_HOOK_TEMPLATE,
    PRECOMPACT_HOOK_TEMPLATE,
    SESSION_END_HOOK_TEMPLATE,
)

DEFAULT_URL = "https://meme.24x365.online"

# ---------------------------------------------------------------------------
# Hook script templates — bash boilerplate only; prompt text comes from renderers
# ---------------------------------------------------------------------------

# The __RULES_TEXT__ placeholder is replaced with render_rules_text() output.
# The __FOLLOWUP_MSG__ placeholder is replaced with render_cursor_followup().
# The __DEFAULT_URL__ / __MEM_MESH_PATH__ are replaced at install time.

STOP_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Stop hook: save conversation summary to mem-mesh
# stdin: {"stop_hook_active":bool,"last_assistant_message":"..."} JSON

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

INPUT=$(cat)

# Prevent infinite loop
ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

# Extract message + minimum length filter
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 50 ] && exit 0

SUMMARY=$(echo "$MESSAGE" | head -c 9500)

# Extract project ID from CWD
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

PAYLOAD=$(jq -n \
  --arg content "[conversation summary] $SUMMARY" \
  --arg project_id "$PROJECT_DIR" \
  --arg source "__SOURCE_TAG__" \
  --arg client "__CLIENT_TAG__" \
  '{
    content: $content,
    project_id: $project_id,
    category: "git-history",
    source: $source,
    client: $client,
    tags: ["auto-save", "conversation", "__IDE_TAG__"]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
"""

STOP_DECIDE_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Stop hook: keyword-based category matching + structured save (요약+원본)
# stdin: {"stop_hook_active":bool,"last_assistant_message":"...","transcript_path":"..."} JSON
# No LLM, no API key — regex keyword matching, skip if no match

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

INPUT=$(cat)

# Guard: prevent infinite loop
ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

# Extract fields
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
[ ${#MESSAGE} -lt 50 ] && exit 0

# Already saved via MCP
echo "$MESSAGE" | grep -q 'mcp__mem-mesh__add' && exit 0

# Keyword decision (regex matching, SAVE patterns first)
CATEGORY=$(python3 -c "
import sys, re
msg = sys.stdin.read().lower()

save_rules = [
    (r'(버그|bug).*(수정|fix|해결|resolved|patch)', 'bug'),
    (r'(수정|fix).*(버그|bug|에러|error|오류)', 'bug'),
    (r'(에러|error|exception|오류).*(해결|수정|fixed|resolved)', 'bug'),
    (r'(결정|decision).*(변경|선택|채택|chose|decided)', 'decision'),
    (r'(아키텍처|architecture|설계).*(결정|변경|선택)', 'decision'),
    (r'(전환|migration|마이그레이션)', 'decision'),
    (r'(구현|implement).*(완료|했습니다|done)', 'code_snippet'),
    (r'(장애|incident|outage).*(발생|occurred|detected)', 'incident'),
    (r'(아이디어|idea).*(제안|suggest|고려|consider)', 'idea'),
]

for pat, cat in save_rules:
    if re.search(pat, msg):
        print(cat)
        sys.exit(0)

print('SKIP')
" <<< "$MESSAGE" 2>/dev/null) || CATEGORY="SKIP"

# No keyword match -> skip saving (M3: task is system-only category)
[ "$CATEGORY" = "SKIP" ] && exit 0

# Build content: Q&A from transcript + answer (no LLM summary)
CONTENT=$(python3 -c "
import sys, json

message = sys.argv[1]
transcript_path = sys.argv[2]

# Extract last user question from transcript
user_question = ''
if transcript_path:
    try:
        with open(transcript_path, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get('role') == 'human':
                        content = entry.get('content', '')
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

# Save to mem-mesh API
PAYLOAD=$(jq -n \
  --arg content "$CONTENT" \
  --arg project_id "$PROJECT_DIR" \
  --arg category "$CATEGORY" \
  --arg source "__SOURCE_TAG__" \
  --arg client "__CLIENT_TAG__" \
  '{
    content: $content,
    project_id: $project_id,
    category: $category,
    source: $source,
    client: $client,
    tags: ["auto-save", "keyword", $category]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
"""

SESSION_START_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Claude Code SessionStart hook: inject mem-mesh session context
# Fires on session start AND after compaction (context re-injection)
# Returns additional_context JSON via /api/work/sessions/resume/{project_id}

set -euo pipefail
command -v jq >/dev/null 2>&1 || { echo '{}'; exit 0; }
command -v curl >/dev/null 2>&1 || { echo '{}'; exit 0; }

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

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
__RULES_TEXT__"

jq -n --arg ctx "$CONTEXT" '{ additional_context: $ctx }'
"""

LOCAL_SESSION_START_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Claude Code SessionStart hook: inject mem-mesh session context (local mode)
# Fires on session start AND after compaction (context re-injection)
# Returns additional_context JSON

set -euo pipefail
command -v python3 >/dev/null 2>&1 || { echo '{}'; exit 0; }

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && PROJECT_DIR="unknown"

RESUME_DATA=$(python3 -c "
import sys, json
sys.path.insert(0, '$MEM_MESH_PATH')
try:
    from app.core.services.pin_service import PinService
    from app.core.storage.direct import DirectStorageManager
    import asyncio

    async def get_resume():
        storage = DirectStorageManager()
        await storage.initialize()
        pin_svc = PinService(storage)
        result = await pin_svc.session_resume('$PROJECT_DIR', expand='smart')
        return json.dumps(result, ensure_ascii=False, default=str)

    print(asyncio.run(get_resume()))
except Exception as e:
    print(json.dumps({'error': str(e)}))
" 2>/dev/null) || RESUME_DATA='{"error": "mem-mesh not available"}'

RULES_TEXT="__RULES_TEXT__"

CONTEXT="## mem-mesh Session Context (Auto-injected)

### Previous Session
${RESUME_DATA}

### Rules
${RULES_TEXT}"

python3 -c "
import json, sys
ctx = sys.stdin.read()
print(json.dumps({'additional_context': ctx}))
" <<< "$CONTEXT"
"""

KIRO_STOP_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Kiro agentResponse hook: keyword-based category matching + save to mem-mesh

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

RESPONSE="${KIRO_RESULT:-}"
[ ${#RESPONSE} -lt 50 ] && exit 0

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

# Keyword decision (same logic as Claude Code stop-decide)
CATEGORY=$(python3 -c "
import sys, re
msg = sys.stdin.read().lower()

save_rules = [
    (r'(버그|bug).*(수정|fix|해결|resolved|patch)', 'bug'),
    (r'(수정|fix).*(버그|bug|에러|error|오류)', 'bug'),
    (r'(에러|error|exception|오류).*(해결|수정|fixed|resolved)', 'bug'),
    (r'(결정|decision).*(변경|선택|채택|chose|decided)', 'decision'),
    (r'(아키텍처|architecture|설계).*(결정|변경|선택)', 'decision'),
    (r'(전환|migration|마이그레이션)', 'decision'),
    (r'(구현|implement).*(완료|했습니다|done)', 'code_snippet'),
    (r'(장애|incident|outage).*(발생|occurred|detected)', 'incident'),
    (r'(아이디어|idea).*(제안|suggest|고려|consider)', 'idea'),
]

for pat, cat in save_rules:
    if re.search(pat, msg):
        print(cat)
        sys.exit(0)

print('SKIP')
" <<< "$RESPONSE" 2>/dev/null) || CATEGORY="SKIP"

# No keyword match -> skip saving (M3: task is system-only category)
[ "$CATEGORY" = "SKIP" ] && exit 0

SUMMARY=$(echo "$RESPONSE" | head -c 9500)

PAYLOAD=$(jq -n \
  --arg content "[kiro response] $SUMMARY" \
  --arg project_id "$PROJECT_DIR" \
  --arg category "$CATEGORY" \
  --arg source "kiro-hook" \
  --arg client "kiro" \
  '{
    content: $content,
    project_id: $project_id,
    category: $category,
    source: $source,
    client: $client,
    tags: ["auto-save", "keyword", $category, "kiro"]
  }')

curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
"""

# Cursor sessionStart: injects rules via additional_context.
# __RULES_CONTEXT__ is replaced with render_cursor_context() output.
CURSOR_SESSION_START_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Cursor sessionStart hook: load mem-mesh session context
# Returns additional_context JSON for the agent

set -euo pipefail
command -v jq >/dev/null 2>&1 || { echo '{}'; exit 0; }
command -v curl >/dev/null 2>&1 || { echo '{}'; exit 0; }

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

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
__RULES_TEXT__"

jq -n --arg ctx "$CONTEXT" '{ additional_context: $ctx }'
"""

# Cursor stop hook with followup_message.
# __FOLLOWUP_MSG__ is replaced with render_cursor_followup() output.
CURSOR_STOP_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
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
print(json.dumps({'followup_message': '''__FOLLOWUP_MSG__'''}))
"
else
    echo '{}'
fi
"""

# ---------------------------------------------------------------------------
# Local mode hook templates (python direct, no curl)
# ---------------------------------------------------------------------------

LOCAL_STOP_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Stop hook: save conversation summary to mem-mesh (local mode)

set -euo pipefail
command -v python3 >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 50 ] && exit 0

SUMMARY=$(echo "$MESSAGE" | head -c 9500)
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

python3 -c "
import sys, asyncio, json
sys.path.insert(0, '$MEM_MESH_PATH')
from app.core.storage.direct import DirectStorageManager
async def save():
    s = DirectStorageManager()
    await s.initialize()
    await s.add_memory(
        content='[conversation summary] ' + $(python3 -c "import json; print(json.dumps('''$SUMMARY'''))"),
        project_id='$PROJECT_DIR',
        category='git-history',
        source='hook-local',
        tags=['auto-save', 'conversation'],
    )
asyncio.run(save())
" 2>/dev/null || true

exit 0
"""


# ---------------------------------------------------------------------------
# Reflect hook templates (Enhanced profile — LLM analysis via Haiku)
# ---------------------------------------------------------------------------

# __REFLECT_PROMPT__ is replaced with render_reflect_prompt() output.
# __REFLECT_MODEL__, __REFLECT_MAX_TOKENS__, __REFLECT_TIMEOUT__ from REFLECT_CONFIG.

REFLECT_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Stop hook (enhanced): LLM reflection — analyze conversation and save structured insights
# Requires ANTHROPIC_API_KEY env var
# stdin: {"stop_hook_active":bool,"last_assistant_message":"..."} JSON

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

[ -z "${ANTHROPIC_API_KEY:-}" ] && exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

INPUT=$(cat)

# Prevent infinite loop
ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

# Extract message + minimum length filter
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 100 ] && exit 0

# Truncate to fit within API limits (leave room for prompt + analysis output)
CONVERSATION=$(echo "$MESSAGE" | head -c 6000)

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

# Call Haiku for reflection analysis
ANALYSIS=$(python3 -c "
import json, urllib.request, urllib.error, os, sys

api_key = os.environ.get('ANTHROPIC_API_KEY', '')
if not api_key:
    sys.exit(0)

conversation = sys.stdin.read()
prompt = '''__REFLECT_PROMPT__'''

payload = json.dumps({
    'model': '__REFLECT_MODEL__',
    'max_tokens': __REFLECT_MAX_TOKENS__,
    'messages': [{'role': 'user', 'content': f'{prompt}\n\n---\n\n{conversation}'}],
}).encode()

req = urllib.request.Request(
    'https://api.anthropic.com/v1/messages',
    data=payload,
    headers={
        'Content-Type': 'application/json',
        'x-api-key': api_key,
        'anthropic-version': '2023-06-01',
    },
)

try:
    with urllib.request.urlopen(req, timeout=__REFLECT_TIMEOUT__) as resp:
        result = json.loads(resp.read())
        text = result.get('content', [{}])[0].get('text', '')
        print(text)
except Exception:
    sys.exit(0)
" <<< "$CONVERSATION" 2>/dev/null) || exit 0

[ -z "$ANALYSIS" ] && exit 0

# Build combined content: raw context + LLM analysis
RAW_SUMMARY=$(echo "$CONVERSATION" | head -c 3000)
CONTENT="## Raw Context
${RAW_SUMMARY}

## LLM Analysis
${ANALYSIS}"

# Limit to API max (10000 chars)
CONTENT=$(echo "$CONTENT" | head -c 9500)

PAYLOAD=$(jq -n \
  --arg content "$CONTENT" \
  --arg project_id "$PROJECT_DIR" \
  --arg client "__CLIENT_TAG__" \
  '{
    content: $content,
    project_id: $project_id,
    category: "decision",
    source: "hook-reflect",
    client: $client,
    tags: ["auto-save", "llm-reflection", "enhanced"]
  }')

curl -s -o /dev/null --max-time 10 \
  -X POST "${API_URL}/api/memories" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" 2>/dev/null || true

exit 0
"""

LOCAL_REFLECT_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Stop hook (enhanced, local): LLM reflection — analyze conversation and save structured insights
# Requires ANTHROPIC_API_KEY env var
# Writes directly to local SQLite via Python

set -euo pipefail
command -v python3 >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

[ -z "${ANTHROPIC_API_KEY:-}" ] && exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 100 ] && exit 0

CONVERSATION=$(echo "$MESSAGE" | head -c 6000)
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

python3 -c "
import sys, asyncio, json, urllib.request, urllib.error, os

api_key = os.environ.get('ANTHROPIC_API_KEY', '')
if not api_key:
    sys.exit(0)

conversation = sys.stdin.read()
prompt = '''__REFLECT_PROMPT__'''

# Call Haiku for analysis
payload = json.dumps({
    'model': '__REFLECT_MODEL__',
    'max_tokens': __REFLECT_MAX_TOKENS__,
    'messages': [{'role': 'user', 'content': f'{prompt}\n\n---\n\n{conversation}'}],
}).encode()

req = urllib.request.Request(
    'https://api.anthropic.com/v1/messages',
    data=payload,
    headers={
        'Content-Type': 'application/json',
        'x-api-key': api_key,
        'anthropic-version': '2023-06-01',
    },
)

try:
    with urllib.request.urlopen(req, timeout=__REFLECT_TIMEOUT__) as resp:
        result = json.loads(resp.read())
        analysis = result.get('content', [{}])[0].get('text', '')
except Exception:
    sys.exit(0)

if not analysis:
    sys.exit(0)

raw_summary = conversation[:3000]
content = f'## Raw Context\n{raw_summary}\n\n## LLM Analysis\n{analysis}'
content = content[:9500]

sys.path.insert(0, '$MEM_MESH_PATH')
from app.core.storage.direct import DirectStorageManager

async def save():
    s = DirectStorageManager()
    await s.initialize()
    await s.add_memory(
        content=content,
        project_id='$PROJECT_DIR',
        category='decision',
        source='hook-reflect',
        tags=['auto-save', 'llm-reflection', 'enhanced'],
    )

asyncio.run(save())
" <<< "$CONVERSATION" 2>/dev/null || true

exit 0
"""


# ---------------------------------------------------------------------------
# Enhanced stop hook templates (Haiku API → save/skip → mem-mesh API)
# ---------------------------------------------------------------------------

# __ENHANCED_PROMPT__ is replaced with render_enhanced_stop_prompt() output.

ENHANCED_STOP_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Stop hook (enhanced): Haiku API decides save/skip, then saves via mem-mesh API
# Requires ANTHROPIC_API_KEY env var
# stdin: {"stop_hook_active":bool,"last_assistant_message":"..."} JSON

set -euo pipefail
command -v jq >/dev/null 2>&1 || exit 0

[ -z "${ANTHROPIC_API_KEY:-}" ] && exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

INPUT=$(cat)

# Prevent infinite loop
ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

# Extract message + minimum length filter
MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 100 ] && exit 0

# Check if already saved in this turn
echo "$MESSAGE" | grep -q 'mcp__mem-mesh__add' && exit 0

# Truncate to fit within API limits
CONVERSATION=$(echo "$MESSAGE" | head -c 6000)

PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

# Call Haiku for save/skip decision, then save if needed
python3 -c "
import json, urllib.request, urllib.error, os, sys

api_key = os.environ.get('ANTHROPIC_API_KEY', '')
if not api_key:
    sys.exit(0)

conversation = sys.stdin.read()
prompt = '''__ENHANCED_PROMPT__'''

payload = json.dumps({
    'model': '__REFLECT_MODEL__',
    'max_tokens': 100,
    'messages': [{'role': 'user', 'content': f'{prompt}\n\n---\n\n{conversation}'}],
}).encode()

req = urllib.request.Request(
    'https://api.anthropic.com/v1/messages',
    data=payload,
    headers={
        'Content-Type': 'application/json',
        'x-api-key': api_key,
        'anthropic-version': '2023-06-01',
    },
)

try:
    with urllib.request.urlopen(req, timeout=__REFLECT_TIMEOUT__) as resp:
        result = json.loads(resp.read())
        text = result.get('content', [{}])[0].get('text', '').strip()
except Exception:
    sys.exit(0)

if not text or text == 'SKIP' or not text.startswith('SAVE|'):
    sys.exit(0)

# Parse SAVE|category|summary
parts = text.split('|', 2)
if len(parts) < 3:
    sys.exit(0)

category = parts[1].strip()
summary = parts[2].strip()[:200]

valid_categories = ('bug', 'decision', 'code_snippet', 'idea', 'incident')
if category not in valid_categories:
    category = 'decision'

# Build payload with json.dumps for safety
content = summary + '\n\n---\n\n' + conversation[:3000]
save_payload = json.dumps({
    'content': content[:9500],
    'project_id': '$PROJECT_DIR',
    'category': category,
    'source': 'hook-enhanced',
    'tags': ['auto-save', 'enhanced', category],
})

# Save via mem-mesh API
save_req = urllib.request.Request(
    '$API_URL' + '/api/memories',
    data=save_payload.encode(),
    headers={'Content-Type': 'application/json'},
)
try:
    with urllib.request.urlopen(save_req, timeout=5) as resp:
        pass
except Exception:
    pass
" <<< "$CONVERSATION" 2>/dev/null || true

exit 0
"""

LOCAL_ENHANCED_STOP_HOOK_TEMPLATE = r"""#!/bin/bash
__VERSION_MARKER__
# Stop hook (enhanced, local): Haiku API decides save/skip, saves to local SQLite
# Requires ANTHROPIC_API_KEY env var

set -euo pipefail
command -v python3 >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0

[ -z "${ANTHROPIC_API_KEY:-}" ] && exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

INPUT=$(cat)

ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

MESSAGE=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')
[ ${#MESSAGE} -lt 100 ] && exit 0

echo "$MESSAGE" | grep -q 'mcp__mem-mesh__add' && exit 0

CONVERSATION=$(echo "$MESSAGE" | head -c 6000)
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")

python3 -c "
import sys, asyncio, json, urllib.request, urllib.error, os

api_key = os.environ.get('ANTHROPIC_API_KEY', '')
if not api_key:
    sys.exit(0)

conversation = sys.stdin.read()
prompt = '''__ENHANCED_PROMPT__'''

payload = json.dumps({
    'model': '__REFLECT_MODEL__',
    'max_tokens': 100,
    'messages': [{'role': 'user', 'content': f'{prompt}\n\n---\n\n{conversation}'}],
}).encode()

req = urllib.request.Request(
    'https://api.anthropic.com/v1/messages',
    data=payload,
    headers={
        'Content-Type': 'application/json',
        'x-api-key': api_key,
        'anthropic-version': '2023-06-01',
    },
)

try:
    with urllib.request.urlopen(req, timeout=__REFLECT_TIMEOUT__) as resp:
        result = json.loads(resp.read())
        text = result.get('content', [{}])[0].get('text', '').strip()
except Exception:
    sys.exit(0)

if not text or text == 'SKIP' or not text.startswith('SAVE|'):
    sys.exit(0)

parts = text.split('|', 2)
if len(parts) < 3:
    sys.exit(0)

category = parts[1].strip()
summary = parts[2].strip()[:200]

valid_categories = ('bug', 'decision', 'code_snippet', 'idea', 'incident')
if category not in valid_categories:
    category = 'decision'

content = summary + '\n\n---\n\n' + conversation[:3000]
content = content[:9500]

sys.path.insert(0, '$MEM_MESH_PATH')
from app.core.storage.direct import DirectStorageManager

async def save():
    s = DirectStorageManager()
    await s.initialize()
    await s.add_memory(
        content=content,
        project_id='$PROJECT_DIR',
        category=category,
        source='hook-enhanced',
        tags=['auto-save', 'enhanced', category],
    )

asyncio.run(save())
" <<< "$CONVERSATION" 2>/dev/null || true

exit 0
"""


# ---------------------------------------------------------------------------
# Hook profiles
# ---------------------------------------------------------------------------

HOOK_PROFILES = {
    "standard": {
        "description": "Keyword matching + structured save (no LLM, no API key, 요약+원본)",
        "hooks": ["session-start", "stop-decide"],
    },
    "enhanced": {
        "description": "Haiku API decision + structured analysis (requires ANTHROPIC_API_KEY)",
        "hooks": ["session-start", "stop-enhanced"],
    },
    "minimal": {
        "description": "Simple truncated save (async, no LLM, no decision making)",
        "hooks": ["session-start", "stop"],
    },
}


# ---------------------------------------------------------------------------
# Claude Code hooks settings patch
# ---------------------------------------------------------------------------


def _build_claude_hooks_settings(profile: str = "standard") -> Dict[str, Any]:
    """Build Claude Code hooks settings dynamically based on profile.

    Profiles:
      - minimal: command-based stop hook (no LLM cost, simple truncation)
      - standard: native prompt-based stop hook (hybrid summarization via Haiku)
      - enhanced: prompt stop + async reflect command (structured analysis)
    """
    settings: Dict[str, Any] = {"hooks": {}}

    # SessionStart: inject session context (all profiles)
    settings["hooks"]["SessionStart"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "~/.claude/hooks/mem-mesh-session-start.sh",
                    "timeout": 15,
                }
            ]
        }
    ]

    stop_entries: List[Dict[str, Any]] = []

    if profile == "standard":
        # Keyword matching command hook (no LLM, no API key)
        stop_entries.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "~/.claude/hooks/mem-mesh-stop-decide.sh",
                        "timeout": 10,
                        "async": True,
                    }
                ]
            }
        )
    elif profile == "enhanced":
        # Async command hook: Haiku API decides save/skip, saves directly
        stop_entries.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "~/.claude/hooks/mem-mesh-stop-enhanced.sh",
                        "timeout": 20,
                        "async": True,
                    }
                ]
            }
        )
    else:
        # minimal: old-style command hook (truncate + save via API/local)
        stop_entries.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "~/.claude/hooks/mem-mesh-stop.sh",
                        "timeout": 10,
                        "async": True,
                    }
                ]
            }
        )

    settings["hooks"]["Stop"] = stop_entries

    # SessionEnd: auto-end session on exit (all profiles)
    settings["hooks"]["SessionEnd"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "~/.claude/hooks/mem-mesh-session-end.sh",
                    "timeout": 10,
                }
            ]
        }
    ]

    # PreCompact: auto-end session before context compaction (all profiles)
    settings["hooks"]["PreCompact"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "~/.claude/hooks/mem-mesh-precompact.sh",
                    "timeout": 10,
                }
            ]
        }
    ]

    return settings


CLAUDE_HOOKS_SETTINGS: Dict[str, Any] = _build_claude_hooks_settings("standard")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_template(
    template: str,
    url: str,
    *,
    source_tag: str = "claude-code-hook",
    ide_tag: str = "claude",
    client_tag: str = "claude_code",
    project_id: str = "mem-mesh",
) -> str:
    """Replace all placeholders in a template string."""
    result = template.replace("__DEFAULT_URL__", url)
    result = result.replace("__VERSION_MARKER__", VERSION_MARKER)
    result = result.replace("__SOURCE_TAG__", source_tag)
    result = result.replace("__IDE_TAG__", ide_tag)
    result = result.replace("__CLIENT_TAG__", client_tag)
    # Inject renderer-generated text
    result = result.replace("__RULES_TEXT__", render_rules_text(project_id))
    result = result.replace("__FOLLOWUP_MSG__", render_cursor_followup(project_id))
    # Reflect hook placeholders
    result = result.replace("__REFLECT_PROMPT__", render_reflect_prompt())
    result = result.replace("__REFLECT_MODEL__", REFLECT_CONFIG.model)
    result = result.replace("__REFLECT_MAX_TOKENS__", str(REFLECT_CONFIG.max_tokens))
    result = result.replace("__REFLECT_TIMEOUT__", str(REFLECT_CONFIG.timeout_seconds))
    # Enhanced stop hook prompt
    result = result.replace("__ENHANCED_PROMPT__", render_enhanced_stop_prompt())
    return result


def _render_local_template(
    template: str,
    mem_mesh_path: str,
    *,
    project_id: str = "mem-mesh",
) -> str:
    """Replace placeholders for local mode templates."""
    result = template.replace("__MEM_MESH_PATH__", mem_mesh_path)
    result = result.replace("__VERSION_MARKER__", VERSION_MARKER)
    result = result.replace("__RULES_TEXT__", render_rules_text(project_id))
    result = result.replace("__FOLLOWUP_MSG__", render_cursor_followup(project_id))
    # Reflect hook placeholders
    result = result.replace("__REFLECT_PROMPT__", render_reflect_prompt())
    result = result.replace("__REFLECT_MODEL__", REFLECT_CONFIG.model)
    result = result.replace("__REFLECT_MAX_TOKENS__", str(REFLECT_CONFIG.max_tokens))
    result = result.replace("__REFLECT_TIMEOUT__", str(REFLECT_CONFIG.timeout_seconds))
    # Enhanced stop hook prompt
    result = result.replace("__ENHANCED_PROMPT__", render_enhanced_stop_prompt())
    return result


def _write_script(path: Path, content: str) -> None:
    """Write a shell script and make it executable."""
    unresolved = re.findall(r"__[A-Z0-9_]+__", content)
    if unresolved:
        tokens = ", ".join(sorted(set(unresolved)))
        raise ValueError(f"Unresolved template tokens in {path}: {tokens}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _is_mem_mesh_hook(hook: Dict[str, Any]) -> bool:
    """Return True if a hook definition belongs to mem-mesh."""
    hook_type = str(hook.get("type", ""))
    command = str(hook.get("command", ""))
    prompt = str(hook.get("prompt", ""))
    if "mem-mesh-" in command:
        return True
    if hook_type == "prompt" and "mcp__mem-mesh__add" in prompt:
        return True
    return False


def _is_mem_mesh_entry(entry: Dict[str, Any]) -> bool:
    """Return True if a hook entry contains mem-mesh managed hooks."""
    if _is_mem_mesh_hook(entry):
        return True
    hooks = entry.get("hooks", [])
    if not isinstance(hooks, list):
        return False
    return any(isinstance(hook, dict) and _is_mem_mesh_hook(hook) for hook in hooks)


def _merge_hook_entries(
    existing_entries: List[Dict[str, Any]],
    patch_entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge event entries while preserving non mem-mesh user hooks."""
    preserved = [
        entry
        for entry in existing_entries
        if isinstance(entry, dict) and not _is_mem_mesh_entry(entry)
    ]
    passthrough = [
        entry
        for entry in patch_entries
        if isinstance(entry, dict) and not _is_mem_mesh_entry(entry)
    ]
    managed = [
        entry
        for entry in patch_entries
        if isinstance(entry, dict) and _is_mem_mesh_entry(entry)
    ]
    return preserved + passthrough + managed


def _merge_json_settings(path: Path, patch: Dict[str, Any]) -> None:
    """Merge patch into an existing JSON file, preserving other keys."""
    existing: Dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    # Deep-merge hooks section only; preserve everything else.
    # For each hook event, keep existing non mem-mesh entries and upsert only
    # mem-mesh-managed entries from patch.
    for key, value in patch.items():
        if key == "hooks" and key in existing and isinstance(existing[key], dict):
            existing_hooks = existing[key]
            patch_hooks = value if isinstance(value, dict) else {}
            merged_hooks = dict(existing_hooks)
            for event_name, patch_entries in patch_hooks.items():
                current_entries = existing_hooks.get(event_name, [])
                if isinstance(current_entries, list) and isinstance(patch_entries, list):
                    merged_hooks[event_name] = _merge_hook_entries(
                        current_entries, patch_entries
                    )
                else:
                    merged_hooks[event_name] = patch_entries
            existing[key] = merged_hooks
        else:
            existing[key] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _remove_json_key(path: Path, key: str) -> None:
    """Remove a top-level key from a JSON file."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if key in data:
        del data[key]
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def _remove_hook_event(path: Path, event_name: str) -> None:
    """Remove a specific hook event from the hooks section of a JSON file."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    hooks = data.get("hooks", {})
    if event_name in hooks:
        del hooks[event_name]
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _remove_mem_mesh_hooks_from_json(path: Path) -> None:
    """Remove mem-mesh hook entries from hooks.json, preserving user entries."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return

    changed = False
    for event_name, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        filtered = [
            entry
            for entry in entries
            if not (isinstance(entry, dict) and _is_mem_mesh_entry(entry))
        ]
        if len(filtered) != len(entries):
            hooks[event_name] = filtered
            changed = True
        if not hooks[event_name]:
            del hooks[event_name]
            changed = True

    if changed:
        if not hooks:
            data.pop("hooks", None)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _count_mem_mesh_hook_entries(path: Path) -> int:
    """Count mem-mesh hook entries in hooks.json."""
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return 0

    count = 0
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and _is_mem_mesh_entry(entry):
                count += 1
    return count


def _remove_kiro_mem_mesh_hooks(path: Path) -> None:
    """Remove mem-mesh entries from Kiro hooks.json, preserving others."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    hooks: List[Any] = data.get("hooks", [])
    data["hooks"] = [h for h in hooks if not h.get("name", "").startswith("mem-mesh:")]
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Install / Uninstall commands
# ---------------------------------------------------------------------------

HOME = Path.home()

CLAUDE_HOOKS_DIR = HOME / ".claude" / "hooks"
CLAUDE_SETTINGS = HOME / ".claude" / "settings.json"

KIRO_HOOKS_DIR = HOME / ".kiro" / "hooks"
KIRO_SETTINGS = HOME / ".kiro" / "settings" / "hooks.json"

CURSOR_HOOKS_DIR = HOME / ".cursor" / "hooks"
CURSOR_SETTINGS = HOME / ".cursor" / "hooks.json"

def _build_cursor_hooks_settings(
    hooks_dir: Path,
    scope: str = "global",
) -> Dict[str, Any]:
    """Build Cursor hooks settings from a single spec builder."""
    if scope == "project":
        return {
            "version": 1,
            "hooks": {
                "sessionStart": [
                    {
                        "type": "command",
                        "command": str(hooks_dir / "mem-mesh-session-start.sh"),
                        "timeout": 15,
                    }
                ],
                "sessionEnd": [
                    {
                        "type": "command",
                        "command": str(hooks_dir / "mem-mesh-session-end.sh"),
                        "timeout": 10,
                    }
                ],
                "stop": [
                    {
                        "type": "command",
                        "command": str(hooks_dir / "mem-mesh-auto-save.sh"),
                        "timeout": 10,
                    }
                ],
            },
        }

    return {
        "version": 1,
        "hooks": {
            "sessionStart": [
                {
                    "type": "command",
                    "command": str(hooks_dir / "mem-mesh-session-start.sh"),
                    "timeout": 15,
                }
            ],
            "stop": [
                {
                    "type": "command",
                    "command": str(hooks_dir / "mem-mesh-stop.sh"),
                    "timeout": 10,
                }
            ],
        },
    }


def _install_claude(
    url: str, mode: str = "api", path: str = "", profile: str = "standard"
) -> None:
    """Install mem-mesh hooks for Claude Code."""
    profile_info = HOOK_PROFILES[profile]
    print(f"[claude] Installing hook scripts (profile: {profile})...")

    session_start_script = CLAUDE_HOOKS_DIR / "mem-mesh-session-start.sh"
    track_script = CLAUDE_HOOKS_DIR / "mem-mesh-track.sh"
    stop_script = CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh"
    enhanced_stop_script = CLAUDE_HOOKS_DIR / "mem-mesh-stop-enhanced.sh"
    reflect_script = CLAUDE_HOOKS_DIR / "mem-mesh-reflect.sh"

    # SessionStart hook (all profiles)
    if mode == "local":
        _write_script(
            session_start_script,
            _render_local_template(LOCAL_SESSION_START_HOOK_TEMPLATE, path),
        )
    else:
        _write_script(
            session_start_script,
            _render_template(
                SESSION_START_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
            ),
        )
    print(f"  -> {session_start_script}")

    # Remove legacy track script if present
    if track_script.exists():
        track_script.unlink()
        print(f"  removed {track_script} (track hook deprecated)")

    decide_script = CLAUDE_HOOKS_DIR / "mem-mesh-stop-decide.sh"

    # Stop hook
    if "stop-decide" in profile_info["hooks"]:
        # Keyword matching command hook (no LLM, no API key)
        _write_script(
            decide_script,
            _render_template(
                STOP_DECIDE_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
            ),
        )
        print(f"  -> {decide_script}")
    elif "stop-enhanced" in profile_info["hooks"]:
        # Enhanced: async command hook with Haiku API
        if mode == "local":
            _write_script(
                enhanced_stop_script,
                _render_local_template(LOCAL_ENHANCED_STOP_HOOK_TEMPLATE, path),
            )
        else:
            _write_script(
                enhanced_stop_script,
                _render_template(
                    ENHANCED_STOP_HOOK_TEMPLATE,
                    url,
                    source_tag="claude-code-hook",
                    ide_tag="claude",
                ),
            )
        print(f"  -> {enhanced_stop_script}")
    elif "stop" in profile_info["hooks"]:
        # Command-based stop: write shell script (minimal profile)
        if mode == "local":
            _write_script(
                stop_script, _render_local_template(LOCAL_STOP_HOOK_TEMPLATE, path)
            )
        else:
            _write_script(
                stop_script,
                _render_template(
                    STOP_HOOK_TEMPLATE,
                    url,
                    source_tag="claude-code-hook",
                    ide_tag="claude",
                ),
            )
        print(f"  -> {stop_script}")

    # SessionEnd hook (all profiles)
    session_end_script = CLAUDE_HOOKS_DIR / "mem-mesh-session-end.sh"
    if mode == "local":
        _write_script(
            session_end_script,
            _render_local_template(LOCAL_SESSION_END_HOOK_TEMPLATE, path),
        )
    else:
        _write_script(
            session_end_script,
            _render_template(
                SESSION_END_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
            ),
        )
    print(f"  -> {session_end_script}")

    # PreCompact hook (all profiles)
    precompact_script = CLAUDE_HOOKS_DIR / "mem-mesh-precompact.sh"
    if mode == "local":
        _write_script(
            precompact_script,
            _render_local_template(LOCAL_PRECOMPACT_HOOK_TEMPLATE, path),
        )
    else:
        _write_script(
            precompact_script,
            _render_template(
                PRECOMPACT_HOOK_TEMPLATE,
                url,
                source_tag="claude-code-hook",
                ide_tag="claude",
            ),
        )
    print(f"  -> {precompact_script}")

    # Clean up legacy scripts not belonging to current profile
    legacy_cleanup = {
        "standard": [stop_script, enhanced_stop_script, reflect_script],
        "enhanced": [stop_script, decide_script, reflect_script],
        "minimal": [enhanced_stop_script, decide_script, reflect_script],
    }
    for script in legacy_cleanup.get(profile, []):
        if script.exists():
            script.unlink()
            print(f"  removed {script} (not in {profile} profile)")

    print("[claude] Updating settings.json...")
    hooks_settings = _build_claude_hooks_settings(profile)
    _merge_json_settings(CLAUDE_SETTINGS, hooks_settings)
    # Remove legacy PostToolUse (track hook) from settings
    _remove_hook_event(CLAUDE_SETTINGS, "PostToolUse")
    print(f"  -> {CLAUDE_SETTINGS}")

    if profile == "enhanced":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            print("  ANTHROPIC_API_KEY: set")
        else:
            print(
                "  WARNING: ANTHROPIC_API_KEY not set — reflect hook will be inactive"
            )
            print("  Set it in your shell profile: export ANTHROPIC_API_KEY=sk-...")

    print("[claude] Done.")


def _install_kiro(url: str, mode: str = "api", path: str = "") -> None:
    """Install mem-mesh hooks for Kiro."""
    print("[kiro] Installing hook script...")

    stop_script = KIRO_HOOKS_DIR / "mem-mesh-stop.sh"
    if mode == "local":
        _write_script(
            stop_script, _render_local_template(LOCAL_STOP_HOOK_TEMPLATE, path)
        )
    else:
        _write_script(
            stop_script,
            _render_template(
                KIRO_STOP_HOOK_TEMPLATE,
                url,
                source_tag="kiro-hook",
                ide_tag="kiro",
                client_tag="kiro",
            ),
        )
    print(f"  -> {stop_script}")

    print("[kiro] Updating hooks.json...")
    kiro_hook_entry = {
        "name": "mem-mesh: Save Response",
        "trigger": "agentResponse",
        "action": "shell",
        "command": str(stop_script),
        "env": {"KIRO_RESULT": "$response"},
    }

    # Load existing or create new
    existing: Dict[str, Any] = {"hooks": []}
    if KIRO_SETTINGS.exists():
        try:
            existing = json.loads(KIRO_SETTINGS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {"hooks": []}

    hooks: List[Any] = existing.get("hooks", [])

    # Remove existing mem-mesh hooks, then add new
    hooks = [h for h in hooks if not h.get("name", "").startswith("mem-mesh:")]
    hooks.append(kiro_hook_entry)
    existing["hooks"] = hooks

    KIRO_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    KIRO_SETTINGS.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"  -> {KIRO_SETTINGS}")

    print("[kiro] Done.")


def _install_cursor(
    url: str, mode: str = "api", path: str = "", profile: str = "standard"
) -> None:
    """Install mem-mesh hooks for Cursor."""
    print(f"[cursor] Installing hook scripts (profile: {profile})...")

    session_start_script = CURSOR_HOOKS_DIR / "mem-mesh-session-start.sh"
    track_script = CURSOR_HOOKS_DIR / "mem-mesh-track.sh"
    stop_script = CURSOR_HOOKS_DIR / "mem-mesh-stop.sh"

    session_end_script = CURSOR_HOOKS_DIR / "mem-mesh-session-end.sh"

    if mode == "local":
        _write_script(
            session_start_script,
            _render_local_template(LOCAL_SESSION_START_HOOK_TEMPLATE, path),
        )
        _write_script(
            stop_script, _render_local_template(LOCAL_STOP_HOOK_TEMPLATE, path)
        )
        _write_script(
            session_end_script,
            _render_local_template(LOCAL_SESSION_END_HOOK_TEMPLATE, path),
        )
    else:
        _write_script(
            session_start_script,
            _render_template(
                CURSOR_SESSION_START_TEMPLATE,
                url,
                source_tag="cursor-hook",
                ide_tag="cursor",
            ),
        )
        _write_script(
            stop_script,
            _render_template(
                CURSOR_STOP_TEMPLATE,
                url,
                source_tag="cursor-hook",
                ide_tag="cursor",
            ),
        )
        _write_script(
            session_end_script,
            _render_template(
                SESSION_END_HOOK_TEMPLATE,
                url,
                source_tag="cursor-hook",
                ide_tag="cursor",
            ),
        )
    print(f"  -> {session_start_script}")
    print(f"  -> {stop_script}")
    print(f"  -> {session_end_script}")

    # Remove legacy track script if present
    if track_script.exists():
        track_script.unlink()
        print(f"  removed {track_script} (track hook deprecated)")

    print("[cursor] Updating hooks.json...")
    _merge_json_settings(
        CURSOR_SETTINGS, _build_cursor_hooks_settings(CURSOR_HOOKS_DIR, scope="global")
    )
    # Remove legacy postToolUse (track hook) from hooks.json
    _remove_hook_event(CURSOR_SETTINGS, "postToolUse")
    print(f"  -> {CURSOR_SETTINGS}")

    print("[cursor] Done.")


def _uninstall_claude() -> None:
    """Remove mem-mesh hooks for Claude Code."""
    print("[claude] Removing hook scripts...")
    for name in (
        "mem-mesh-session-start.sh",
        "mem-mesh-track.sh",
        "mem-mesh-stop.sh",
        "mem-mesh-stop-decide.sh",
        "mem-mesh-stop-enhanced.sh",
        "mem-mesh-reflect.sh",
        "mem-mesh-session-end.sh",
        "mem-mesh-precompact.sh",
    ):
        script = CLAUDE_HOOKS_DIR / name
        if script.exists():
            script.unlink()
            print(f"  removed {script}")

    print("[claude] Removing hooks from settings.json...")
    _remove_json_key(CLAUDE_SETTINGS, "hooks")

    print("[claude] Done.")


def _uninstall_kiro() -> None:
    """Remove mem-mesh hooks for Kiro."""
    print("[kiro] Removing hook scripts...")
    script = KIRO_HOOKS_DIR / "mem-mesh-stop.sh"
    if script.exists():
        script.unlink()
        print(f"  removed {script}")

    print("[kiro] Removing mem-mesh hooks from hooks.json...")
    _remove_kiro_mem_mesh_hooks(KIRO_SETTINGS)

    print("[kiro] Done.")


def _uninstall_cursor() -> None:
    """Remove mem-mesh hooks for Cursor."""
    print("[cursor] Removing hook scripts...")
    for name in (
        "mem-mesh-session-start.sh",
        "mem-mesh-track.sh",
        "mem-mesh-stop.sh",
        "mem-mesh-session-end.sh",
    ):
        script = CURSOR_HOOKS_DIR / name
        if script.exists():
            script.unlink()
            print(f"  removed {script}")

    print("[cursor] Removing hooks from hooks.json...")
    _remove_json_key(CURSOR_SETTINGS, "hooks")

    print("[cursor] Done.")


# ---------------------------------------------------------------------------
# Status command (with version detection)
# ---------------------------------------------------------------------------


def _check_script(path: Path) -> str:
    """Check if a script exists and is executable."""
    if not path.exists():
        return "not installed"
    if not os.access(path, os.X_OK):
        return "exists but NOT executable"
    return "installed"


def _check_script_version(path: Path) -> str:
    """Check script status including prompt version."""
    base = _check_script(path)
    if base != "installed":
        return base
    content = path.read_text(encoding="utf-8")
    version = extract_prompt_version(content)
    if version == 0:
        return "installed (no version marker)"
    if version < PROMPT_VERSION:
        return f"installed (prompt-version: {version} -> outdated)"
    return f"installed (prompt-version: {version})"


def _extract_url_from_script(path: Path) -> Optional[str]:
    """Extract the default URL from an installed script."""
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    for line in content.splitlines():
        if "MEM_MESH_API_URL:-" in line:
            start = line.find(":-") + 2
            end = line.find("}", start)
            if start > 1 and end > start:
                url = line[start:end].strip('"').strip("'")
                return url
    return None


def _check_kiro_hook_version(path: Path) -> str:
    """Check prompt version in a .kiro.hook JSON file."""
    if not path.exists():
        return "not found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "parse error"
    version_str = data.get("version", "0")
    try:
        version = int(version_str)
    except ValueError:
        return f"installed (version: {version_str})"
    if version < PROMPT_VERSION:
        return f"installed (prompt-version: {version} -> outdated)"
    return f"installed (prompt-version: {version})"


def _has_prompt_stop_hook(settings_path: Path) -> bool:
    """Check if settings.json has a prompt-based Stop hook configured."""
    if not settings_path.exists():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        stop_entries = data.get("hooks", {}).get("Stop", [])
        for entry in stop_entries:
            for hook in entry.get("hooks", []):
                if hook.get("type") == "prompt":
                    return True
    except (json.JSONDecodeError, OSError, TypeError):
        pass
    return False


def _detect_profile(hooks_dir: Path, settings_path: Optional[Path] = None) -> str:
    """Detect installed profile based on hook scripts and settings.

    Detection priority:
    1. mem-mesh-stop-enhanced.sh → "enhanced"
    2. mem-mesh-stop-decide.sh → "standard"
    3. settings.json has prompt stop hook → "standard (prompt)"
    4. mem-mesh-stop.sh → "minimal"
    5. mem-mesh-reflect.sh → "legacy"
    """
    has_session_start = (hooks_dir / "mem-mesh-session-start.sh").exists()
    has_enhanced_stop = (hooks_dir / "mem-mesh-stop-enhanced.sh").exists()
    has_stop_decide = (hooks_dir / "mem-mesh-stop-decide.sh").exists()
    has_reflect = (hooks_dir / "mem-mesh-reflect.sh").exists()
    has_stop = (hooks_dir / "mem-mesh-stop.sh").exists()
    has_prompt_stop = (
        _has_prompt_stop_hook(settings_path) if settings_path else False
    )

    if has_enhanced_stop:
        return "enhanced"
    if has_stop_decide:
        return "standard"
    if has_prompt_stop:
        return "standard (prompt)"
    if has_stop:
        return "minimal"
    if has_reflect:
        return "legacy"
    if has_session_start:
        return "standard (partial)"
    return "unknown"


def cmd_status() -> None:
    """Print installation status."""
    print("=== mem-mesh hooks status ===")
    print(f"Prompt version: {PROMPT_VERSION} (current)\n")

    # Claude Code
    print("[Claude Code]")
    session_start = CLAUDE_HOOKS_DIR / "mem-mesh-session-start.sh"
    stop = CLAUDE_HOOKS_DIR / "mem-mesh-stop.sh"
    stop_decide = CLAUDE_HOOKS_DIR / "mem-mesh-stop-decide.sh"
    enhanced_stop = CLAUDE_HOOKS_DIR / "mem-mesh-stop-enhanced.sh"
    reflect = CLAUDE_HOOKS_DIR / "mem-mesh-reflect.sh"
    session_end = CLAUDE_HOOKS_DIR / "mem-mesh-session-end.sh"
    precompact = CLAUDE_HOOKS_DIR / "mem-mesh-precompact.sh"
    print(f"  session hook:   {_check_script_version(session_start)}")
    if enhanced_stop.exists():
        print(f"  stop hook:      {_check_script_version(enhanced_stop)} (enhanced)")
    elif stop_decide.exists():
        print(f"  stop hook:      {_check_script_version(stop_decide)} (standard)")
    elif _has_prompt_stop_hook(CLAUDE_SETTINGS):
        print(f"  stop hook:      native prompt (v{PROMPT_VERSION})")
    else:
        print(f"  stop hook:      {_check_script_version(stop)}")
    print(f"  session-end:    {_check_script_version(session_end)}")
    print(f"  precompact:     {_check_script_version(precompact)}")
    print(f"  reflect hook:   {_check_script_version(reflect)} (legacy)")

    detected = _detect_profile(CLAUDE_HOOKS_DIR, CLAUDE_SETTINGS)
    print(f"  profile:      {detected}")

    url = (
        _extract_url_from_script(session_start)
        or _extract_url_from_script(stop)
    )
    if url:
        print(f"  target URL:   {url}")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    print(f"  ANTHROPIC_API_KEY: {'set' if api_key else 'not set'}")

    if CLAUDE_SETTINGS.exists():
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
            has_hooks = "hooks" in settings
            print(
                f"  settings.json hooks: {'configured' if has_hooks else 'not configured'}"
            )
        except (json.JSONDecodeError, OSError):
            print("  settings.json: parse error")
    else:
        print("  settings.json: not found")

    print()

    # Kiro
    print("[Kiro]")
    kiro_stop = KIRO_HOOKS_DIR / "mem-mesh-stop.sh"
    print(f"  stop hook:   {_check_script_version(kiro_stop)}")

    url = _extract_url_from_script(kiro_stop)
    if url:
        print(f"  target URL:  {url}")

    if KIRO_SETTINGS.exists():
        try:
            data = json.loads(KIRO_SETTINGS.read_text(encoding="utf-8"))
            mem_hooks = [
                h
                for h in data.get("hooks", [])
                if h.get("name", "").startswith("mem-mesh:")
            ]
            print(f"  hooks.json:  {len(mem_hooks)} mem-mesh hook(s) registered")
        except (json.JSONDecodeError, OSError):
            print("  hooks.json: parse error")
    else:
        print("  hooks.json: not found")

    print()

    # Cursor
    print("[Cursor]")
    cursor_session = CURSOR_HOOKS_DIR / "mem-mesh-session-start.sh"
    cursor_stop = CURSOR_HOOKS_DIR / "mem-mesh-stop.sh"
    cursor_session_end = CURSOR_HOOKS_DIR / "mem-mesh-session-end.sh"
    print(f"  session hook: {_check_script_version(cursor_session)}")
    print(f"  stop hook:    {_check_script_version(cursor_stop)}")
    print(f"  session-end:  {_check_script_version(cursor_session_end)}")

    url = _extract_url_from_script(cursor_session) or _extract_url_from_script(
        cursor_stop
    )
    if url:
        print(f"  target URL:   {url}")

    if CURSOR_SETTINGS.exists():
        try:
            settings = json.loads(CURSOR_SETTINGS.read_text(encoding="utf-8"))
            has_hooks = "hooks" in settings
            print(f"  hooks.json:   {'configured' if has_hooks else 'not configured'}")
        except (json.JSONDecodeError, OSError):
            print("  hooks.json:   parse error")
    else:
        print("  hooks.json:   not found")

    # Project-local hooks
    project_root = _find_project_root()
    if project_root:
        print()
        print("[Project Local]")

        # Kiro hooks
        kiro_dir = project_root / ".kiro" / "hooks"
        for name in (
            "auto-save-conversations",
            "auto-create-pin-on-task",
            "load-project-context",
        ):
            hook_file = kiro_dir / f"{name}.kiro.hook"
            print(f"  {name}: {_check_kiro_hook_version(hook_file)}")

        # Cursor hooks
        cursor_dir = project_root / ".cursor" / "hooks"
        for name in (
            "mem-mesh-session-start.sh",
            "mem-mesh-session-end.sh",
            "mem-mesh-auto-save.sh",
        ):
            script = cursor_dir / name
            print(f"  {name}: {_check_script_version(script)}")
        cursor_settings = project_root / ".cursor" / "hooks.json"
        cursor_template = project_root / ".cursor" / "hooks.mem-mesh.example.json"
        if cursor_settings.exists():
            count = _count_mem_mesh_hook_entries(cursor_settings)
            print(f"  hooks.json: configured (mem-mesh entries: {count})")
        else:
            print("  hooks.json: not found")
        if cursor_template.exists():
            print("  hooks.mem-mesh.example.json: available")
        else:
            print("  hooks.mem-mesh.example.json: not found")

    print()
    print("Run 'mem-mesh-hooks install --target all' to update global hooks.")
    print("Run 'mem-mesh-hooks sync-project' to update project-local hooks.")


# ---------------------------------------------------------------------------
# Sync-project command
# ---------------------------------------------------------------------------


def _find_project_root() -> Optional[Path]:
    """Find the mem-mesh project root (where CLAUDE.md exists)."""
    # First try: relative to this file
    candidate = Path(__file__).resolve().parent.parent.parent
    if (candidate / "CLAUDE.md").exists() or (candidate / "pyproject.toml").exists():
        return candidate
    # Second try: CWD
    cwd = Path.cwd()
    if (cwd / "CLAUDE.md").exists() or (cwd / "pyproject.toml").exists():
        return cwd
    return None


def cmd_sync_project(target: str = "all", project_id: str = "mem-mesh") -> None:
    """Regenerate project-local hooks from shared prompt definitions."""
    project_root = _find_project_root()
    if not project_root:
        print("Error: Could not find project root. Run from the mem-mesh directory.")
        sys.exit(1)

    print(f"=== sync-project (prompt-version: {PROMPT_VERSION}) ===")
    print(f"Project root: {project_root}\n")

    if target in ("kiro", "all"):
        _sync_kiro_hooks(project_root, project_id)

    if target in ("cursor", "all"):
        _sync_cursor_hooks(project_root, project_id)

    print("\nSync complete.")


def _sync_kiro_hooks(project_root: Path, project_id: str) -> None:
    """Regenerate behavioral .kiro.hook files from shared prompts."""
    kiro_dir = project_root / ".kiro" / "hooks"
    kiro_dir.mkdir(parents=True, exist_ok=True)

    hooks = {
        "auto-save-conversations": render_kiro_auto_save(project_id),
        "auto-create-pin-on-task": render_kiro_auto_create_pin(project_id),
        "load-project-context": render_kiro_load_context(project_id),
    }

    print("[kiro] Regenerating behavioral hooks...")
    for name, hook_data in hooks.items():
        hook_file = kiro_dir / f"{name}.kiro.hook"
        hook_file.write_text(
            json.dumps(hook_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"  -> {hook_file}")

    print("[kiro] Done. (manual-* hooks untouched)")


def _sync_cursor_hooks(project_root: Path, project_id: str) -> None:
    """Regenerate project-local Cursor hooks from shared prompts."""
    cursor_dir = project_root / ".cursor" / "hooks"
    cursor_dir.mkdir(parents=True, exist_ok=True)

    # session-start: uses Python direct import (project-local)
    session_start_content = f"""#!/bin/bash
{VERSION_MARKER}
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
        result = await pin_svc.session_resume('{project_id}', expand='smart')
        return json.dumps(result, ensure_ascii=False, default=str)

    print(asyncio.run(get_resume()))
except Exception as e:
    print(json.dumps({{'error': str(e)}}))
" 2>/dev/null) || RESUME_OUTPUT='{{"error": "mem-mesh not available"}}'

RULES_TEXT="{render_rules_text(project_id)}"

CONTEXT="## mem-mesh Memory Integration (Auto-loaded)

### 세션 복원 결과
\\`\\`\\`json
${{RESUME_OUTPUT}}
\\`\\`\\`

### 작업 규칙
$RULES_TEXT"

python3 -c "
import json, sys
ctx = sys.stdin.read()
print(json.dumps({{'additional_context': ctx}}))
" <<< "$CONTEXT"
"""

    # auto-save (stop event)
    followup_msg = render_cursor_followup(project_id)
    auto_save_content = f"""#!/bin/bash
{VERSION_MARKER}
# mem-mesh Auto-Save Hook for Cursor (stop event, project-local)

set -euo pipefail

INPUT=$(cat)

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
print(json.dumps({{'followup_message': '''{followup_msg}'''}}))
"
else
    echo '{{}}'
fi
"""

    # session-end
    session_end_content = f"""#!/bin/bash
{VERSION_MARKER}
# mem-mesh Session End Hook for Cursor (project-local)

set -euo pipefail

INPUT=$(cat)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

python3 -c "
import sys, json
sys.path.insert(0, '$PROJECT_ROOT')
try:
    from app.core.services.pin_service import PinService
    from app.core.storage.direct import DirectStorageManager
    import asyncio

    async def end_session():
        storage = DirectStorageManager()
        await storage.initialize()
        pin_svc = PinService(storage)
        result = await pin_svc.session_end('{project_id}')
        return result

    asyncio.run(end_session())
except Exception:
    pass
" 2>/dev/null || true
"""

    print("[cursor] Regenerating project-local hooks...")
    scripts = {
        "mem-mesh-session-start.sh": session_start_content,
        "mem-mesh-auto-save.sh": auto_save_content,
        "mem-mesh-session-end.sh": session_end_content,
    }
    for name, content in scripts.items():
        _write_script(cursor_dir / name, content)
        print(f"  -> {cursor_dir / name}")

    template_path = project_root / ".cursor" / "hooks.mem-mesh.example.json"
    template_data = _build_cursor_hooks_settings(cursor_dir, scope="project")
    template_path.write_text(
        json.dumps(template_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"  -> {template_path}")

    settings_path = project_root / ".cursor" / "hooks.json"
    _remove_mem_mesh_hooks_from_json(settings_path)
    if settings_path.exists():
        print(f"  -> cleaned mem-mesh entries from {settings_path}")

    print("[cursor] Done.")


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


def cmd_install(
    target: str,
    url: str,
    mode: str = "api",
    path: str = "",
    profile: str = "standard",
) -> None:
    """Install hooks for the specified target."""
    if mode == "local":
        resolved = path or str(Path(__file__).resolve().parent.parent.parent)
        print(f"Installing mem-mesh hooks (mode: local, path: {resolved})")
    else:
        resolved = ""
        print(f"Installing mem-mesh hooks (mode: api, url: {url})")

    print(f"Prompt version: {PROMPT_VERSION} | Profile: {profile}\n")

    if target in ("claude", "all"):
        _install_claude(url, mode, resolved, profile)
        print()
    if target in ("kiro", "all"):
        _install_kiro(url, mode, resolved)
        print()
    if target in ("cursor", "all"):
        _install_cursor(url, mode, resolved, profile)
        print()
    print("Installation complete. Run 'mem-mesh-hooks status' to verify.")


def cmd_uninstall(target: str) -> None:
    """Uninstall hooks for the specified target."""
    print("Uninstalling mem-mesh hooks\n")
    if target in ("claude", "all"):
        _uninstall_claude()
        print()
    if target in ("kiro", "all"):
        _uninstall_kiro()
        print()
    if target in ("cursor", "all"):
        _uninstall_cursor()
        print()
    print("Uninstallation complete.")


# ---------------------------------------------------------------------------
# Interactive installer
# ---------------------------------------------------------------------------


def _prompt_choice(prompt: str, options: List[str], default: int = 0) -> int:
    """Show numbered options and return the selected index."""
    for i, opt in enumerate(options, 1):
        marker = " (default)" if i - 1 == default else ""
        print(f"  {i}) {opt}{marker}")
    while True:
        raw = input(f"  Select [{default + 1}]: ").strip()
        if not raw:
            return default
        try:
            choice = int(raw)
            if 1 <= choice <= len(options):
                return choice - 1
        except ValueError:
            pass
        print(f"  Please enter 1-{len(options)}")
    raise RuntimeError("unreachable")


def cmd_interactive() -> None:
    """Interactive hook installation wizard."""
    print("=" * 44)
    print("  mem-mesh hooks installer (interactive)")
    print("=" * 44)
    print()

    # Step 1: target
    print("[1/4] Select target IDE:")
    targets = ["Claude Code", "Kiro", "Cursor", "All"]
    target_keys = ["claude", "kiro", "cursor", "all"]
    idx = _prompt_choice("", targets, default=3)
    target = target_keys[idx]
    print()

    # Step 2: hook profile
    print("[2/4] Select hook profile:")
    profile_options = [
        f"Standard — {HOOK_PROFILES['standard']['description']}",
        f"Enhanced — {HOOK_PROFILES['enhanced']['description']}",
        f"Minimal  — {HOOK_PROFILES['minimal']['description']}",
    ]
    profile_keys = ["standard", "enhanced", "minimal"]
    profile_idx = _prompt_choice("", profile_options, default=0)
    profile = profile_keys[profile_idx]
    print()

    if profile == "enhanced":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("  NOTE: Enhanced profile requires ANTHROPIC_API_KEY.")
            print("  The reflect hook will be inactive until the key is set.")
            print("  Set it with: export ANTHROPIC_API_KEY=sk-ant-...")
            print()

    # Step 3: storage mode
    print("[3/4] Select storage mode:")
    modes = [
        f"API  — Send to remote server ({DEFAULT_URL})",
        "Local — Save directly to local SQLite",
    ]
    mode_idx = _prompt_choice("", modes, default=0)
    mode = "api" if mode_idx == 0 else "local"
    print()

    # Step 4: mode-specific config
    url = DEFAULT_URL
    mem_path = ""
    if mode == "api":
        print(f"[4/4] API URL [{DEFAULT_URL}]:")
        raw = input("  > ").strip()
        if raw:
            url = raw
    else:
        default_path = str(Path(__file__).resolve().parent.parent.parent)
        print(f"[4/4] mem-mesh project path [{default_path}]:")
        raw = input("  > ").strip()
        mem_path = raw if raw else default_path
    print()

    cmd_install(target, url, mode, mem_path, profile)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point for mem-mesh-hooks."""
    parser = argparse.ArgumentParser(
        prog="mem-mesh-hooks",
        description="Install/uninstall mem-mesh hooks for Claude Code, Kiro, and Cursor.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    target_choices = ["claude", "kiro", "cursor", "all"]

    # install
    install_parser = subparsers.add_parser("install", help="Install hooks")
    install_parser.add_argument(
        "--target",
        choices=target_choices,
        default="all",
        help="Target tool (default: all)",
    )
    install_parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"mem-mesh API URL (default: {DEFAULT_URL})",
    )
    install_parser.add_argument(
        "--mode",
        choices=["api", "local"],
        default="api",
        help="Storage mode: api (remote server) or local (SQLite direct)",
    )
    install_parser.add_argument(
        "--path",
        default="",
        help="mem-mesh project path (required for local mode)",
    )
    install_parser.add_argument(
        "--profile",
        choices=["standard", "enhanced", "minimal"],
        default="standard",
        help="Hook profile: standard (prompt hook, hybrid save), enhanced (+reflect), minimal (command, no LLM)",
    )
    install_parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Run interactive installer wizard",
    )

    # uninstall
    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall hooks")
    uninstall_parser.add_argument(
        "--target",
        choices=target_choices,
        default="all",
        help="Target tool (default: all)",
    )

    # status
    subparsers.add_parser("status", help="Show installation status")

    # sync-project
    sync_parser = subparsers.add_parser(
        "sync-project",
        help="Regenerate project-local hooks from shared prompts",
    )
    sync_parser.add_argument(
        "--target",
        choices=["kiro", "cursor", "all"],
        default="all",
        help="Target to sync (default: all)",
    )
    sync_parser.add_argument(
        "--project-id",
        default="mem-mesh",
        help="Project ID for hook prompts (default: mem-mesh)",
    )

    args = parser.parse_args(argv)

    # No subcommand or install -i → interactive mode
    if args.command is None or (
        args.command == "install" and getattr(args, "interactive", False)
    ):
        cmd_interactive()
        return

    if args.command == "install":
        cmd_install(args.target, args.url, args.mode, args.path, args.profile)
    elif args.command == "uninstall":
        cmd_uninstall(args.target)
    elif args.command == "status":
        cmd_status()
    elif args.command == "sync-project":
        cmd_sync_project(args.target, args.project_id)


if __name__ == "__main__":
    main()
