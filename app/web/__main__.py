"""FastAPI Web 서버 진입점"""
import argparse
import uvicorn
from app.core.config import Settings


def main():
    """Web 서버 메인 함수"""
    parser = argparse.ArgumentParser(description="mem-mesh Web Server")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--host", type=str, help="Host address")
    parser.add_argument("--port", type=int, help="Port number")
    args = parser.parse_args()
    
    settings = Settings()
    
    uvicorn.run(
        "app.web.app:app",
        host=args.host or settings.server_host,
        port=args.port or settings.server_port,
        reload=args.reload,
        log_level=settings.log_level.lower()
    )


if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()