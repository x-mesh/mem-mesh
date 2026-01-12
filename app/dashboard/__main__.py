"""FastAPI 대시보드 진입점"""
import uvicorn
from ..core.config import Settings

def main():
    """대시보드 서버 메인 함수"""
    settings = Settings()
    
    uvicorn.run(
        "app.dashboard.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=False,
        log_level=settings.log_level.lower()
    )

if __name__ == "__main__":
    main()