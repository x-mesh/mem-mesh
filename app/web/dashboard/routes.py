"""
Dashboard REST API router.

Provides API endpoints for memory management, search, statistics, embedding management, etc.
"""

import json
import logging
from pathlib import Path
from typing import Union

from fastapi import APIRouter, Depends, HTTPException

from app.core.schemas.pins import PinCreate, PinUpdate
from app.core.schemas.projects import ProjectUpdate
from app.core.schemas.requests import RuleUpdateParams
from app.core.services.embedding_manager import EmbeddingManagerService
from app.core.services.pin import (
    InvalidStatusTransitionError,
    PinNotFoundError,
    PinService,
)
from app.core.services.project import ProjectService
from app.core.services.session import NoActiveSessionError, SessionService
from app.core.services.stats import StatsService

from ..common.dependencies import (
    get_embedding_manager,
    get_embedding_service,
    get_pin_service,
    get_project_service,
    get_session_service,
    get_stats_service,
)
from ..websocket.realtime import RealtimeNotifier
from .route_modules import router as modular_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Dashboard API"])

router.include_router(modular_router)

_notifier = RealtimeNotifier()


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


@router.post("/internal/notify")
async def internal_notify(payload: dict) -> dict:
    """stdio MCP -> WebSocket broadcast bridge.

    stdio MCP 서버가 HttpNotifier를 통해 이 엔드포인트로 이벤트를 보내면,
    웹서버의 RealtimeNotifier가 WebSocket으로 브로드캐스트합니다.
    """
    event_type = payload.get("type")
    data = payload.get("data", {})

    if event_type == "memory_created":
        await _notifier.notify_memory_created(data.get("memory", {}))
    elif event_type == "memory_updated":
        await _notifier.notify_memory_updated(
            data.get("memory_id", ""), data.get("memory", {})
        )
    elif event_type == "memory_deleted":
        await _notifier.notify_memory_deleted(
            data.get("memory_id", ""), data.get("project_id")
        )
    elif event_type == "pin_created":
        await _notifier.notify_pin_created(data.get("pin", {}))
    elif event_type == "pin_completed":
        await _notifier.notify_pin_completed(data.get("pin", {}))
    elif event_type == "pin_promoted":
        await _notifier.notify_pin_promoted(
            data.get("pin_id", ""), data.get("memory_id", "")
        )
    else:
        return {"status": "ignored", "reason": f"unknown event type: {event_type}"}

    return {"status": "ok", "type": event_type}


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
    """Health check endpoint (always 200, even during model loading)"""
    from datetime import datetime, timezone

    from ..lifespan import get_services

    services = get_services()
    es = services.get("embedding_service")
    db = services.get("db")
    embedding_ready = es.is_ready if es else False
    embedding_status = es.status if es else "not_initialized"

    result = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "embedding_ready": embedding_ready,
        "embedding_status": embedding_status,
    }

    # 모델 일관성 체크 (DB vs settings)
    if db and es:
        try:
            model_check = await db.check_embedding_model_consistency(
                current_model=es.model_name,
                current_dim=es.dimension,
            )
            if model_check["needs_migration"]:
                result["needs_migration"] = True
                result["migration_info"] = {
                    "stored_model": model_check["stored_model"],
                    "stored_dim": model_check["stored_dim"],
                    "current_model": model_check["current_model"],
                    "current_dim": model_check["current_dim"],
                    "message": model_check["message"],
                }
        except Exception:
            pass

    return result


@router.get("/system/info")
async def system_info():
    """Detailed system information for settings page"""
    import os
    import platform
    import sqlite3
    import sys
    from datetime import datetime, timezone

    from app.core.version import __VERSION__, MCP_PROTOCOL_VERSION

    # DB file size
    db_path = os.environ.get("MEM_MESH_DB_PATH", "data/mem_mesh.db")
    db_size = 0
    try:
        if os.path.exists(db_path):
            db_size = os.path.getsize(db_path)
    except OSError:
        pass

    return {
        "version": __VERSION__,
        "mcp_protocol": MCP_PROTOCOL_VERSION,
        "python_version": sys.version.split()[0],
        "sqlite_version": sqlite3.sqlite_version,
        "platform": platform.system(),
        "platform_version": platform.release(),
        "db_path": db_path,
        "db_size_bytes": db_size,
        "pid": os.getpid(),
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


@router.get("/embeddings/models")
async def list_available_models():
    """List available embedding models for onboarding selection."""
    from app.core.embeddings.service import AVAILABLE_MODELS, is_model_cached

    models = []
    for m in AVAILABLE_MODELS:
        models.append({**m, "cached": is_model_cached(m["name"])})
    return {"models": models}


@router.get("/embeddings/loading-status")
async def get_embedding_loading_status(
    embedding_service=Depends(get_embedding_service),
):
    """Get current model loading/download status for onboarding progress."""
    return embedding_service.get_status_info()


@router.post("/embeddings/select")
async def select_embedding_model(
    body: dict,
    embedding_service=Depends(get_embedding_service),
):
    """Select and start downloading an embedding model.

    Body: {"model": "intfloat/multilingual-e5-large"}
    """
    model_name = body.get("model")
    if not model_name:
        raise HTTPException(status_code=400, detail="model field is required")

    from app.core.embeddings.service import AVAILABLE_MODELS, MODEL_ALIASES

    # 유효한 모델인지 확인
    resolved = MODEL_ALIASES.get(model_name, model_name)
    valid_names = [m["name"] for m in AVAILABLE_MODELS]
    if resolved not in valid_names:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid model. Choose from: {valid_names}",
        )

    # 이미 로딩 중이면 현재 상태 반환
    if embedding_service.status in ("downloading", "loading"):
        return embedding_service.get_status_info()

    # 모델 변경 + DB에 선택 저장 + 백그라운드 다운로드 시작
    embedding_service.switch_model(resolved)

    # DB에 선택한 모델 저장
    # target_embedding_model: 사용자가 선택한 목표 모델 (재시작 시 자동 로드용)
    # embedding_model: 실제 데이터의 모델 (마이그레이션 완료 후 업데이트)
    from ..lifespan import get_services
    services = get_services()
    db = services.get("db")
    if db:
        try:
            from app.core.embeddings.service import MODEL_DIMENSIONS
            dim = MODEL_DIMENSIONS.get(resolved, 384)

            # 항상 target 저장 (재시작 시 이 모델로 로드)
            await db._migrator.set_embedding_metadata("target_embedding_model", resolved)
            await db._migrator.set_embedding_metadata("target_embedding_dimension", str(dim))

            # 기존 메모리가 없으면 embedding_model도 바로 업데이트 (fresh DB)
            cursor = await db.execute("SELECT COUNT(*) as count FROM memories")
            memory_count = cursor.fetchone()["count"]
            if memory_count == 0:
                await db._migrator.set_embedding_metadata("embedding_model", resolved)
                await db._migrator.set_embedding_metadata("embedding_dimension", str(dim))
        except Exception as e:
            logger.warning(f"Failed to persist model selection: {e}")

    def _on_progress(progress: float, status: str) -> None:
        try:
            from ..websocket.realtime import notifier
            import asyncio

            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(
                asyncio.ensure_future,
                notifier.broadcast(
                    "model_download",
                    {"progress": progress, "status": status, "model": resolved},
                ),
            )
        except Exception:
            pass

    embedding_service.load_model_background(on_progress=_on_progress)
    return embedding_service.get_status_info()


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
    ide_session_id: str = None,
    client_type: str = None,
    session_service: SessionService = Depends(get_session_service),
):
    """
    Load last session context.

    Args:
        project_id: Project ID
        expand: If True, return full pin content; if False, return summary only
        limit: Number of pins to return (default 10)
        user_id: User ID (optional)
        ide_session_id: IDE native session ID (optional, for session correlation)
        client_type: IDE/tool type (optional, e.g. "claude-ai", "Cursor")
    """
    try:
        # 1. 먼저 resume로 기존 맥락 로드 (cross-session 포함)
        context = await session_service.resume_last_session(
            project_id=project_id, user_id=user_id, expand=expand, limit=limit
        )

        # 2. IDE session_id가 있으면 활성 세션에 연결 (resume 이후)
        if ide_session_id:
            await session_service.get_or_create_active_session(
                project_id=project_id,
                user_id=user_id,
                ide_session_id=ide_session_id,
                client_type=client_type,
            )

        if context is None:
            return {
                "status": "no_session",
                "message": f"No session found for project: {project_id}",
            }
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


@router.post("/work/sessions/end-by-project/{project_id}")
async def end_session_by_project(
    project_id: str,
    summary: str = None,
    session_service: SessionService = Depends(get_session_service),
):
    """End the most recent active session for a project.

    Used by PreCompact/SessionEnd hooks which only know project_id.
    """
    try:
        session = await session_service.end_session_by_project(project_id, summary)
        if not session:
            return {
                "status": "no_active_session",
                "message": f"No active session found for project: {project_id}",
            }
        return session.dict()
    except Exception as e:
        logger.error(f"End session by project error: {e}")
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

        result = created_pin.dict()
        try:
            await _notifier.notify_pin_created(result)
        except Exception:
            pass
        return result
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

        try:
            await _notifier.notify_pin_completed(result)
        except Exception:
            pass
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
        memory_id = result.get("memory_id", "")
        if memory_id:
            try:
                await _notifier.notify_pin_promoted(pin_id, memory_id)
            except Exception:
                pass
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
