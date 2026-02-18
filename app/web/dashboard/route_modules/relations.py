"""
Memory Relations API 라우트.
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends

from app.core.services.relation import (
    RelationService,
    RelationNotFoundError,
    MemoryNotFoundError,
)
from app.core.schemas.relations import (
    Relation,
    RelationCreate,
    RelationUpdate,
    RelationType,
    RelationWithMemory,
    RelationGraph,
)
from app.web.common.dependencies import get_relation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/relations", tags=["Relations"])


@router.post("", response_model=Relation)
async def create_relation(
    data: RelationCreate,
    service: RelationService = Depends(get_relation_service),
):
    """메모리 관계 생성"""
    try:
        relation = await service.create_relation(data)
        return relation
    except MemoryNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Create relation error: {e}")
        # UNIQUE constraint 위반 처리
        if "UNIQUE constraint" in str(e):
            raise HTTPException(
                status_code=409, detail="Relation already exists"
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{relation_id}", response_model=Relation)
async def get_relation(
    relation_id: str,
    service: RelationService = Depends(get_relation_service),
):
    """관계 조회"""
    relation = await service.get_relation(relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="Relation not found")
    return relation


@router.put("/{relation_id}", response_model=Relation)
async def update_relation(
    relation_id: str,
    data: RelationUpdate,
    service: RelationService = Depends(get_relation_service),
):
    """관계 수정"""
    try:
        relation = await service.update_relation(relation_id, data)
        return relation
    except RelationNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Update relation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{relation_id}")
async def delete_relation(
    relation_id: str,
    service: RelationService = Depends(get_relation_service),
):
    """관계 삭제"""
    success = await service.delete_relation(relation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Relation not found")
    return {"success": True, "deleted_id": relation_id}


@router.get("/memory/{memory_id}", response_model=List[RelationWithMemory])
async def get_memory_relations(
    memory_id: str,
    relation_type: Optional[RelationType] = None,
    direction: str = "both",
    min_strength: float = 0.0,
    limit: int = 50,
    service: RelationService = Depends(get_relation_service),
):
    """특정 메모리의 관계 목록 조회"""
    if direction not in ("outgoing", "incoming", "both"):
        raise HTTPException(
            status_code=400,
            detail="direction must be 'outgoing', 'incoming', or 'both'",
        )

    relations = await service.get_relations_for_memory(
        memory_id=memory_id,
        relation_type=relation_type,
        direction=direction,
        min_strength=min_strength,
        limit=limit,
    )
    return relations


@router.get("/graph/{memory_id}", response_model=RelationGraph)
async def get_relation_graph(
    memory_id: str,
    depth: int = 2,
    min_strength: float = 0.0,
    service: RelationService = Depends(get_relation_service),
):
    """관계 그래프 조회"""
    if depth < 1 or depth > 5:
        raise HTTPException(
            status_code=400, detail="depth must be between 1 and 5"
        )

    graph = await service.get_relation_graph(
        memory_id=memory_id,
        depth=depth,
        min_strength=min_strength,
    )
    return graph
