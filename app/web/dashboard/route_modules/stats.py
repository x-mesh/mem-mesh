"""
Memory statistics API routes.

Provides endpoints for retrieving memory statistics and project information.
"""

import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends, Query

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


@router.get("/memories/daily-counts")
async def get_daily_counts(
    days: int = Query(default=7, ge=1, le=365),
    project_id: str = None,
    service: StatsService = Depends(get_stats_service),
):
    """Get daily memory creation counts for the last N days."""
    try:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=days - 1)).strftime("%Y-%m-%d")

        date_counts = await service.get_date_range_stats(
            start_date=start_date,
            end_date=end_date,
            project_id=project_id,
        )

        # Fill in missing dates with 0
        result = []
        current = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            result.append({"date": date_str, "count": date_counts.get(date_str, 0)})
            current += timedelta(days=1)

        return {"daily_counts": result, "days": days, "start_date": start_date, "end_date": end_date}
    except Exception as e:
        logger.error(f"Get daily counts error: {e}")
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
