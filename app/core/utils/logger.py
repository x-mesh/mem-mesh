"""
Enhanced structured logging module for mem-mesh server with file logging support.

This module provides structured logging with configurable format (JSON or text),
configurable log levels, file logging, and performance monitoring capabilities.

환경변수 (MEM_MESH_* 우선, MCP_* deprecated fallback):
- MEM_MESH_LOG_LEVEL: 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- MEM_MESH_LOG_FILE: 로그 파일 경로 (선택)
- MEM_MESH_LOG_FORMAT: 로그 형식 (json 또는 text, 기본값: text)
- MEM_MESH_LOG_OUTPUT: 출력 대상 (console, file, both)

사용법:
```python
# 기본 사용법
from app.core.utils.logger import get_logger, setup_logging

# 로깅 시스템 초기화 (애플리케이션 시작 시 한 번만)
setup_logging()

# 로거 인스턴스 가져오기
logger = get_logger("my-module")
logger.info("Hello world", extra_field="value")

# 또는 직접 사용
from app.core.utils.logger import logger
logger.info("Hello world")
```
"""

import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Union

# 전역 로거 인스턴스들을 저장할 딕셔너리
_loggers: Dict[str, "MemMeshLogger"] = {}
_initialized = False


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "extra_fields") and getattr(record, "extra_fields", None):
            log_entry.update(getattr(record, "extra_fields"))

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "request_id"):
            log_entry["request_id"] = getattr(record, "request_id")

        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = getattr(record, "duration_ms")

        if hasattr(record, "method"):
            log_entry["method"] = getattr(record, "method")

        if hasattr(record, "path"):
            log_entry["path"] = getattr(record, "path")

        return json.dumps(log_entry, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """
    Human-readable text formatter for logging.
    """

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        # 기본 메시지 포맷
        base_message = super().format(record)

        # extra_fields가 있으면 추가
        if hasattr(record, "extra_fields"):
            extra_fields = getattr(record, "extra_fields", {})
            if extra_fields:
                extras = ", ".join(f"{k}={v}" for k, v in extra_fields.items())
                base_message = f"{base_message} [{extras}]"

        return base_message


def get_formatter() -> logging.Formatter:
    """환경변수에 따라 적절한 formatter 반환"""
    # MEM_MESH_LOG_FORMAT 우선, MCP_LOG_FORMAT deprecated fallback
    log_format = (
        os.getenv("MEM_MESH_LOG_FORMAT") or os.getenv("MCP_LOG_FORMAT") or "text"
    ).lower()

    if log_format == "json":
        return JSONFormatter()
    else:
        return TextFormatter()


class MemMeshLogger:
    """
    Main logger class for mem-mesh with structured logging and file support.
    """

    def __init__(self, name: str = "mem-mesh"):
        self.name = name
        self.logger = logging.getLogger(name)
        # 항상 설정을 적용 (초기화 플래그와 관계없이)
        self._setup_logger()

    def _setup_logger(self) -> None:
        """Setup logger with appropriate formatter and handlers."""
        # 이미 핸들러가 있고 올바른 레벨이 설정되어 있으면 중복 설정 방지
        current_level = self.logger.getEffectiveLevel()
        expected_level = getattr(logging, self._get_log_level().upper(), logging.INFO)

        if self.logger.handlers and current_level == expected_level:
            return

        # 기존 핸들러 제거
        self.logger.handlers.clear()

        # Set log level from environment or default
        log_level_str = self._get_log_level().upper()
        log_level = getattr(logging, log_level_str, logging.INFO)
        self.logger.setLevel(log_level)

        # Get formatter based on environment
        formatter = get_formatter()

        # 출력 대상 설정
        log_output = self._get_log_output().lower()
        log_file = self._get_log_file()

        # 콘솔 핸들러 추가 (console 또는 both)
        if log_output in ["console", "both"]:
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setLevel(log_level)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

        # 파일 핸들러 추가 (file 또는 both, 그리고 로그 파일이 설정된 경우)
        if log_file and log_output in ["file", "both"]:
            try:
                log_path = Path(log_file)
                log_path.parent.mkdir(parents=True, exist_ok=True)

                file_handler = logging.FileHandler(log_file, encoding="utf-8")
                file_handler.setLevel(log_level)
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)
            except Exception as e:
                # 파일 핸들러 생성 실패 시 stderr로 경고 (콘솔 핸들러가 없을 수도 있으므로 직접 출력)
                print(
                    f"Warning: Could not create log file {log_file}: {e}",
                    file=sys.stderr,
                )

        # 핸들러가 하나도 없으면 기본 콘솔 핸들러 추가
        if not self.logger.handlers:
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setLevel(log_level)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

        # Prevent duplicate logs from parent loggers
        self.logger.propagate = False

    def _get_log_level(self) -> str:
        """로그 레벨 (MEM_MESH_LOG_LEVEL 우선, MCP_LOG_LEVEL deprecated fallback)"""
        return os.getenv("MEM_MESH_LOG_LEVEL") or os.getenv("MCP_LOG_LEVEL") or "INFO"

    def _get_log_file(self) -> str:
        """로그 파일 경로 (MEM_MESH_LOG_FILE 우선, MCP_LOG_FILE deprecated fallback)"""
        return os.getenv("MEM_MESH_LOG_FILE") or os.getenv("MCP_LOG_FILE") or ""

    def _get_log_output(self) -> str:
        """로그 출력 대상 (MEM_MESH_LOG_OUTPUT 우선, MCP_LOG_OUTPUT deprecated fallback)"""
        return (
            os.getenv("MEM_MESH_LOG_OUTPUT") or os.getenv("MCP_LOG_OUTPUT") or "console"
        )

    def info(self, message: str, **kwargs) -> None:
        """Log info message with optional extra fields."""
        self._log_with_extra(logging.INFO, message, kwargs)

    def debug(self, message: str, **kwargs) -> None:
        """Log debug message with optional extra fields."""
        self._log_with_extra(logging.DEBUG, message, kwargs)

    def warning(self, message: str, **kwargs) -> None:
        """Log warning message with optional extra fields."""
        self._log_with_extra(logging.WARNING, message, kwargs)

    def error(self, message: str, **kwargs) -> None:
        """Log error message with optional extra fields."""
        self._log_with_extra(logging.ERROR, message, kwargs)

    def critical(self, message: str, **kwargs) -> None:
        """Log critical message with optional extra fields."""
        self._log_with_extra(logging.CRITICAL, message, kwargs)

    def info_debug(self, info_msg: str, debug_msg: str = None, **kwargs) -> None:
        """
        조건부 로깅: DEBUG 레벨이면 debug_msg를, 아니면 info_msg를 로깅합니다.

        Args:
            info_msg: INFO 레벨에서 보여줄 메시지
            debug_msg: DEBUG 레벨에서 보여줄 메시지 (None이면 info_msg 사용)
            **kwargs: 추가 필드들
        """
        if self.logger.isEnabledFor(logging.DEBUG):
            self.debug(debug_msg or info_msg, **kwargs)
        else:
            self.info(info_msg, **kwargs)

    def info_with_details(
        self, base_msg: str, details: Dict[str, Any] = None, **kwargs
    ) -> None:
        """
        조건부 상세 로깅: DEBUG 레벨이면 details를 포함하여 로깅합니다.

        Args:
            base_msg: 기본 메시지
            details: DEBUG 레벨에서만 포함할 상세 정보
            **kwargs: 추가 필드들
        """
        if self.logger.isEnabledFor(logging.DEBUG) and details:
            # DEBUG 레벨에서는 details를 kwargs에 병합
            combined_kwargs = {**kwargs, **details}
            self.debug(base_msg, **combined_kwargs)
        else:
            # INFO 레벨에서는 기본 kwargs만 사용
            self.info(base_msg, **kwargs)

    def _log_with_extra(
        self, level: int, message: str, extra_fields: Dict[str, Any]
    ) -> None:
        record = self.logger.makeRecord(
            self.logger.name, level, "", 0, message, (), None
        )
        # 동적으로 extra_fields 속성 추가
        setattr(record, "extra_fields", extra_fields)
        self.logger.handle(record)

    @contextmanager
    def log_duration(self, operation: str, **context) -> Generator[None, None, None]:
        """Context manager to log operation duration."""
        start_time = time.time()
        self.debug(f"Starting {operation}", operation=operation, **context)

        try:
            yield
            duration_ms = (time.time() - start_time) * 1000
            self.info(
                f"Completed {operation}",
                operation=operation,
                duration_ms=round(duration_ms, 2),
                **context,
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.error(
                f"Failed {operation}: {str(e)}",
                operation=operation,
                duration_ms=round(duration_ms, 2),
                error=str(e),
                **context,
            )
            raise

    def log_request(
        self,
        method: str,
        path: str,
        duration_ms: float,
        status_code: Optional[int] = None,
        **context,
    ) -> None:
        """Log HTTP request with timing information."""
        log_data = {
            "method": method,
            "path": path,
            "duration_ms": round(duration_ms, 2),
            **context,
        }

        if status_code:
            log_data["status_code"] = status_code

        if duration_ms > 200:
            self.warning("Slow request detected", **log_data)
        else:
            self.info("Request processed", **log_data)


# Global logger instance
logger = MemMeshLogger()


def get_logger(name: str = "mem-mesh") -> MemMeshLogger:
    """
    Get a logger instance with the specified name.

    Args:
        name: Logger name (e.g., "mem-mesh-web", "mem-mesh-mcp-server")

    Returns:
        MemMeshLogger instance
    """
    global _loggers

    if name not in _loggers:
        _loggers[name] = MemMeshLogger(name)

    return _loggers[name]


def setup_logging(
    logger_name: Optional[str] = None,
) -> Union[MemMeshLogger, logging.Logger]:
    """
    Setup global logging configuration with file logging support.

    Args:
        logger_name: Optional logger name for specific modules (e.g., "mem-mesh-mcp-server")

    Returns:
        Logger instance (MemMeshLogger for default, standard Logger for specific names)
    """
    global logger, _initialized, _loggers

    # 환경변수 읽기 (MEM_MESH_* 우선, MCP_* deprecated fallback)
    log_level = os.getenv("MEM_MESH_LOG_LEVEL") or os.getenv("MCP_LOG_LEVEL") or "INFO"
    log_file = os.getenv("MEM_MESH_LOG_FILE") or os.getenv("MCP_LOG_FILE") or ""
    log_format = (
        os.getenv("MEM_MESH_LOG_FORMAT") or os.getenv("MCP_LOG_FORMAT") or "text"
    )
    log_output = (
        os.getenv("MEM_MESH_LOG_OUTPUT") or os.getenv("MCP_LOG_OUTPUT") or "console"
    )

    # 파일 로깅이 설정된 경우 디렉토리 생성
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(
                f"Warning: Could not create log directory for {log_file}: {e}",
                file=sys.stderr,
            )

    # 초기화 플래그 설정
    _initialized = True

    # 특정 로거 이름이 지정된 경우 (MCP 서버용)
    if logger_name:
        return setup_simple_logger(logger_name)

    # 기본 로거 초기화 (환경변수가 설정되어 있으면 자동으로 파일 핸들러 추가됨)
    logger = MemMeshLogger()

    # 기존 로거들도 재설정
    for existing_logger in _loggers.values():
        existing_logger._setup_logger()

    logger.info(
        "Logging system initialized",
        log_level=log_level,
        log_format=log_format,
        log_output=log_output,
        log_file=log_file if log_file else "console_only",
    )

    return logger


def setup_simple_logger(name: str) -> logging.Logger:
    """
    Setup a simple standard logger for MCP servers and other modules.

    Args:
        name: Logger name

    Returns:
        Standard logging.Logger instance
    """
    # 환경변수 조회 (MEM_MESH_* 우선, MCP_* deprecated fallback)
    log_level_str = (
        os.getenv("MEM_MESH_LOG_LEVEL") or os.getenv("MCP_LOG_LEVEL") or "INFO"
    ).upper()

    log_file = os.getenv("MEM_MESH_LOG_FILE") or os.getenv("MCP_LOG_FILE") or ""

    log_format = (
        os.getenv("MEM_MESH_LOG_FORMAT") or os.getenv("MCP_LOG_FORMAT") or "text"
    )

    log_output = (
        os.getenv("MEM_MESH_LOG_OUTPUT") or os.getenv("MCP_LOG_OUTPUT") or "console"
    ).lower()

    # 로그 레벨 매핑
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    log_level = level_map.get(log_level_str, logging.INFO)

    # 로거 생성
    simple_logger = logging.getLogger(name)
    simple_logger.setLevel(log_level)

    # 기존 핸들러 제거 (중복 방지)
    simple_logger.handlers.clear()

    # 포맷터 설정
    if log_format.lower() == "json":
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # 콘솔 핸들러 추가 (console 또는 both)
    if log_output in ["console", "both"]:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(log_level)
        stderr_handler.setFormatter(formatter)
        simple_logger.addHandler(stderr_handler)

    # 파일 핸들러 추가 (file 또는 both, 그리고 로그 파일이 설정된 경우)
    if log_file and log_output in ["file", "both"]:
        try:
            # 디렉토리 생성
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(log_level)
            file_handler.setFormatter(formatter)
            simple_logger.addHandler(file_handler)
            simple_logger.info(f"File logging enabled: {log_file}")
        except Exception as e:
            simple_logger.warning(f"Could not create log file {log_file}: {e}")

    # 핸들러가 하나도 없으면 기본 콘솔 핸들러 추가
    if not simple_logger.handlers:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(log_level)
        stderr_handler.setFormatter(formatter)
        simple_logger.addHandler(stderr_handler)

    simple_logger.info(
        f"Logging initialized: level={log_level_str}, output={log_output}, file={log_file or 'none'}"
    )
    simple_logger.propagate = False

    return simple_logger
