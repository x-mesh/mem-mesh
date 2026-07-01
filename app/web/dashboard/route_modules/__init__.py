"""
Dashboard routes aggregation module.

Combines all route modules into a single router for the dashboard API.
"""

from fastapi import APIRouter

from .chat import router as chat_router
from .connect import router as connect_router
from .curation import router as curation_router
from .hooks import router as hooks_router
from .memories import router as memories_router
from .oauth import router as oauth_router
from .relations import router as relations_router
from .relay import router as relay_router
from .search import router as search_router
from .security import router as security_router
from .settings_llm import router as settings_llm_router
from .stats import router as stats_router

router = APIRouter()

router.include_router(stats_router)
router.include_router(search_router)
router.include_router(memories_router)
router.include_router(oauth_router)
router.include_router(relay_router)
router.include_router(relations_router)
router.include_router(hooks_router)
router.include_router(security_router)
router.include_router(connect_router)
router.include_router(chat_router)
router.include_router(curation_router)
router.include_router(settings_llm_router)

__all__ = [
    "router",
    "memories_router",
    "search_router",
    "stats_router",
    "oauth_router",
    "relay_router",
    "relations_router",
    "hooks_router",
    "security_router",
    "connect_router",
    "chat_router",
    "curation_router",
    "settings_llm_router",
]
