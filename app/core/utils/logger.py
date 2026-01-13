"""
Enhanced structured logging module for mem-mesh server with file logging support.

This module provides structured logging with configurable format (JSON or text),
configurable log levels, file logging, and performance monitoring capabilities.

환경변수:
- MCP_LOG_LEVEL: 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- MCP_LOG_FILE: 로그 파일 경로 (선택)
- MCP_LOG_FORMAT: 로그 형식 (json 또는 text, 기본값: text)
"""

import json
import logging
import sys
import time
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from contextlib import contextmanager
from pathlib import Path

from ..config import Settings


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
        
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)
        
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms
            
        if hasattr(record, "method"):
            log_entry["method"] = record.method
            
        if hasattr(record, "path"):
            log_entry["path"] = record.path
        
        return json.dumps(log_entry, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """
    Human-readable text formatter for logging.
    """
    
    def __init__(self):
        super().__init__(
            fmt="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    
    def format(self, record: logging.LogRecord) -> str:
        # 기본 메시지 포맷
        base_message = super().format(record)
        
        # extra_fields가 있으면 추가
        if hasattr(record, "extra_fields") and record.extra_fields:
            extras = ", ".join(f"{k}={v}" for k, v in record.extra_fields.items())
            base_message = f"{base_message} [{extras}]"
        
        return base_message


def get_formatter() -> logging.Formatter:
    """환경변수에 따라 적절한 formatter 반환"""
    log_format = os.getenv("MCP_LOG_FORMAT", "text").lower()
    
    if log_format == "json":
        return JSONFormatter()
    else:
        return TextFormatter()


class MemMeshLogger:
    """
    Main logger class for mem-mesh with structured logging and file support.
    """
    
    def __init__(self, name: str = "mem-mesh"):
        self.logger = logging.getLogger(name)
        self._setup_logger()
    
    def _setup_logger(self) -> None:
        """Setup logger with appropriate formatter and handlers."""
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Set log level from environment or default
        log_level_str = os.getenv("MCP_LOG_LEVEL", "INFO").upper()
        log_level = getattr(logging, log_level_str, logging.INFO)
        self.logger.setLevel(log_level)
        
        # Get formatter based on environment
        formatter = get_formatter()
        
        # Create console handler
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # Add file handler if MCP_LOG_FILE environment variable is set
        log_file = os.getenv("MCP_LOG_FILE")
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(log_level)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        
        # Prevent duplicate logs from parent loggers
        self.logger.propagate = False
    
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
    
    def _log_with_extra(self, level: int, message: str, extra_fields: Dict[str, Any]) -> None:
        record = self.logger.makeRecord(
            self.logger.name, level, "", 0, message, (), None
        )
        record.extra_fields = extra_fields
        self.logger.handle(record)

    @contextmanager
    def log_duration(self, operation: str, **context):
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
                **context
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.error(
                f"Failed {operation}: {str(e)}",
                operation=operation,
                duration_ms=round(duration_ms, 2),
                error=str(e),
                **context
            )
            raise
    
    def log_request(self, method: str, path: str, duration_ms: float, 
                   status_code: Optional[int] = None, **context) -> None:
        """Log HTTP request with timing information."""
        log_data = {
            "method": method,
            "path": path,
            "duration_ms": round(duration_ms, 2),
            **context
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
    """Get a logger instance."""
    return MemMeshLogger(name)


def setup_logging() -> None:
    """Setup global logging configuration."""
    global logger
    logger = MemMeshLogger()
    
    log_level = os.getenv("MCP_LOG_LEVEL", "INFO")
    log_file = os.getenv("MCP_LOG_FILE", "")
    log_format = os.getenv("MCP_LOG_FORMAT", "text")
    
    logger.info("Logging system initialized", 
                log_level=log_level, 
                log_format=log_format,
                log_file=log_file if log_file else "console_only")
