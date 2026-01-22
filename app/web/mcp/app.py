"""
MCP SSE 전용 FastAPI 애플리케이션.

MCP SSE 엔드포인트만 제공하며, 웹 UI는 제외됩니다.
localhost 바인딩과 API Key 인증을 통해 보안을 강화합니다.
"""

from fastapi import FastAPI

from app.core.version import __VERSION__
from app.web.mcp.lifespan import mcp_lifespan
from app.web.common.middleware import setup_middleware, setup_exception_handlers
from app.web.mcp import sse as mcp_sse


def create_mcp_app() -> FastAPI:
    """MCP 전용 FastAPI 애플리케이션 생성"""
    
    app = FastAPI(
        title="mem-mesh MCP Server",
        description="MCP SSE Server for AI agent memory management",
        version=__VERSION__,
        lifespan=mcp_lifespan
    )
    
    setup_middleware(app)
    setup_exception_handlers(app)
    
    # MCP 라우터만 등록
    app.include_router(mcp_sse.router)
    
    # 헬스체크 엔드포인트
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": "mcp-sse"}
    
    return app


# 앱 인스턴스
app = create_mcp_app()
