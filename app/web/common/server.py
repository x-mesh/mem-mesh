"""
공통 서버 유틸리티.

Dashboard와 MCP 서버에서 공유하는 uvicorn 설정 및 실행 로직.
"""

import os
from typing import Optional, Dict, Any
from dotenv import load_dotenv

from app.core.config import Settings
from app.core.utils.logger import setup_logging


def get_uvicorn_log_config(
    access_log_file: Optional[str] = None,
    log_level: str = "info",
    log_output: str = "console"
) -> Dict[str, Any]:
    """Uvicorn 로깅 설정 생성
    
    Args:
        access_log_file: Access log 파일 경로 (None이면 파일 로깅 비활성화)
        log_level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_output: 로그 출력 대상 (console, file, both)
    """
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
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": '%(asctime)s - %(client_addr)s - "%(request_line)s" %(status_code)s',
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "use_colors": False,
        },
    }
    
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
    
    if access_log_file:
        handlers["access_file"] = {
            "formatter": "access_file",
            "class": "logging.FileHandler",
            "filename": access_log_file,
            "mode": "a",
        }
    
    access_handlers = []
    if log_output in ("console", "both"):
        access_handlers.append("access")
    if access_log_file and log_output in ("file", "both"):
        access_handlers.append("access_file")
    
    if not access_handlers:
        access_handlers = ["access"]
    
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


def setup_access_log(settings: Settings, prefix: str = "") -> Optional[str]:
    """Access log 파일 설정
    
    Args:
        settings: 설정 객체
        prefix: 로그 파일 접두사 (예: "mcp-", "dashboard-")
    
    Returns:
        Access log 파일 경로 또는 None
    """
    if settings.log_output not in ("file", "both"):
        return None
    
    if settings.log_file:
        log_dir = os.path.dirname(settings.log_file)
        access_log_file = os.path.join(log_dir, f"{prefix}access.log")
    else:
        access_log_file = f"./logs/{prefix}access.log"
    
    os.makedirs(os.path.dirname(access_log_file), exist_ok=True)
    return access_log_file


def create_uvicorn_config(
    app_path: str,
    settings: Settings,
    host: Optional[str] = None,
    port: Optional[int] = None,
    workers: Optional[int] = None,
    reload: bool = False,
    access_log_prefix: str = ""
) -> Dict[str, Any]:
    """Uvicorn 설정 생성
    
    Args:
        app_path: FastAPI 앱 경로 (예: "app.web.app:app")
        settings: 설정 객체
        host: 호스트 주소 (None이면 settings 사용)
        port: 포트 번호 (None이면 settings 사용)
        workers: 워커 수 (None이면 settings 사용)
        reload: 자동 리로드 활성화
        access_log_prefix: Access log 파일 접두사
    
    Returns:
        Uvicorn 설정 딕셔너리
    """
    # reload 모드에서는 workers를 1로 고정
    final_workers = 1 if reload else (workers or settings.server_workers)
    
    # Access log 설정
    access_log_file = setup_access_log(settings, access_log_prefix)
    if access_log_file:
        print(f"Access log file: {access_log_file}")
    
    # 로그 설정
    log_config = get_uvicorn_log_config(
        access_log_file=access_log_file,
        log_level=settings.log_level,
        log_output=settings.log_output
    )
    
    config = {
        "app": app_path,
        "host": host or settings.server_host,
        "port": port or settings.server_port,
        "workers": final_workers,
        "log_level": settings.log_level.lower(),
        "log_config": log_config,
        "access_log": True,
        "use_colors": settings.log_output != "file",
        "timeout_keep_alive": 5,
        "timeout_graceful_shutdown": 5,
    }
    
    if reload:
        config.update({
            "reload": True,
            "reload_dirs": ["app", "static"],
            "reload_excludes": ["*.pyc", "__pycache__", "*.db", "*.log", ".git"],
            "reload_delay": 0.25,
        })
    
    return config


def init_server() -> Settings:
    """서버 초기화 공통 로직
    
    Returns:
        Settings 객체
    """
    load_dotenv()
    setup_logging()
    return Settings()
