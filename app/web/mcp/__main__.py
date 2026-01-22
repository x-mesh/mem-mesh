"""
MCP SSE 전용 서버 진입점.

python -m app.web.mcp 로 실행
- MCP SSE 엔드포인트만 제공
- 웹 UI 제외, API Key 인증 지원
"""

import argparse
import uvicorn

from app.core.config import Settings
from app.web.common.server import init_server, create_uvicorn_config


def main():
    """MCP 서버 메인 함수"""
    settings = init_server()
    
    parser = argparse.ArgumentParser(description="mem-mesh MCP SSE Server")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8001, help="Port number (default: 8001)")
    parser.add_argument("--workers", type=int, help="Number of worker processes")
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("  mem-mesh MCP SSE Server (MCP Only)")
    print("="*60)
    print(f"  Mode:          MCP SSE Only (no Dashboard)")
    print(f"  Host:          {args.host}")
    print(f"  Port:          {args.port}")
    print(f"  Endpoints:     /mcp/sse, /mcp/info, /mcp/tools/call")
    print("="*60 + "\n")
    
    config = create_uvicorn_config(
        app_path="app.web.mcp.app:app",
        settings=settings,
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
        access_log_prefix="mcp-"
    )
    
    uvicorn.run(**config)


if __name__ == "__main__":
    main()
