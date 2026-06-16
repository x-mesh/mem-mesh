"""
Dashboard routes aggregation module.

Combines all route modules into a single router for the dashboard API.
"""

from fastapi import APIRouter

from .hooks import router as hooks_router
from .memories import router as memories_router
from .oauth import router as oauth_router
from .relations import router as relations_router
from .search import router as search_router
from .security import router as security_router
from .stats import router as stats_router

router = APIRouter()

router.include_router(stats_router)
router.include_router(search_router)
router.include_router(memories_router)
router.include_router(oauth_router)
router.include_router(relations_router)
router.include_router(hooks_router)
router.include_router(security_router)

__all__ = [
    "router",
    "memories_router",
    "search_router",
    "stats_router",
    "oauth_router",
    "relations_router",
    "hooks_router",
    "security_router",
]
