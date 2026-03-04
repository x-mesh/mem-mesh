"""
Dashboard 전용 서버 진입점.

python -m app.web.dashboard 로 실행
- 웹 UI와 REST API만 제공
- MCP SSE 엔드포인트 제외
"""

import argparse

import uvicorn

from app.web.common.server import create_uvicorn_config, init_server


def main():
    """Dashboard 서버 메인 함수"""
    settings = init_server()

    parser = argparse.ArgumentParser(description="mem-mesh Dashboard Server")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--host", type=str, help="Host address")
    parser.add_argument("--port", type=int, help="Port number (default: 8000)")
    parser.add_argument("--workers", type=int, help="Number of worker processes")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  mem-mesh Dashboard Server (Dashboard Only)")
    print("=" * 60)
    print("  Mode:          Dashboard Only (no MCP)")
    print(f"  Port:          {args.port or settings.server_port}")
    print("=" * 60 + "\n")

    config = create_uvicorn_config(
        app_path="app.web.dashboard.app:app",
        settings=settings,
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
        access_log_prefix="dashboard-",
    )

    uvicorn.run(**config)


if __name__ == "__main__":
    main()
