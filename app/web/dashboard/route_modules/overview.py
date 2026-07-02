"""Project overview routes — LLM narrative summary of a project's recent memories.

GET returns the cached overview (+ a ``stale`` flag); POST regenerates it via the
chat LLM. One LLM call per generate (a batch summary, not a per-item loop), so
the synchronous POST is bounded.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.errors import ChatError
from app.core.services.overview import OverviewScheduler, OverviewService
from app.web.common.dependencies import get_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Overview"])


def get_overview_service(db=Depends(get_database)) -> OverviewService:
    return OverviewService(db)


def get_overview_scheduler(db=Depends(get_database)) -> OverviewScheduler:
    return OverviewScheduler(db)


def get_chat_service_dep(db=Depends(get_database)):
    from app.core.services.chat import ChatService

    return ChatService(db)


@router.get("/{project_id}/overview")
async def get_project_overview(
    project_id: str,
    service: OverviewService = Depends(get_overview_service),
) -> dict:
    """Cached overview for a project, or ``{overview: null}`` if never generated.
    ``stale`` is true when the project's memories changed since generation."""
    cached = await service.get_cached(project_id)
    if cached is None:
        return {"project_id": project_id, "overview": None, "stale": False}
    return {"project_id": project_id, **cached}


@router.post("/{project_id}/overview")
async def generate_project_overview(
    project_id: str,
    service: OverviewService = Depends(get_overview_service),
    chat_service=Depends(get_chat_service_dep),
) -> dict:
    """(Re)generate the overview from the project's recent memories."""
    settings = get_settings()
    if not await chat_service.is_configured(settings):
        raise HTTPException(
            status_code=400, detail="Chat assistant LLM is not configured"
        )
    try:
        result = await service.generate(
            project_id=project_id, chat_service=chat_service, settings=settings
        )
    except ChatError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc))
    except Exception as exc:
        logger.exception("Project overview generation failed")
        raise HTTPException(status_code=500, detail=str(exc))
    if result.get("empty"):
        raise HTTPException(
            status_code=404, detail="Project has no memories to summarize"
        )
    return {"project_id": project_id, **result}


# ── Scheduled auto-refresh (opt-in per project) ──────────────────────────────


class OverviewScheduleRequest(BaseModel):
    enabled: bool


@router.get("/overview/schedules")
async def list_overview_schedules(
    scheduler: OverviewScheduler = Depends(get_overview_scheduler),
) -> dict:
    """All projects with scheduled overview refresh configured (for card toggles)."""
    return {"schedules": await scheduler.list_schedules()}


@router.put("/{project_id}/overview/schedule")
async def set_overview_schedule(
    project_id: str,
    payload: OverviewScheduleRequest,
    scheduler: OverviewScheduler = Depends(get_overview_scheduler),
) -> dict:
    """Enable/disable daily(ish) auto-refresh of this project's overview. When
    on, the relay worker's ``overview`` task regenerates it at most once per
    configured interval, and only when the project had recent memory activity."""
    return await scheduler.set_enabled(project_id, payload.enabled)
