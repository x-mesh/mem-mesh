"""
Dashboard 페이지 라우터.

SPA (Single Page Application) 라우팅을 위한 페이지 서빙을 담당합니다.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

# 페이지 라우터 생성
router = APIRouter(tags=["Dashboard Pages"])


@router.get("/")
async def serve_web_ui():
    """웹 UI 서빙"""
    return FileResponse("static/index.html")


@router.get("/about")
async def serve_about_page():
    """About 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@router.get("/dashboard")
async def serve_dashboard_page():
    """Dashboard 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@router.get("/search")
async def serve_search_page():
    """검색 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@router.get("/memory/{memory_id}")
async def serve_memory_page(memory_id: str):
    """메모리 상세 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@router.get("/create")
async def serve_create_page():
    """메모리 생성 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@router.get("/edit/{memory_id}")
async def serve_edit_page(memory_id: str):
    """메모리 편집 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@router.get("/projects")
async def serve_projects_page():
    """프로젝트 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@router.get("/project/{project_id}")
async def serve_project_page(project_id: str):
    """프로젝트 상세 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@router.get("/test")
async def serve_test_page():
    """테스트 페이지 서빙"""
    return FileResponse("test_web_ui.html")


@router.get("/analytics")
async def serve_analytics_page():
    """분석 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@router.get("/work")
async def serve_work_page():
    """Work Tracking 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


@router.get("/settings")
async def serve_settings_page():
    """설정 페이지 서빙 (SPA 라우팅)"""
    return FileResponse("static/index.html")


# Catch-all route for SPA routing (must be last)
@router.get("/{path:path}")
async def serve_spa_routes(path: str):
    """SPA 라우팅을 위한 catch-all 라우트"""
    # API 경로는 제외
    if path.startswith("api"):
        raise HTTPException(status_code=404, detail="Not Found")
    
    # MCP 경로는 제외 (MCP SSE 라우터에서 처리)
    if path.startswith("mcp"):
        raise HTTPException(status_code=404, detail="Not Found")
    
    # 정적 파일 경로는 제외 (이미 /static으로 마운트됨)
    if path.startswith("static"):
        raise HTTPException(status_code=404, detail="Not Found")
    
    # docs 경로는 제외 (FastAPI 자동 문서)
    if path in ["docs", "redoc", "openapi.json"]:
        raise HTTPException(status_code=404, detail="Not Found")
    
    # 모든 다른 경로는 index.html로 서빙 (SPA 라우팅)
    return FileResponse("static/index.html")