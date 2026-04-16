"""
FastAPI 애플리케이션 생성 및 설정.

모든 라우터와 미들웨어를 등록하여 완전한 웹 애플리케이션을 구성합니다.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.version import __VERSION__

from .common.middleware import setup_exception_handlers, setup_middleware
from .dashboard import pages as dashboard_pages
from .dashboard import routes as dashboard_routes
from .lifespan import lifespan
from .mcp import sse as mcp_sse
from .monitoring import router as monitoring_router
from .oauth import router as oauth_router
from .oauth.basic_auth import BasicAuthMiddleware
from .oauth.middleware import BearerTokenMiddleware
from .websocket import router as websocket_router

_WEB_ROOT = Path(__file__).resolve().parent

# Jinja2 template configuration
templates = Jinja2Templates(directory=str(_WEB_ROOT / "templates"))


def create_app() -> FastAPI:
    """FastAPI 애플리케이션 생성 및 설정"""

    # Create FastAPI app
    app = FastAPI(
        title="mem-mesh",
        description="Central memory server with vector search and context retrieval",
        version=__VERSION__,
        lifespan=lifespan,
    )

    # Configure middleware
    setup_middleware(app)
    app.add_middleware(BearerTokenMiddleware)
    app.add_middleware(BasicAuthMiddleware)  # Basic Auth for web dashboard

    # Configure exception handlers
    setup_exception_handlers(app)

    # Configure static file serving (register before routers)
    app.mount("/static", StaticFiles(directory=str(_WEB_ROOT / "static")), name="static")

    # Register routers (order matters!)
    app.include_router(oauth_router)  # OAuth endpoints
    app.include_router(websocket_router)  # WebSocket
    app.include_router(mcp_sse.router)  # MCP SSE
    app.include_router(monitoring_router)  # Monitoring API
    app.include_router(dashboard_routes.router)  # Dashboard API
    app.include_router(
        dashboard_pages.router
    )  # Dashboard Pages (last, because it has a catch-all)

    return app


# Create app instance
app = create_app()
