"""Project-level batch maintenance routes (enrich / improve / reconcile).

Enqueues async per-memory jobs — never a synchronous LLM loop over a whole
project. enrich/improve drain from ``maintenance_queue`` (relay worker's
``maintenance`` task); reconcile reuses the existing ``reconcile_queue`` +
reconcile worker. Improve results are proposals reviewed here before applying.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.redaction import redact_secrets
from app.core.services.maintenance import MAINTENANCE_OPERATIONS, MaintenanceService
from app.web.common.dependencies import get_database, get_memory_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])

_ALL_OPERATIONS = (*MAINTENANCE_OPERATIONS, "reconcile")


def get_maintenance_service(db=Depends(get_database)) -> MaintenanceService:
    return MaintenanceService(db)


class ProjectMaintenanceRequest(BaseModel):
    operations: List[str] = Field(min_length=1)
    force: bool = False


class ProjectMaintenanceResponse(BaseModel):
    project_id: str
    enqueued: dict = Field(default_factory=dict)
    skipped: dict = Field(default_factory=dict)
    total_memories: int = 0
    reconcile: Optional[dict] = None


@router.post("/projects/{project_id}", response_model=ProjectMaintenanceResponse)
async def run_project_maintenance(
    project_id: str,
    payload: ProjectMaintenanceRequest,
    service: MaintenanceService = Depends(get_maintenance_service),
    memory_service=Depends(get_memory_service),
) -> ProjectMaintenanceResponse:
    """Queue enrich/improve/reconcile jobs for every canonical memory in a
    project. Returns per-operation queued counts; results surface in the AI
    enrichment box (enrich), the Improve review queue (improve), and Curation
    (reconcile)."""

    ops = [op for op in payload.operations if op in _ALL_OPERATIONS]
    unknown = set(payload.operations) - set(_ALL_OPERATIONS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown operation(s): {', '.join(sorted(unknown))}",
        )
    if not ops:
        raise HTTPException(status_code=400, detail="no valid operations")

    try:
        queue_ops = [op for op in ops if op in MAINTENANCE_OPERATIONS]
        result = (
            await service.enqueue_project(
                project_id=project_id, operations=queue_ops, force=payload.force
            )
            if queue_ops
            else {"enqueued": {}, "skipped": {}, "total_memories": 0}
        )

        reconcile_result = None
        if "reconcile" in ops:
            reconcile_result = await memory_service.enqueue_project_reconcile(
                project_id
            )

        return ProjectMaintenanceResponse(
            project_id=project_id,
            enqueued=result.get("enqueued", {}),
            skipped=result.get("skipped", {}),
            total_memories=result.get("total_memories", 0),
            reconcile=reconcile_result,
        )
    except Exception as exc:
        logger.exception("Project maintenance enqueue failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/status")
async def maintenance_status(
    project_id: Optional[str] = None,
    service: MaintenanceService = Depends(get_maintenance_service),
) -> dict:
    """Queue status counts + pending improve-proposal count (for UI badges)."""
    return {
        "queue": await service.status_counts(),
        "pending_proposals": await service.count_refine_proposals(
            project_id=project_id
        ),
    }


class CancelRequest(BaseModel):
    operation: Optional[str] = None
    project_id: Optional[str] = None


@router.post("/cancel")
async def cancel_pending(
    payload: CancelRequest,
    service: MaintenanceService = Depends(get_maintenance_service),
) -> dict:
    """Cancel queued enrich/improve jobs (worker stops picking them up). A job
    already processing finishes its current LLM call. Optional operation /
    project_id narrow the scope."""
    if payload.operation and payload.operation not in MAINTENANCE_OPERATIONS:
        raise HTTPException(
            status_code=400, detail=f"unknown operation: {payload.operation}"
        )
    cancelled = await service.cancel_pending(
        operation=payload.operation, project_id=payload.project_id
    )
    return {"cancelled": cancelled}


@router.get("/proposals")
async def list_proposals(
    project_id: Optional[str] = None,
    limit: int = 50,
    service: MaintenanceService = Depends(get_maintenance_service),
) -> dict:
    """Pending improve (refine) proposals awaiting human review."""
    proposals = await service.list_refine_proposals(project_id=project_id, limit=limit)
    return {"proposals": proposals, "count": len(proposals)}


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: str,
    service: MaintenanceService = Depends(get_maintenance_service),
    memory_service=Depends(get_memory_service),
) -> dict:
    """Apply an improve proposal to its memory (secret-redacted), then close it."""
    proposal = await service.get_refine_proposal(proposal_id)
    if proposal is None or proposal.get("status") != "pending":
        raise HTTPException(status_code=404, detail="Pending proposal not found")

    memory = await memory_service.get(proposal["memory_id"])
    if memory is None:
        # Memory gone — retire the proposal instead of erroring.
        await service.reject_refine_proposal(proposal_id)
        raise HTTPException(status_code=409, detail="Memory no longer exists")
    # Refuse to overwrite a memory that changed since the proposal (staleness).
    if getattr(memory, "content_hash", None) != proposal.get("original_hash"):
        await service.reject_refine_proposal(proposal_id)
        raise HTTPException(
            status_code=409,
            detail="Memory changed since this proposal — rejected as stale.",
        )

    import json

    tags = None
    if proposal.get("proposed_tags"):
        try:
            tags = json.loads(proposal["proposed_tags"])
        except (json.JSONDecodeError, TypeError):
            tags = None
    content = redact_secrets(str(proposal["proposed_content"]))
    try:
        await memory_service.update(
            proposal["memory_id"],
            content=content,
            category=proposal.get("proposed_category"),
            tags=tags,
        )
    except Exception as exc:
        logger.exception("Proposal apply failed")
        raise HTTPException(status_code=500, detail=str(exc))

    await service.mark_proposal_approved(proposal_id)
    return {
        "proposal_id": proposal_id,
        "memory_id": proposal["memory_id"],
        "applied": True,
    }


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: str,
    service: MaintenanceService = Depends(get_maintenance_service),
) -> dict:
    ok = await service.reject_refine_proposal(proposal_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Pending proposal not found")
    return {"proposal_id": proposal_id, "rejected": True}
