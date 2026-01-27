"""MCP Stdio Pure 서버 진입점"""

import asyncio
from .server import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Graceful shutdown on Ctrl+C - no additional cleanup needed
        pass
