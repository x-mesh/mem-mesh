"""
FastAPI 애플리케이션 생성 및 설정.

모든 라우터와 미들웨어를 등록하여 완전한 웹 애플리케이션을 구성합니다.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.version import __VERSION__
from .lifespan import lifespan
from .common.middleware import setup_middleware, setup_exception_handlers
from .dashboard import routes as dashboard_routes
from .dashboard import pages as dashboard_pages
from .mcp import sse as mcp_sse
from .websocket import router as websocket_router
from .monitoring import router as monitoring_router


# Jinja2 템플릿 설정
templates = Jinja2Templates(directory="templates")


def create_app() -> FastAPI:
    """FastAPI 애플리케이션 생성 및 설정"""
    
    # FastAPI 앱 생성
    app = FastAPI(
        title="mem-mesh",
        description="Central memory server with vector search and context retrieval",
        version=__VERSION__,
        lifespan=lifespan
    )
    
    # 미들웨어 설정
    setup_middleware(app)
    
    # 예외 핸들러 설정
    setup_exception_handlers(app)
    
    # 정적 파일 서빙 설정 (라우터보다 먼저 등록)
    app.mount("/static", StaticFiles(directory="static"), name="static")
    
    # 라우터 등록 (순서 중요!)
    app.include_router(websocket_router)        # WebSocket (먼저 등록)
    app.include_router(mcp_sse.router)          # MCP SSE
    app.include_router(monitoring_router)       # Monitoring API
    app.include_router(dashboard_routes.router)  # Dashboard API
    app.include_router(dashboard_pages.router)  # Dashboard Pages (catch-all이 있으므로 마지막)
    
    return app


# 앱 인스턴스 생성
app = create_app()