#!/bin/bash
__VERSION_MARKER__
# Claude Code PreCompact hook: auto-end mem-mesh session before context compaction
# Ensures session data is preserved before the context window is compressed
# Non-blocking: exits 0 on failure

set -euo pipefail
command -v curl >/dev/null 2>&1 || exit 0

API_URL="${MEM_MESH_API_URL:-__DEFAULT_URL__}"

# Detect project from CWD
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && exit 0

# End session with auto-compact summary
curl -s -o /dev/null --max-time 5 \
  -X POST "${API_URL}/api/work/sessions/end-by-project/${PROJECT_DIR}?summary=Auto-ended%20by%20PreCompact%20hook" \
  2>/dev/null || true

exit 0
