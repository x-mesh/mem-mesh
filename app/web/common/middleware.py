"""
공통 미들웨어 및 에러 핸들러.

CORS, 에러 처리 등 공통 기능을 제공합니다.
"""

import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.schemas.responses import ErrorResponse

logger = logging.getLogger(__name__)


def setup_middleware(app: FastAPI) -> None:
    """미들웨어 설정"""
    # CORS 미들웨어 추가
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 개발용, 운영에서는 제한 필요
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def setup_exception_handlers(app: FastAPI) -> None:
    """예외 핸들러 설정"""
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc: HTTPException):
        """HTTP 예외 핸들러"""
        error_response = ErrorResponse(
            error=f"HTTP_{exc.status_code}",
            message=exc.detail
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response.model_dump()
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request, exc: Exception):
        """일반 예외 핸들러"""
        logger.error(f"Unhandled exception: {exc}")
        error_response = ErrorResponse(
            error="INTERNAL_ERROR",
            message="Internal server error"
        )
        return JSONResponse(
            status_code=500,
            content=error_response.model_dump()
        )