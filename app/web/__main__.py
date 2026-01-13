"""FastAPI Web 서버 진입점"""
import argparse
import uvicorn
from dotenv import load_dotenv
from app.core.config import Settings
from app.core.utils.logger import setup_logging


def main():
    """Web 서버 메인 함수"""
    # .env 파일 먼저 로드
    load_dotenv()
    
    # 로깅 시스템 초기화 (.env 로드 후)
    setup_logging()
    
    parser = argparse.ArgumentParser(description="mem-mesh Web Server")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--host", type=str, help="Host address")
    parser.add_argument("--port", type=int, help="Port number")
    parser.add_argument("--workers", type=int, help="Number of worker processes")
    args = parser.parse_args()
    
    settings = Settings()
    
    # reload 모드에서는 workers를 1로 고정 (uvicorn 제한사항)
    workers = 1 if args.reload else (args.workers or settings.server_workers)
    
    uvicorn.run(
        "app.web.app:app",
        host=args.host or settings.server_host,
        port=args.port or settings.server_port,
        workers=workers,
        reload=args.reload,
        log_level=settings.log_level.lower()
    )


if __name__ == "__main__":
    main()