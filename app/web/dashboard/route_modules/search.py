"""
Memory search API routes.

Provides endpoints for searching memories with various modes and filters.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.schemas.responses import SearchResponse
from app.core.services.unified_search import UnifiedSearchService

from ...common.dependencies import get_search_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Search"])


class SearchRequest(BaseModel):
    """POST search request body."""

    query: str = ""
    project_id: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None
    tag: Optional[str] = None
    limit: int = Field(default=25, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    sort_by: str = "created_at"
    sort_direction: str = "desc"
    recency_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    search_mode: str = "hybrid"
    time_range: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    temporal_mode: str = "boost"


async def _do_search(
    query: str,
    project_id: str,
    category: str,
    source: str,
    tag: str,
    limit: int,
    offset: int,
    sort_by: str,
    sort_direction: str,
    recency_weight: float,
    search_mode: str,
    service: UnifiedSearchService,
    time_range: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    temporal_mode: str = "boost",
) -> SearchResponse:
    """Shared search logic for GET and POST endpoints."""
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
            time_range=time_range,
            date_from=date_from,
            date_to=date_to,
            temporal_mode=temporal_mode,
        )
    except Exception as e:
        logger.error(f"Search memories error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    time_range: str = None,
    date_from: str = None,
    date_to: str = None,
    temporal_mode: str = "boost",
    service: UnifiedSearchService = Depends(get_search_service),
) -> SearchResponse:
    """
    Search memories with various modes and filters (GET).

    search_mode options:
    - hybrid: Vector + text combined search (default)
    - exact: Exact text matching only
    - semantic: Semantic vector search only
    - fuzzy: Fuzzy search with typo tolerance
    """
    return await _do_search(
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
        service=service,
        time_range=time_range,
        date_from=date_from,
        date_to=date_to,
        temporal_mode=temporal_mode,
    )


@router.post("/memories/search", response_model=SearchResponse)
async def search_memories_post(
    body: SearchRequest,
    service: UnifiedSearchService = Depends(get_search_service),
) -> SearchResponse:
    """
    Search memories with various modes and filters (POST).

    Accepts JSON body — useful for complex filter combinations that
    exceed URL length limits or require structured payloads.
    """
    return await _do_search(
        query=body.query,
        project_id=body.project_id,
        category=body.category,
        source=body.source,
        tag=body.tag,
        limit=body.limit,
        offset=body.offset,
        sort_by=body.sort_by,
        sort_direction=body.sort_direction,
        recency_weight=body.recency_weight,
        search_mode=body.search_mode,
        service=service,
        time_range=body.time_range,
        date_from=body.date_from,
        date_to=body.date_to,
        temporal_mode=body.temporal_mode,
    )


class ContextSearchRequest(BaseModel):
    """POST context-optimized search request body."""

    query: str = ""
    project_id: Optional[str] = None
    category: Optional[str] = None
    limit: int = Field(default=25, ge=1, le=500)
    optimize_context: bool = True


class ContextSearchResponse(BaseModel):
    """Context-optimized search response."""

    search_results: SearchResponse
    context: Optional[dict] = None


@router.post("/search/optimized", response_model=ContextSearchResponse)
async def search_with_context(
    body: ContextSearchRequest,
    service: UnifiedSearchService = Depends(get_search_service),
) -> ContextSearchResponse:
    """
    Search with context optimization.

    Analyzes search intent and loads optimized session context alongside
    search results. Reduces token usage while providing relevant context.
    """
    try:
        search_response, optimized_context = (
            await service.search_with_context_optimization(
                query=body.query,
                project_id=body.project_id,
                category=body.category,
                limit=body.limit,
                optimize_context=body.optimize_context,
            )
        )

        context_dict = None
        if optimized_context:
            try:
                context_dict = {
                    "session_id": getattr(optimized_context, "session_id", None),
                    "pins_count": (
                        len(optimized_context.pins)
                        if hasattr(optimized_context, "pins") and optimized_context.pins
                        else 0
                    ),
                    "strategy": getattr(optimized_context, "strategy", None),
                    "token_budget": getattr(optimized_context, "token_budget", None),
                }
            except Exception:
                context_dict = {"raw": str(optimized_context)}

        return ContextSearchResponse(
            search_results=search_response,
            context=context_dict,
        )
    except Exception as e:
        logger.error(f"Context-optimized search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
