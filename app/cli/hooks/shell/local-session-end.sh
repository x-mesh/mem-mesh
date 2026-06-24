#!/bin/bash
__VERSION_MARKER__
# Claude Code SessionEnd hook: auto-end mem-mesh session (local mode)
# Writes directly to local SQLite via Python
# Non-blocking: exits 0 on failure

set -euo pipefail
__PROJECT_ID_RESOLVER__
command -v python3 >/dev/null 2>&1 || exit 0

MEM_MESH_PATH=__MEM_MESH_PATH__

# Resolve the stable project id.
PROJECT_DIR="$(mem_mesh_project_id)"
[ -z "$PROJECT_DIR" ] && exit 0

python3 - "$MEM_MESH_PATH" "$PROJECT_DIR" <<'PY' 2>/dev/null || true
import sys, asyncio, json
mem_mesh_path, project_dir = sys.argv[1:3]
sys.path.insert(0, mem_mesh_path)
try:
    from app.core.services.session import SessionService
    from app.core.database.base import Database

    async def end_session():
        db = Database()
        await db.initialize()
        svc = SessionService(db)
        await svc.end_session_by_project(project_dir)

    asyncio.run(end_session())
except Exception:
    pass
PY

exit 0
