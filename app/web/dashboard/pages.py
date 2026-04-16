"""
Dashboard 페이지 라우터.

SPA (Single Page Application) 라우팅을 위한 페이지 서빙을 담당합니다.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

from app.core.version import __VERSION__

# Create page router
router = APIRouter(tags=["Dashboard Pages"])

# Configure Jinja2 templates (resolved relative to the app.web package)
_WEB_ROOT = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(_WEB_ROOT / "templates"))


@router.get("/")
async def serve_web_ui(request: Request):
    """웹 UI 서빙"""
    return templates.TemplateResponse(
        request, "index.html", {"version": __VERSION__}
    )


@router.get("/about")
async def serve_about_page(request: Request):
    """About 페이지 서빙 (SPA 라우팅)"""
    return templates.TemplateResponse(
        request, "index.html", {"version": __VERSION__}
    )


@router.get("/dashboard")
async def serve_dashboard_page(request: Request):
    """Dashboard 페이지 서빙 (SPA 라우팅)"""
    return templates.TemplateResponse(
        request, "index.html", {"version": __VERSION__}
    )


@router.get("/search")
async def serve_search_page(request: Request):
    """검색 페이지 서빙 (SPA 라우팅)"""
    return templates.TemplateResponse(
        request, "index.html", {"version": __VERSION__}
    )


@router.get("/memory/{memory_id}")
async def serve_memory_page(request: Request, memory_id: str):
    """메모리 상세 페이지 서빙 (SPA 라우팅)"""
    return templates.TemplateResponse(
        request, "index.html", {"version": __VERSION__}
    )


@router.get("/create")
async def serve_create_page(request: Request):
    """메모리 생성 페이지 서빙 (SPA 라우팅)"""
    return templates.TemplateResponse(
        request, "index.html", {"version": __VERSION__}
    )


@router.get("/edit/{memory_id}")
async def serve_edit_page(request: Request, memory_id: str):
    """메모리 편집 페이지 서빙 (SPA 라우팅)"""
    return templates.TemplateResponse(
        request, "index.html", {"version": __VERSION__}
    )


@router.get("/projects")
async def serve_projects_page(request: Request):
    """프로젝트 페이지 서빙 (SPA 라우팅)"""
    return templates.TemplateResponse(
        request, "index.html", {"version": __VERSION__}
    )


@router.get("/project/{project_id}")
async def serve_project_page(request: Request, project_id: str):
    """프로젝트 상세 페이지 서빙 (SPA 라우팅)"""
    return templates.TemplateResponse(
        request, "index.html", {"version": __VERSION__}
    )


@router.get("/analytics")
async def serve_analytics_page(request: Request):
    """분석 페이지 서빙 (SPA 라우팅)"""
    return templates.TemplateResponse(
        request, "index.html", {"version": __VERSION__}
    )


@router.get("/work")
async def serve_work_page(request: Request):
    """Work Tracking 페이지 서빙 (SPA 라우팅)"""
    return templates.TemplateResponse(
        request, "index.html", {"version": __VERSION__}
    )


@router.get("/monitoring")
async def serve_monitoring_page(request: Request):
    """모니터링 페이지 서빙 (SPA 라우팅)"""
    return templates.TemplateResponse(
        request, "index.html", {"version": __VERSION__}
    )


@router.get("/settings")
async def serve_settings_page(request: Request):
    """설정 페이지 서빙 (SPA 라우팅)"""
    return templates.TemplateResponse(
        request, "index.html", {"version": __VERSION__}
    )


# Catch-all route for SPA routing (must be last)
@router.get("/{path:path}")
async def serve_spa_routes(request: Request, path: str):
    """SPA 라우팅을 위한 catch-all 라우트"""
    # Exclude API paths
    if path.startswith("api"):
        raise HTTPException(status_code=404, detail="Not Found")

    # Exclude MCP paths (handled by MCP SSE router)
    if path.startswith("mcp"):
        raise HTTPException(status_code=404, detail="Not Found")

    # Exclude static file paths (already mounted at /static)
    if path.startswith("static"):
        raise HTTPException(status_code=404, detail="Not Found")

    # Exclude docs paths (FastAPI auto-docs)
    if path in ["docs", "redoc", "openapi.json"]:
        raise HTTPException(status_code=404, detail="Not Found")

    # Serve index.html for all other paths (SPA routing)
    return templates.TemplateResponse(
        request, "index.html", {"version": __VERSION__}
    )
