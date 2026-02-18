"""
Memory statistics API routes.

Provides endpoints for retrieving memory statistics and project information.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends

from app.core.services.stats import StatsService
from app.core.schemas.responses import StatsResponse
from ...common.dependencies import get_stats_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Statistics"])


@router.get("/memories/stats", response_model=StatsResponse)
async def get_memory_stats(
    project_id: str = None,
    start_date: str = None,
    end_date: str = None,
    service: StatsService = Depends(get_stats_service),
) -> StatsResponse:
    """Get memory statistics"""
    try:
        stats = await service.get_overall_stats(
            project_id=project_id, start_date=start_date, end_date=end_date
        )
        return StatsResponse(**stats)
    except Exception as e:
        logger.error(f"Get stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects")
async def get_projects(service: StatsService = Depends(get_stats_service)):
    """
    Get project list with detailed statistics.

    Returns aggregated results from SQL GROUP BY for efficiency.
    Does not download all memories, only returns aggregated results.

    Returns:
        - projects: List of project details
        - total_projects: Total number of projects
        - total_memories: Total number of memories
    """
    try:
        projects = await service.get_projects_detail()

        total_memories = sum(p["memory_count"] for p in projects)

        return {
            "projects": projects,
            "total_projects": len(projects),
            "total_memories": total_memories,
            "avg_per_project": total_memories // len(projects)
            if len(projects) > 0
            else 0,
        }
    except Exception as e:
        logger.error(f"Get projects error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
