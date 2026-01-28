"""
Dashboard routes aggregation module.

Combines all route modules into a single router for the dashboard API.
"""

from fastapi import APIRouter

from .memories import router as memories_router
from .search import router as search_router
from .stats import router as stats_router
from .oauth import router as oauth_router

router = APIRouter()

router.include_router(stats_router)
router.include_router(search_router)
router.include_router(memories_router)
router.include_router(oauth_router)

__all__ = ["router", "memories_router", "search_router", "stats_router", "oauth_router"]
