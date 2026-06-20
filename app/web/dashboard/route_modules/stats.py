"""
Memory statistics API routes.

Provides endpoints for retrieving memory statistics and project information.
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.schemas.responses import StatsResponse
from app.core.services.stats import StatsService

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

        return {
            "daily_counts": result,
            "days": days,
            "start_date": start_date,
            "end_date": end_date,
        }
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
            "avg_per_project": (
                total_memories // len(projects) if len(projects) > 0 else 0
            ),
        }
    except Exception as e:
        logger.error(f"Get projects error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Analytics extensions =====


@router.get("/analytics/productivity")
async def get_productivity_analytics(
    project_id: str = None,
    days: int = Query(default=7, ge=1, le=365),
    weeks: int = Query(default=8, ge=1, le=52),
    service: StatsService = Depends(get_stats_service),
):
    """Work-tracking productivity: pin/session throughput and lead time."""
    try:
        pin_stats = await service.get_pin_stats(project_id=project_id)
        session_stats = await service.get_session_stats(project_id=project_id)
        daily = await service.get_daily_pin_completions(
            project_id=project_id, days=days
        )
        weekly = await service.get_weekly_pin_completions(
            project_id=project_id, weeks=weeks
        )
        return {
            "pins": pin_stats,
            "sessions": session_stats,
            "daily_completions": daily,
            "weekly_completions": weekly,
        }
    except Exception as e:
        logger.error(f"Get productivity analytics error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/token-economics")
async def get_token_economics_analytics(
    project_id: str = None,
    start_date: str = None,
    end_date: str = None,
    service: StatsService = Depends(get_stats_service),
):
    """Token-savings economics aggregated from token_usage."""
    try:
        return await service.get_token_economics(
            project_id=project_id, start_date=start_date, end_date=end_date
        )
    except Exception as e:
        logger.error(f"Get token economics error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/kb-health")
async def get_kb_health_analytics(
    project_id: str = None,
    service: StatsService = Depends(get_stats_service),
):
    """Knowledge-base health: age distribution, stale/orphan ratio, graph density."""
    try:
        return await service.get_kb_health(project_id=project_id)
    except Exception as e:
        logger.error(f"Get KB health error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/recall")
async def get_recall_analytics(
    project_id: str = None,
    limit: int = Query(default=10, ge=1, le=50),
    service: StatsService = Depends(get_stats_service),
):
    """Recall/usage: most-recalled memories, dead-memory ratio, access distribution."""
    try:
        return await service.get_recall_stats(project_id=project_id, limit=limit)
    except Exception as e:
        logger.error(f"Get recall analytics error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/activity-trend")
async def get_activity_trend_analytics(
    project_id: str = None,
    days: int = Query(default=30, ge=1, le=365),
    dimension: str = Query(default="client"),
    service: StatsService = Depends(get_stats_service),
):
    """Daily activity broken down by client or source (stacked time series)."""
    try:
        return await service.get_activity_trend(
            project_id=project_id, days=days, dimension=dimension
        )
    except Exception as e:
        logger.error(f"Get activity trend error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
