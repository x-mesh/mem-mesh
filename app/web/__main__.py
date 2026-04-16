"""
통합 Web 서버 진입점.

python -m app.web 로 실행
- Dashboard + MCP SSE 모두 제공 (기본)

분리 실행:
- python -m app.web.dashboard  # Dashboard만
- python -m app.web.mcp        # MCP만
"""

import argparse

import uvicorn

from app.web.common.server import create_uvicorn_config, init_server


def main():
    """통합 Web 서버 메인 함수"""
    settings = init_server()

    parser = argparse.ArgumentParser(
        description="mem-mesh Web Server (Dashboard + MCP)"
    )
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--host", type=str, help="Host address")
    parser.add_argument("--port", type=int, help="Port number")
    parser.add_argument("--workers", type=int, help="Number of worker processes")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  mem-mesh Web Server (Unified)")
    print("=" * 60)
    print("  Mode:          Dashboard + MCP SSE")
    print(f"  Port:          {args.port or settings.server_port}")
    print("  Dashboard:     /")
    print("  MCP SSE:       /mcp/sse")
    print("=" * 60)
    print("  Tip: For separated mode, use:")
    print("    python -m app.web.dashboard  # Dashboard only")
    print("    python -m app.web.mcp        # MCP only")
    print("=" * 60)
    print("  Loading server modules (first-time boot may take ~30s — imports torch,")
    print("  embedding model, FastAPI. Subsequent starts are fast.)")
    print("=" * 60 + "\n", flush=True)

    config = create_uvicorn_config(
        app_path="app.web.app:app",
        settings=settings,
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
        access_log_prefix="",
    )

    uvicorn.run(**config)


if __name__ == "__main__":
    main()
