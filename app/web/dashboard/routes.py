"""
Dashboard REST API router.

Provides API endpoints for memory management, search, statistics, embedding management, etc.
"""

import json
import logging
from pathlib import Path
from typing import Union
from fastapi import APIRouter, HTTPException, Depends

from app.core.services.stats import StatsService
from app.core.services.embedding_manager import EmbeddingManagerService
from app.core.services.project import ProjectService
from app.core.services.session import SessionService, NoActiveSessionError
from app.core.services.pin import (
    PinService,
    PinNotFoundError,
    InvalidStatusTransitionError,
)
from app.core.schemas.requests import RuleUpdateParams
from app.core.schemas.pins import PinCreate, PinUpdate
from app.core.schemas.projects import ProjectUpdate
from ..common.dependencies import (
    get_stats_service,
    get_embedding_manager,
    get_project_service,
    get_session_service,
    get_pin_service,
)
from .route_modules import router as modular_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Dashboard API"])

router.include_router(modular_router)


def _rules_root() -> Path:
    return Path(__file__).resolve().parents[3] / "docs" / "rules"


def _rules_index_path() -> Path:
    return _rules_root() / "index.json"


def _load_rules_index() -> dict:
    index_path = _rules_index_path()
    if not index_path.exists():
        raise FileNotFoundError("rules index.json not found")
    return json.loads(index_path.read_text(encoding="utf-8"))


def _get_rule_entry(rule_id: str) -> dict:
    index_data = _load_rules_index()
    for rule in index_data.get("rules", []):
        if rule.get("id") == rule_id:
            return rule
    raise KeyError(f"Rule not found: {rule_id}")


def _resolve_rule_path(rule_entry: dict) -> Path:
    rule_path = rule_entry.get("path")
    if not rule_path:
        raise ValueError("Invalid rule entry: missing path")
    base = _rules_root().resolve()
    candidate = (Path(__file__).resolve().parents[3] / rule_path).resolve()
    if not str(candidate).startswith(str(base)):
        raise ValueError("Invalid rule path")
    return candidate


@router.get("/")
async def api_root():
    """API root endpoint"""
    from app.core.version import __VERSION__, MCP_PROTOCOL_VERSION
    
    return {
        "name": "mem-mesh",
        "description": "Central memory server with vector search",
        "version": __VERSION__,
        "mcp_protocol": MCP_PROTOCOL_VERSION,
        "status": "running",
    }


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    from datetime import datetime, timezone
    
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/rules")
async def list_rules():
    """List all rules"""
    try:
        index_data = _load_rules_index()
        rules = index_data.get("rules", [])
        return {
            "version": index_data.get("version", 1),
            "rules": [
                {
                    "id": rule.get("id"),
                    "title": rule.get("title"),
                    "kind": rule.get("kind"),
                    "tags": rule.get("tags", []),
                }
                for rule in rules
            ],
        }
    except Exception as e:
        logger.error(f"List rules error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: str):
    """Get a single rule"""
    try:
        entry = _get_rule_entry(rule_id)
        rule_path = _resolve_rule_path(entry)
        if not rule_path.exists():
            raise HTTPException(status_code=404, detail="Rule file not found")
        content = rule_path.read_text(encoding="utf-8")
        return {"rule": entry, "content": content}
    except KeyError:
        raise HTTPException(status_code=404, detail="Rule not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get rule error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: str, params: RuleUpdateParams):
    """Update a rule"""
    try:
        entry = _get_rule_entry(rule_id)
        rule_path = _resolve_rule_path(entry)
        if not rule_path.exists():
            raise HTTPException(status_code=404, detail="Rule file not found")
        rule_path.write_text(params.content, encoding="utf-8")
        return {"status": "updated", "rule_id": rule_id, "bytes": len(params.content)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Rule not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update rule error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Embedding Management API =====


@router.get("/embeddings/status")
async def get_embedding_status(
    manager: EmbeddingManagerService = Depends(get_embedding_manager),
):
    """
    Get embedding model status.

    Returns:
        - stored_model: Model name stored in DB
        - stored_dimension: Dimension stored in DB
        - current_model: Currently configured model name
        - current_dimension: Currently configured dimension
        - total_memories: Total number of memories
        - vector_count: Number of records in vector table
        - needs_migration: Whether migration is needed
        - migration_in_progress: Whether migration is in progress
    """
    try:
        status = await manager.get_status()
        return status
    except Exception as e:
        logger.error(f"Get embedding status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/embeddings/migrate")
async def start_embedding_migration(
    force: bool = False,
    batch_size: int = 100,
    manager: EmbeddingManagerService = Depends(get_embedding_manager),
):
    """
    Start embedding migration.

    Args:
        force: Force re-embedding even if model is the same
        batch_size: Batch size (default: 100)

    Returns:
        Migration result or progress
    """
    try:
        result = await manager.start_migration(force=force, batch_size=batch_size)
        return result
    except Exception as e:
        logger.error(f"Start migration error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/embeddings/migration/progress")
async def get_migration_progress(
    manager: EmbeddingManagerService = Depends(get_embedding_manager),
):
    """Get migration progress"""
    try:
        progress = manager.get_migration_progress()
        return progress
    except Exception as e:
        logger.error(f"Get migration progress error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Work Tracking API (Pins, Sessions, Projects) =====


@router.get("/work/projects")
async def list_work_projects(service: ProjectService = Depends(get_project_service)):
    """List work tracking projects with statistics"""
    try:
        projects = await service.list_projects_with_stats()
        return {"projects": [p.dict() for p in projects], "total": len(projects)}
    except Exception as e:
        logger.error(f"List work projects error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/work/projects/{project_id}")
async def get_work_project(
    project_id: str, service: ProjectService = Depends(get_project_service)
):
    """Get a single project"""
    try:
        project = await service.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project.dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get work project error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/work/projects/{project_id}")
async def create_or_get_work_project(
    project_id: str, service: ProjectService = Depends(get_project_service)
):
    """Create or get a project"""
    try:
        project = await service.get_or_create_project(project_id)
        return project.dict()
    except Exception as e:
        logger.error(f"Create work project error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/work/projects/{project_id}")
async def update_work_project(
    project_id: str,
    update: ProjectUpdate,
    service: ProjectService = Depends(get_project_service),
):
    """Update a project"""
    try:
        project = await service.update_project(project_id, update)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project.dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update work project error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/work/projects/{project_id}/stats")
async def get_work_project_stats(
    project_id: str, stats_service: StatsService = Depends(get_stats_service)
):
    """Get project statistics (Pin/Session stats)"""
    try:
        pin_stats = await stats_service.get_pin_stats(project_id=project_id)
        session_stats = await stats_service.get_session_stats(project_id=project_id)
        daily_completions = await stats_service.get_daily_pin_completions(
            project_id=project_id
        )

        return {
            "project_id": project_id,
            "pins": pin_stats,
            "sessions": session_stats,
            "daily_completions": daily_completions,
        }
    except Exception as e:
        logger.error(f"Get work project stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Session API =====


@router.get("/work/sessions/resume/{project_id}")
async def resume_session(
    project_id: str,
    expand: Union[bool, str] = False,
    limit: int = 10,
    user_id: str = None,
    session_service: SessionService = Depends(get_session_service),
):
    """
    Load last session context.

    Args:
        project_id: Project ID
        expand: If True, return full pin content; if False, return summary only
        limit: Number of pins to return (default 10)
        user_id: User ID (optional)
    """
    try:
        context = await session_service.resume_last_session(
            project_id=project_id, user_id=user_id, expand=expand, limit=limit
        )
        return context.dict()
    except NoActiveSessionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Resume session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/work/sessions/{session_id}/end")
async def end_session(
    session_id: str,
    summary: str = None,
    session_service: SessionService = Depends(get_session_service),
):
    """End a session"""
    try:
        session = await session_service.end_session(session_id, summary)
        return session.dict()
    except Exception as e:
        logger.error(f"End session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/work/sessions")
async def list_sessions(
    project_id: str = None,
    user_id: str = None,
    status: str = None,
    limit: int = 20,
    session_service: SessionService = Depends(get_session_service),
):
    """List sessions"""
    try:
        sessions = await session_service.list_sessions(
            project_id=project_id, user_id=user_id, status=status, limit=limit
        )
        return {"sessions": [s.dict() for s in sessions], "total": len(sessions)}
    except Exception as e:
        logger.error(f"List sessions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Pin API =====


@router.post("/work/pins")
async def create_pin(
    pin: PinCreate, pin_service: PinService = Depends(get_pin_service)
):
    """
    Create a new Pin.

    Session is automatically created if it doesn't exist.
    """
    try:
        created_pin = await pin_service.create_pin(
            project_id=pin.project_id,
            content=pin.content,
            importance=pin.importance,
            tags=pin.tags,
            user_id=pin.user_id,
        )

        return created_pin.dict()
    except Exception as e:
        logger.error(f"Create pin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/work/pins")
async def list_pins(
    project_id: str = None,
    session_id: str = None,
    user_id: str = None,
    status: str = None,
    limit: int = 10,
    order_by_importance: bool = True,
    pin_service: PinService = Depends(get_pin_service),
):
    """List pins"""
    try:
        pins = await pin_service.get_pins(
            project_id=project_id,
            session_id=session_id,
            user_id=user_id,
            status=status,
            limit=limit,
            order_by_importance=order_by_importance,
        )
        return {"pins": [p.dict() for p in pins], "total": len(pins)}
    except Exception as e:
        logger.error(f"List pins error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/work/pins/{pin_id}")
async def get_pin(pin_id: str, pin_service: PinService = Depends(get_pin_service)):
    """Get a single pin"""
    try:
        pin = await pin_service.get_pin(pin_id)
        if pin is None:
            raise HTTPException(status_code=404, detail="Pin not found")
        return pin.dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get pin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/work/pins/{pin_id}")
async def update_pin(
    pin_id: str, update: PinUpdate, pin_service: PinService = Depends(get_pin_service)
):
    """Update a pin"""
    try:
        pin = await pin_service.update_pin(pin_id, update)
        return pin.dict()
    except PinNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidStatusTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Update pin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/work/pins/{pin_id}")
async def patch_pin(
    pin_id: str, update: PinUpdate, pin_service: PinService = Depends(get_pin_service)
):
    """Partial update a pin (for drag and drop)"""
    try:
        pin = await pin_service.update_pin(pin_id, update)
        return pin.dict()
    except PinNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidStatusTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Patch pin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/work/pins/{pin_id}/complete")
async def complete_pin(pin_id: str, pin_service: PinService = Depends(get_pin_service)):
    """
    Complete a pin.

    If importance >= 4, includes a suggestion to promote to Memory.
    """
    try:
        pin = await pin_service.complete_pin(pin_id)
        result = pin.dict()

        if pin.importance >= 4:
            result["suggest_promotion"] = True
            result["promotion_message"] = (
                f"This Pin has importance {pin.importance}. Would you like to promote it to Memory?"
            )

        return result
    except PinNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidStatusTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Complete pin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/work/pins/{pin_id}/promote")
async def promote_pin(pin_id: str, pin_service: PinService = Depends(get_pin_service)):
    """
    Promote a Pin to Memory.

    Copies content and tags, and generates embedding.
    """
    try:
        result = await pin_service.promote_to_memory(pin_id)
        return result
    except PinNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Promote pin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/work/pins/{pin_id}")
async def delete_pin(pin_id: str, pin_service: PinService = Depends(get_pin_service)):
    """Delete a pin"""
    try:
        success = await pin_service.delete_pin(pin_id)
        return {"success": success, "deleted_id": pin_id}
    except PinNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Delete pin error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
