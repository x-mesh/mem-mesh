"""
Memory search API routes.

Provides endpoints for searching memories with various modes and filters.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends

from app.core.services.unified_search import UnifiedSearchService
from app.core.schemas.responses import SearchResponse
from ...common.dependencies import get_search_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Search"])


@router.get("/memories/search", response_model=SearchResponse)
async def search_memories(
    query: str,
    project_id: str = None,
    category: str = None,
    source: str = None,
    tag: str = None,
    limit: int = 25,
    offset: int = 0,
    sort_by: str = "created_at",
    sort_direction: str = "desc",
    recency_weight: float = 0.0,
    search_mode: str = "hybrid",
    service: UnifiedSearchService = Depends(get_search_service),
) -> SearchResponse:
    """
    Search memories with various modes and filters.

    search_mode options:
    - hybrid: Vector + text combined search (default)
    - exact: Exact text matching only
    - semantic: Semantic vector search only
    - fuzzy: Fuzzy search with typo tolerance

    sort options:
    - sort_by: created_at, updated_at, category, project, size
    - sort_direction: asc, desc
    """
    try:
        return await service.search(
            query=query,
            project_id=project_id,
            category=category,
            source=source,
            tag=tag,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_direction=sort_direction,
            recency_weight=recency_weight,
            search_mode=search_mode,
        )
    except Exception as e:
        logger.error(f"Search memories error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
