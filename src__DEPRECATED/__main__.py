"""
MCP 서버 진입점
stdio 기반 MCP 서버 또는 FastAPI 서버 실행
"""

import asyncio
import sys
import logging
import argparse
from .mcp.server import main as mcp_main

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr  # MCP는 stdout을 사용하므로 로그는 stderr로
)


def parse_args():
    """Command line arguments 파싱"""
    parser = argparse.ArgumentParser(
        description="mem-mesh server - MCP 또는 FastAPI 모드로 실행"
    )
    
    parser.add_argument(
        "--mode",
        choices=["mcp", "fastapi"],
        default="mcp",
        help="서버 실행 모드 (기본값: mcp)"
    )
    
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="FastAPI 서버 호스트 (기본값: 127.0.0.1)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="FastAPI 서버 포트 (기본값: 8000)"
    )
    
    parser.add_argument(
        "--reload",
        action="store_true",
        help="FastAPI 개발 모드 (auto-reload)"
    )
    
    return parser.parse_args()


async def run_fastapi_server(host: str, port: int, reload: bool = False):
    """FastAPI 서버 실행"""
    try:
        import uvicorn
        from .main import app
        
        print(f"Starting FastAPI server on {host}:{port}", file=sys.stderr)
        
        if reload:
            # 개발 모드
            uvicorn.run(
                "src.main:app",
                host=host,
                port=port,
                reload=True,
                log_level="info"
            )
        else:
            # 프로덕션 모드
            config = uvicorn.Config(
                app=app,
                host=host,
                port=port,
                log_level="info"
            )
            server = uvicorn.Server(config)
            await server.serve()
            
    except ImportError:
        print("Error: uvicorn이 설치되지 않았습니다. pip install uvicorn으로 설치하세요.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"FastAPI server error: {e}", file=sys.stderr)
        sys.exit(1)


async def main():
    """메인 진입점"""
    args = parse_args()
    
    if args.mode == "fastapi":
        await run_fastapi_server(args.host, args.port, args.reload)
    else:
        # MCP 모드 (기본값)
        await mcp_main()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Server stopped", file=sys.stderr)
    except Exception as e:
        print(f"Server error: {e}", file=sys.stderr)
        sys.exit(1)