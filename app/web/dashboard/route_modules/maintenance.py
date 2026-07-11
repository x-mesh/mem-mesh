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


class AutoEnrichRequest(BaseModel):
    enabled: bool
    operations: Optional[List[str]] = None


class AutoEnrichResponse(BaseModel):
    project_id: str
    # Whether auto-enrich actually applies to this project *right now* — the
    # explicit row AND the global scope together. Under scope="all" a project
    # with no row is enabled, so reporting the row alone would tell the UI the
    # opposite of what the server will do.
    enabled: bool = False
    operations: List[str] = Field(default_factory=lambda: ["enrich"])
    # Whether a Worker LLM is configured — the hard prerequisite for auto-enrich
    # to actually run (UI shows a "configure Worker LLM" hint when False).
    llm_configured: bool = False
    last_sweep_at: Optional[str] = None
    # Global scope: "subscribed" (per-project opt-in) or "all" (opt-out). Lets
    # the UI label the toggle correctly in each mode.
    scope: str = "subscribed"


async def _auto_enrich_response(
    service: MaintenanceService, project_id: str
) -> AutoEnrichResponse:
    from app.core.config import get_settings
    from app.core.services.llm_resolver import resolve_service_llm

    sub = await service.get_auto_enrich(project_id)
    scope = await service.get_auto_enrich_scope()
    llm = await resolve_service_llm(service.db, get_settings(), "relay")
    if scope == "all":
        # No row = in scope; an explicit row still wins (opt-out).
        enabled = sub.enabled if sub is not None else True
    else:
        enabled = bool(sub and sub.enabled)
    return AutoEnrichResponse(
        project_id=project_id,
        enabled=enabled,
        operations=(sub.operations if sub else ["enrich"]),
        llm_configured=bool(llm.get("api_key")),
        last_sweep_at=(sub.last_sweep_at if sub else None),
        scope=scope,
    )


@router.get("/auto-enrich/{project_id}", response_model=AutoEnrichResponse)
async def get_auto_enrich(
    project_id: str,
    service: MaintenanceService = Depends(get_maintenance_service),
) -> AutoEnrichResponse:
    """Current per-project auto-enrich opt-in + whether a Worker LLM is wired."""
    try:
        return await _auto_enrich_response(service, project_id)
    except Exception as exc:
        logger.exception("auto-enrich status failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/auto-enrich/{project_id}", response_model=AutoEnrichResponse)
async def set_auto_enrich(
    project_id: str,
    payload: AutoEnrichRequest,
    service: MaintenanceService = Depends(get_maintenance_service),
) -> AutoEnrichResponse:
    """Enable/disable continuous auto-enrich for a project."""
    ops = payload.operations
    if ops is not None:
        unknown = set(ops) - set(MAINTENANCE_OPERATIONS)
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"unknown operation(s): {', '.join(sorted(unknown))}",
            )
    try:
        await service.set_auto_enrich(
            project_id, enabled=payload.enabled, operations=ops
        )
        return await _auto_enrich_response(service, project_id)
    except Exception as exc:
        logger.exception("auto-enrich update failed")
        raise HTTPException(status_code=500, detail=str(exc))


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


async def _reconcile_status_counts(db, project_id: Optional[str]) -> dict:
    """reconcile_queue status counts (optionally project-scoped) for the same
    progress shape as maintenance ops. Missing table → empty (schema v11 not
    yet migrated)."""
    try:
        if project_id:
            rows = await db.fetchall(
                "SELECT status, COUNT(*) AS c FROM reconcile_queue "
                "WHERE project_id = ? GROUP BY status",
                (project_id,),
            )
        else:
            rows = await db.fetchall(
                "SELECT status, COUNT(*) AS c FROM reconcile_queue GROUP BY status"
            )
    except Exception:
        return {}
    return {str(r["status"]): int(r["c"]) for r in rows}


async def _reconcile_status_counts_by_project(db) -> dict:
    """{project_id: {status: n}} over reconcile_queue; missing table → empty."""
    try:
        rows = await db.fetchall(
            "SELECT project_id, status, COUNT(*) AS c FROM reconcile_queue "
            "WHERE project_id IS NOT NULL GROUP BY project_id, status"
        )
    except Exception:
        return {}
    out: dict = {}
    for r in rows:
        out.setdefault(str(r["project_id"]), {})[str(r["status"])] = int(r["c"])
    return out


@router.get("/status")
async def maintenance_status(
    project_id: Optional[str] = None,
    by_project: bool = False,
    service: MaintenanceService = Depends(get_maintenance_service),
    db=Depends(get_database),
) -> dict:
    """Queue status counts + pending improve-proposal count (for UI badges).

    With ``project_id`` every count is scoped to that project; with
    ``by_project`` a ``queue_by_project`` map covering all projects in one
    request is added (the project-card progress poll). Without either the
    counts stay global as before. ``reconcile`` is included so card progress
    covers all three operations.
    """
    queue = await service.status_counts(project_id=project_id)
    reconcile = await _reconcile_status_counts(db, project_id)
    if reconcile:
        queue["reconcile"] = reconcile
    result = {
        "queue": queue,
        "pending_proposals": await service.count_refine_proposals(
            project_id=project_id
        ),
    }
    if by_project:
        by_proj = await service.status_counts_by_project()
        for proj, statuses in (await _reconcile_status_counts_by_project(db)).items():
            by_proj.setdefault(proj, {})["reconcile"] = statuses
        result["queue_by_project"] = by_proj
    return result


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


class RetryRequest(BaseModel):
    operation: Optional[str] = None
    project_id: Optional[str] = None
    job_id: Optional[str] = None


@router.post("/retry")
async def retry_dead_letters(
    payload: RetryRequest,
    service: MaintenanceService = Depends(get_maintenance_service),
) -> dict:
    """Requeue dead-lettered enrich/improve jobs (attempts reset, worker picks
    them up again). Optional operation / project_id / job_id narrow the scope."""
    if payload.operation and payload.operation not in MAINTENANCE_OPERATIONS:
        raise HTTPException(
            status_code=400, detail=f"unknown operation: {payload.operation}"
        )
    retried = await service.retry_dead_letters(
        operation=payload.operation,
        project_id=payload.project_id,
        job_id=payload.job_id,
    )
    return {"retried": retried}


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
