"""MCP Stdio 서버 진입점"""

import asyncio
import logging
import sys

from ..core.config import Settings
from .server import initialize_storage, mcp, shutdown_storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,  # MCP uses stdout, so send logs to stderr
)

logger = logging.getLogger(__name__)


async def main():
    """MCP 서버 메인 함수"""
    try:
        settings = Settings()

        logger.info(f"Starting MCP server in {settings.storage_mode} mode")

        # Initialize storage
        await initialize_storage(settings)

        # Run FastMCP server
        await mcp.run_stdio_async()

    except Exception as e:
        logger.error(f"Failed to start MCP server: {e}")
        raise
    finally:
        # Cleanup
        await shutdown_storage()


if __name__ == "__main__":
    asyncio.run(main())
