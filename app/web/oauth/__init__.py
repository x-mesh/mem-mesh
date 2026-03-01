"""OAuth 2.1 Web Endpoints and Basic Auth."""

from fastapi import APIRouter

from .login_routes import router as login_router
from .routes import router as oauth_router

# Combined router
router = APIRouter()
router.include_router(oauth_router)
router.include_router(login_router)

__all__ = ["router"]
