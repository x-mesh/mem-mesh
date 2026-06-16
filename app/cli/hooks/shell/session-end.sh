#!/bin/bash
__VERSION_MARKER__
# Claude Code SessionEnd hook: auto-end mem-mesh session via API
# Fires when the user closes the session or exits Claude Code
# Non-blocking: exits 0 on failure to avoid disrupting the IDE

set -euo pipefail
command -v curl >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-$(cat ~/.mem-mesh/api_url 2>/dev/null || echo __DEFAULT_URL__)}"
HOOK_TOKEN="${MEM_MESH_HOOK_TOKEN:-$(cat ~/.mem-mesh/hook_token 2>/dev/null || true)}"
AUTH=()
if [ -n "$HOOK_TOKEN" ]; then AUTH+=(-H "Authorization: Bearer ${HOOK_TOKEN}"); fi

# Detect project from CWD
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && exit 0

# End the most recent active session for this project
curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/work/sessions/end-by-project/${PROJECT_DIR}" \
  ${AUTH[@]+"${AUTH[@]}"} \
  2>/dev/null || true

exit 0
