#!/bin/bash
# mem-mesh-hooks prompt-version: 2
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
        result = await pin_svc.session_end('mem-mesh')
        return result

    asyncio.run(end_session())
except Exception:
    pass
" 2>/dev/null || true
