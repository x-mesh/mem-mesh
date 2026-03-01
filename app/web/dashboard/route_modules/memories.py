"""
Memory CRUD API routes.

Provides endpoints for creating, reading, updating, and deleting memories.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.schemas.requests import AddParams, UpdateParams
from app.core.schemas.responses import (
    AddResponse,
    ContextResponse,
    DeleteResponse,
    UpdateResponse,
)
from app.core.services.context import ContextNotFoundError, ContextService
from app.core.services.memory import MemoryNotFoundError, MemoryService

from ...common.dependencies import (
    get_context_service,
    get_memory_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Memories"])


@router.post("/memories", response_model=AddResponse)
async def add_memory(
    params: AddParams, service: MemoryService = Depends(get_memory_service)
) -> AddResponse:
    """Add a new memory"""
    try:
        result = await service.create(
            content=params.content,
            project_id=params.project_id,
            category=params.category,
            source=params.source or "api",
            tags=params.tags,
        )

        # WebSocket real-time notification
        try:
            from ...websocket.realtime import notifier

            memory = await service.get(result.id)
            if memory:
                memory_data = {
                    "id": memory.id,
                    "content": memory.content,
                    "project_id": memory.project_id,
                    "category": memory.category,
                    "tags": json.loads(memory.tags) if memory.tags else [],
                    "source": memory.source,
                    "created_at": memory.created_at,
                    "updated_at": memory.updated_at,
                }
                await notifier.notify_memory_created(memory_data)
        except Exception as e:
            logger.warning(f"Failed to send WebSocket notification: {e}")

        return result
    except Exception as e:
        logger.error(f"Add memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/{memory_id}")
async def get_memory(
    memory_id: str, service: MemoryService = Depends(get_memory_service)
):
    """Get a single memory by ID"""
    try:
        memory = await service.get(memory_id)
        if memory is None:
            raise HTTPException(status_code=404, detail="Memory not found")

        return {
            "id": memory.id,
            "content": memory.content,
            "project_id": memory.project_id,
            "category": memory.category,
            "tags": memory.tags,
            "source": memory.source,
            "created_at": memory.created_at,
            "updated_at": memory.updated_at,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/{memory_id}/context", response_model=ContextResponse)
async def get_memory_context(
    memory_id: str,
    depth: int = 2,
    project_id: str = None,
    service: ContextService = Depends(get_context_service),
) -> ContextResponse:
    """Get context around a specific memory"""
    try:
        return await service.get_context(
            memory_id=memory_id, depth=depth, project_id=project_id
        )
    except ContextNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Get context error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/memories/{memory_id}", response_model=UpdateResponse)
async def update_memory(
    memory_id: str,
    params: UpdateParams,
    service: MemoryService = Depends(get_memory_service),
) -> UpdateResponse:
    """Update an existing memory"""
    try:
        result = await service.update(
            memory_id=memory_id,
            content=params.content,
            category=params.category,
            tags=params.tags,
        )

        # WebSocket real-time notification
        try:
            from ...websocket.realtime import notifier

            memory = await service.get(memory_id)
            if memory:
                memory_data = {
                    "id": memory.id,
                    "content": memory.content,
                    "project_id": memory.project_id,
                    "category": memory.category,
                    "tags": json.loads(memory.tags) if memory.tags else [],
                    "source": memory.source,
                    "created_at": memory.created_at,
                    "updated_at": memory.updated_at,
                }
                await notifier.notify_memory_updated(memory_id, memory_data)
        except Exception as e:
            logger.warning(f"Failed to send WebSocket notification: {e}")

        return result
    except MemoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Update memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/memories/{memory_id}", response_model=DeleteResponse)
async def delete_memory(
    memory_id: str, service: MemoryService = Depends(get_memory_service)
) -> DeleteResponse:
    """Delete a memory"""
    try:
        # Get memory info before deletion (for project_id)
        try:
            memory_info = await service.get_by_id(memory_id)
            project_id = memory_info.project_id if memory_info else None
        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            project_id = None

        result = await service.delete(memory_id)

        # WebSocket real-time notification
        try:
            from ...websocket.realtime import notifier

            await notifier.notify_memory_deleted(memory_id, project_id)
        except Exception as e:
            logger.warning(f"Failed to send WebSocket notification: {e}")

        return result
    except MemoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Delete memory error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
