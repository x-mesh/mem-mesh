#!/bin/bash
__VERSION_MARKER__
# Claude Code PreCompact hook: auto-end mem-mesh session (local mode)
# Writes directly to local SQLite via Python
# Non-blocking: exits 0 on failure

set -euo pipefail
command -v python3 >/dev/null 2>&1 || exit 0

MEM_MESH_PATH="__MEM_MESH_PATH__"

# Detect project from CWD
PROJECT_DIR=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
[ -z "$PROJECT_DIR" ] && exit 0

python3 -c "
import sys, asyncio, json
sys.path.insert(0, '$MEM_MESH_PATH')
try:
    from app.core.services.session import SessionService
    from app.core.database.base import Database

    async def end_session():
        db = Database()
        await db.initialize()
        svc = SessionService(db)
        await svc.end_session_by_project('$PROJECT_DIR', summary='Auto-ended by PreCompact hook')

    asyncio.run(end_session())
except Exception:
    pass
" 2>/dev/null || true

exit 0
