"""MCP Stdio 서버 진입점"""
import asyncio
import logging
import sys

from ..core.config import Settings
from .server import mcp, initialize_storage, shutdown_storage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr  # MCP는 stdout을 사용하므로 로그는 stderr로
)

logger = logging.getLogger(__name__)


async def main():
    """MCP 서버 메인 함수"""
    try:
        settings = Settings()
        
        logger.info(f"Starting MCP server in {settings.storage_mode} mode")
        
        # 스토리지 초기화
        await initialize_storage(settings)
        
        # FastMCP 서버 실행
        await mcp.run_stdio_async()
        
    except Exception as e:
        logger.error(f"Failed to start MCP server: {e}")
        raise
    finally:
        # 정리
        await shutdown_storage()


if __name__ == "__main__":
    asyncio.run(main())
