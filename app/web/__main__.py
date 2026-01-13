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
    
    # reload 설정 개선
    reload_config = None
    if args.reload:
        reload_config = {
            "reload": True,
            "reload_dirs": ["app", "static"],  # 감시할 디렉토리 명시
            "reload_excludes": ["*.pyc", "__pycache__", "*.db", "*.log", ".git"],  # 제외할 파일
            "reload_delay": 0.25,  # 파일 변경 감지 지연시간 (초)
        }
    
    uvicorn_config = {
        "app": "app.web.app:app",
        "host": args.host or settings.server_host,
        "port": args.port or settings.server_port,
        "workers": workers,
        "log_level": settings.log_level.lower(),
        "access_log": True,
        "use_colors": True,
        "timeout_keep_alive": 5,  # Keep-alive 연결 타임아웃 단축
        "timeout_graceful_shutdown": 5,  # Graceful shutdown 타임아웃 단축
    }
    
    # reload 설정 추가
    if reload_config:
        uvicorn_config.update(reload_config)
    
    uvicorn.run(**uvicorn_config)


if __name__ == "__main__":
    main()