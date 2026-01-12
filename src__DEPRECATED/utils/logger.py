"""
Structured JSON logging module for mem-mesh server.

This module provides structured logging with JSON format output,
configurable log levels, and performance monitoring capabilities.
"""

import json
import logging
import sys
import time
from datetime import datetime
from typing import Any, Dict, Optional
from contextlib import contextmanager

from src.config import get_settings


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging.
    
    Formats log records as JSON with consistent structure including
    timestamp, level, message, and additional context fields.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON string.
        
        Args:
            record: The log record to format
            
        Returns:
            str: JSON formatted log message
        """
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add extra fields if present
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add request context if available
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms
            
        if hasattr(record, "method"):
            log_entry["method"] = record.method
            
        if hasattr(record, "path"):
            log_entry["path"] = record.path
        
        return json.dumps(log_entry, ensure_ascii=False)


class MemMeshLogger:
    """
    Main logger class for mem-mesh with structured JSON logging.
    
    Provides methods for logging with additional context and
    performance monitoring capabilities.
    """
    
    def __init__(self, name: str = "mem-mesh"):
        """
        Initialize logger with JSON formatting.
        
        Args:
            name: Logger name (default: "mem-mesh")
        """
        self.logger = logging.getLogger(name)
        self._setup_logger()
    
    def _setup_logger(self) -> None:
        """Setup logger with JSON formatter and appropriate handlers."""
        settings = get_settings()
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Set log level
        log_level = getattr(logging, settings.log_level.upper())
        self.logger.setLevel(log_level)
        
        # Create console handler with JSON formatter
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(log_level)
        handler.setFormatter(JSONFormatter())
        
        self.logger.addHandler(handler)
        
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
        """
        Log message with extra fields.
        
        Args:
            level: Log level
            message: Log message
            extra_fields: Additional fields to include in log
        """
        record = self.logger.makeRecord(
            self.logger.name, level, "", 0, message, (), None
        )
        record.extra_fields = extra_fields
        self.logger.handle(record)

    @contextmanager
    def log_duration(self, operation: str, **context):
        """
        Context manager to log operation duration.
        
        Args:
            operation: Name of the operation being timed
            **context: Additional context to include in logs
            
        Usage:
            with logger.log_duration("embedding_generation", model="MiniLM"):
                # operation code here
                pass
        """
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
        """
        Log HTTP request with timing information.
        
        Args:
            method: HTTP method
            path: Request path
            duration_ms: Request duration in milliseconds
            status_code: HTTP status code (optional)
            **context: Additional context fields
        """
        log_data = {
            "method": method,
            "path": path,
            "duration_ms": round(duration_ms, 2),
            **context
        }
        
        if status_code:
            log_data["status_code"] = status_code
        
        # Log as warning if request is slow
        if duration_ms > 200:  # Requirements 9.5: log warning for slow searches
            self.warning("Slow request detected", **log_data)
        else:
            self.info("Request processed", **log_data)
    
    def log_performance_warning(self, operation: str, duration_ms: float, 
                               threshold_ms: float, **context) -> None:
        """
        Log performance warning when operation exceeds threshold.
        
        Args:
            operation: Operation name
            duration_ms: Actual duration
            threshold_ms: Expected threshold
            **context: Additional context
        """
        self.warning(
            f"{operation} exceeded performance threshold",
            operation=operation,
            duration_ms=round(duration_ms, 2),
            threshold_ms=threshold_ms,
            **context
        )


# Global logger instance
logger = MemMeshLogger()


def get_logger(name: str = "mem-mesh") -> MemMeshLogger:
    """
    Get a logger instance.
    
    Args:
        name: Logger name
        
    Returns:
        MemMeshLogger: Logger instance
    """
    return MemMeshLogger(name)


def setup_logging() -> None:
    """
    Setup global logging configuration.
    
    This function should be called once at application startup
    to configure logging according to the current settings.
    """
    global logger
    logger = MemMeshLogger()
    logger.info("Logging system initialized", log_level=get_settings().log_level)