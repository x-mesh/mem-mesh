"""
Memory search API routes.

Provides endpoints for searching memories with various modes and filters.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.schemas.requests import normalize_anchored_path, normalize_project_id
from app.core.schemas.responses import SearchResponse
from app.core.services.recall import (
    fetch_curation_candidates,
    fetch_lessons,
    fetch_tag_facets,
)
from app.core.services.unified_search import UnifiedSearchService

from ...common.dependencies import get_database, get_search_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Search"])


class TagFacet(BaseModel):
    tag: str
    count: int


class TagFacetsResponse(BaseModel):
    facets: List[TagFacet] = Field(default_factory=list)


@router.get("/memories/tags", response_model=TagFacetsResponse)
async def memory_tag_facets(
    project_id: Optional[str] = None,
    limit: int = 30,
    db=Depends(get_database),
) -> TagFacetsResponse:
    """Top topic tags (enrichment + source) with counts, for facet navigation."""
    pid = normalize_project_id(project_id, strict=False) if project_id else None
    try:
        facets = await fetch_tag_facets(db, project_id=pid, limit=limit)
    except Exception as exc:
        logger.error(f"tag facets failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    return TagFacetsResponse(facets=[TagFacet(**f) for f in facets])


@router.get("/memories/curation-candidates")
async def memory_curation_candidates(
    project_id: Optional[str] = None,
    limit: int = 50,
    db=Depends(get_database),
) -> dict:
    """Memories flagged by enrichment for a curation look (miscategorized
    display_kind and/or low confidence)."""
    pid = normalize_project_id(project_id, strict=False) if project_id else None
    try:
        return {
            "candidates": await fetch_curation_candidates(
                db, project_id=pid, limit=limit
            )
        }
    except Exception as exc:
        logger.error(f"curation candidates failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/memories/lessons")
async def memory_lessons(
    project_id: Optional[str] = None,
    limit: int = 50,
    db=Depends(get_database),
) -> dict:
    """Reusable takeaways (enrichment 'lesson' field) rolled up — 'what we learned'."""
    pid = normalize_project_id(project_id, strict=False) if project_id else None
    try:
        return {"lessons": await fetch_lessons(db, project_id=pid, limit=limit)}
    except Exception as exc:
        logger.error(f"lessons failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


class SearchRequest(BaseModel):
    """POST search request body."""

    query: str = ""
    project_id: Optional[str] = None
    category: Optional[str] = None
    categories: Optional[List[str]] = None
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
    scope: str = "local"
    anchored_path: Optional[str] = Field(default=None, max_length=500)
    starred_only: bool = False


# Canonical memory categories (mirrors SearchParams.validate_category). Used to
# bound the user-controlled `categories` filter so a crafted/huge list can't blow
# up the SQL IN clause or the cache key.
_VALID_CATEGORIES = {
    "task",
    "bug",
    "idea",
    "decision",
    "incident",
    "code_snippet",
    "git-history",
}


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
    categories: Optional[List[str]] = None,
    time_range: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    temporal_mode: str = "boost",
    scope: str = "local",
    anchored_path: Optional[str] = None,
    starred_only: bool = False,
) -> SearchResponse:
    """Shared search logic for GET and POST endpoints."""
    # Single chokepoint for both GET (query param) and POST (body) search, so a
    # lookup for "MyProject" matches memories stored under the canonical
    # "my-project". strict=False: a malformed filter degrades to "unknown"
    # (empty result) rather than a 500.
    project_id = normalize_project_id(project_id, strict=False)
    # Bound the user-controlled multi-category filter: dedupe (order-preserving),
    # drop unknown categories, and cap at the number of real categories so a
    # crafted `categories=...` list can't expand the SQL IN clause / cache key.
    if categories:
        deduped: list[str] = []
        for c in categories:
            if c in _VALID_CATEGORIES and c not in deduped:
                deduped.append(c)
        categories = deduped[: len(_VALID_CATEGORIES)] or None
    # Unknown scope degrades to local (mirrors MCP tools.py:239-240 contract).
    if scope not in ("local", "hub", "all"):
        scope = "local"
    # Validate/normalize the anchored-path prefix (this path bypasses the
    # Pydantic SearchParams model); bad input → 422, not a silent no-op.
    if anchored_path:
        try:
            anchored_path = normalize_anchored_path(anchored_path)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    # Anchored search is local-only (hub rows carry foreign-repo anchors the
    # filter can't judge) — mirrors the MCP tools.py contract.
    if anchored_path:
        scope = "local"
    # Stars are a local judgement — a hub row can never be starred, so a starred
    # search must not fan out (it would only leak unfiltered hub rows).
    if starred_only:
        scope = "local"

    async def _local_search() -> SearchResponse:
        return await service.search(
            query=query,
            project_id=project_id,
            category=category,
            categories=categories,
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
            anchored_path=anchored_path,
            starred_only=starred_only,
        )

    try:
        if scope == "local":
            return await _local_search()

        db = getattr(service, "db", None)
        if db is None:
            # No local DB handle → federation unavailable; never answer a
            # hub-only request with local results.
            if scope == "hub":
                return SearchResponse(results=[], total=0, hub_status="skipped")
            result = await _local_search()
            result.hub_status = "skipped"
            return result

        # Load more: paginating a federated result set does not re-query the hub
        # (hub search has no stable offset) — continue locally only, no dup rows.
        if offset > 0:
            return await _local_search()

        from app.core.config import get_settings
        from app.core.services.federated_search import FederatedHubSearch

        # Merge single + multi category so hub results honor the same filter the
        # local query does (D8: unmerged → unfiltered hub rows leak in).
        merged_categories = categories or ([category] if category else None)
        federated = FederatedHubSearch(db, get_settings())
        return await federated.search(
            scope=scope,
            query=query,
            limit=limit,
            local_search=_local_search,
            categories=merged_categories,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search memories error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/search", response_model=SearchResponse)
async def search_memories(
    query: str,
    project_id: str = None,
    category: str = None,
    categories: Optional[List[str]] = Query(None),
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
    scope: str = "local",
    anchored_path: Optional[str] = Query(None, max_length=500),
    starred_only: bool = False,
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
        categories=categories,
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
        scope=scope,
        anchored_path=anchored_path,
        starred_only=starred_only,
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
        categories=body.categories,
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
        scope=body.scope,
        anchored_path=body.anchored_path,
        starred_only=body.starred_only,
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
            except Exception as e:
                logger.debug(f"Failed to serialize optimized context: {e}")
                context_dict = {"raw": str(optimized_context)}

        return ContextSearchResponse(
            search_results=search_response,
            context=context_dict,
        )
    except Exception as e:
        logger.error(f"Context-optimized search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
