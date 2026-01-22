"""FastAPI Web 서버 진입점"""
import argparse
import os
import logging
import uvicorn
from dotenv import load_dotenv
from app.core.config import Settings
from app.core.utils.logger import setup_logging


def get_uvicorn_log_config(access_log_file: str = None, log_level: str = "info", log_output: str = "console"):
    """Uvicorn 로깅 설정 생성
    
    Args:
        access_log_file: Access log 파일 경로 (None이면 파일 로깅 비활성화)
        log_level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_output: 로그 출력 대상 (console, file, both)
    """
    
    # 기본 포맷터
    formatters = {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": "%(levelprefix)s %(message)s",
            "use_colors": True,
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
        },
        "access_file": {
            # 파일용 포맷터 - Uvicorn AccessFormatter 사용
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": '%(asctime)s - %(client_addr)s - "%(request_line)s" %(status_code)s',
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "use_colors": False,
        },
    }
    
    # 핸들러 설정
    handlers = {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
    }
    
    # Access log 파일 핸들러 추가
    if access_log_file:
        handlers["access_file"] = {
            "formatter": "access_file",
            "class": "logging.FileHandler",
            "filename": access_log_file,
            "mode": "a",
        }
    
    # log_output에 따라 access 핸들러 결정
    access_handlers = []
    if log_output in ("console", "both"):
        access_handlers.append("access")
    if access_log_file and log_output in ("file", "both"):
        access_handlers.append("access_file")
    
    # 핸들러가 없으면 최소한 콘솔 출력
    if not access_handlers:
        access_handlers = ["access"]
    
    # 로거 설정
    loggers = {
        "uvicorn": {"handlers": ["default"], "level": log_level.upper(), "propagate": False},
        "uvicorn.error": {"level": log_level.upper()},
        "uvicorn.access": {
            "handlers": access_handlers,
            "level": log_level.upper(),
            "propagate": False,
        },
    }
    
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": formatters,
        "handlers": handlers,
        "loggers": loggers,
    }


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
    
    # Access log 파일 설정
    access_log_file = None
    
    if settings.log_output in ("file", "both"):
        # 접근 로그 파일 경로 설정
        if settings.log_file:
            log_dir = os.path.dirname(settings.log_file)
            access_log_file = os.path.join(log_dir, "access.log")
        else:
            access_log_file = "./logs/access.log"
        
        # 로그 디렉토리 생성
        os.makedirs(os.path.dirname(access_log_file), exist_ok=True)
        print(f"Access log file: {access_log_file}")
    
    # Uvicorn 로그 설정 생성
    log_config = get_uvicorn_log_config(
        access_log_file=access_log_file,
        log_level=settings.log_level,
        log_output=settings.log_output
    )
    
    uvicorn_config = {
        "app": "app.web.app:app",
        "host": args.host or settings.server_host,
        "port": args.port or settings.server_port,
        "workers": workers,
        "log_level": settings.log_level.lower(),
        "log_config": log_config,
        "access_log": True,
        "use_colors": settings.log_output != "file",  # 파일 전용이면 색상 비활성화
        "timeout_keep_alive": 5,
        "timeout_graceful_shutdown": 5,
    }
    
    # reload 설정 추가
    if reload_config:
        uvicorn_config.update(reload_config)
    
    uvicorn.run(**uvicorn_config)


if __name__ == "__main__":
    main()