"""
공통 미들웨어 및 에러 핸들러.

CORS, 에러 처리 등 공통 기능을 제공합니다.
"""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.errors import MemMeshError
from app.core.schemas.responses import ErrorResponse

logger = logging.getLogger(__name__)


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """Static 파일에 no-cache 헤더 추가 (개발 환경용)"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Disable cache for static file requests
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        return response


def setup_middleware(app: FastAPI) -> None:
    """미들웨어 설정"""
    settings = get_settings()

    # Middleware to disable static file cache (for development)
    app.add_middleware(NoCacheStaticMiddleware)

    # Add CORS middleware
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def setup_exception_handlers(app: FastAPI) -> None:
    """예외 핸들러 설정"""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc: HTTPException):
        """HTTP 예외 핸들러"""
        if isinstance(exc.detail, dict):
            detail = dict(exc.detail)
            message = detail.pop("message", str(exc.detail))
            error_code = detail.pop("error", f"HTTP_{exc.status_code}")
            error_response = ErrorResponse(
                error=error_code, message=message, details=detail or None
            )
        else:
            error_response = ErrorResponse(
                error=f"HTTP_{exc.status_code}", message=exc.detail
            )
        return JSONResponse(
            status_code=exc.status_code, content=error_response.model_dump()
        )

    @app.exception_handler(MemMeshError)
    async def memmesh_exception_handler(request, exc: MemMeshError):
        """MemMeshError → code-specific HTTP status (422 for content rules, 400/404/409/...)"""
        error_response = ErrorResponse(
            error=exc.error_code,
            message=str(exc),
            details=exc.details or None,
        )
        return JSONResponse(
            status_code=exc.http_status, content=error_response.model_dump()
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request, exc: Exception):
        """일반 예외 핸들러 — 예상치 못한 예외만 500으로 변환"""
        logger.error(f"Unhandled exception: {exc}")
        error_response = ErrorResponse(
            error="INTERNAL_ERROR", message="Internal server error"
        )
        return JSONResponse(status_code=500, content=error_response.model_dump())
