"""
Dashboard 전용 FastAPI 애플리케이션.

MCP SSE 엔드포인트를 제외한 웹 UI와 REST API만 제공합니다.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.version import __VERSION__
from app.web.common.middleware import setup_exception_handlers, setup_middleware
from app.web.dashboard import pages as dashboard_pages
from app.web.dashboard import routes as dashboard_routes
from app.web.lifespan import lifespan
from app.web.monitoring import router as monitoring_router
from app.web.websocket import router as websocket_router

templates = Jinja2Templates(directory="templates")


def create_dashboard_app() -> FastAPI:
    """Dashboard 전용 FastAPI 애플리케이션 생성"""
    from app.core.config import get_settings

    app = FastAPI(
        title="mem-mesh Dashboard",
        description="Web Dashboard for mem-mesh memory management",
        version=__VERSION__,
        lifespan=lifespan,
    )

    setup_middleware(app)

    settings = get_settings()
    if settings.web_basic_auth_enabled:
        from app.web.oauth.basic_auth import BasicAuthMiddleware
        from app.web.oauth.login_routes import router as login_router

        app.add_middleware(BasicAuthMiddleware)
        app.include_router(login_router)

    setup_exception_handlers(app)

    # Serve static files
    app.mount("/static", StaticFiles(directory="static"), name="static")

    # Register routers (excluding MCP)
    app.include_router(websocket_router)
    app.include_router(monitoring_router)
    app.include_router(dashboard_routes.router)
    app.include_router(dashboard_pages.router)

    return app


# App instance
app = create_dashboard_app()
