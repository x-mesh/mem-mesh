#!/bin/bash
__VERSION_MARKER__
# Claude Code SessionEnd hook: auto-end mem-mesh session via API
# Fires when the user closes the session or exits Claude Code
# Non-blocking: exits 0 on failure to avoid disrupting the IDE

set -euo pipefail
command -v curl >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

# Detect project from CWD
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && exit 0

# End the most recent active session for this project
curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/work/sessions/end-by-project/${PROJECT_DIR}" \
  2>/dev/null || true

exit 0
