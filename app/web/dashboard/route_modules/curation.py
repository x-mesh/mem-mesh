"""Reconcile curation API routes (SSOT #3, F4).

Human gate over the async reconcile worker's PROPOSED relations: review the
queue and approve/reject/dismiss. Approving a supersede demotes the loser to
``deprecated``; ``reject-new`` deprecates a wrongly-added new memory (C3).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.core.config import get_settings
from app.core.errors import DocProposalNotFoundError
from app.core.schemas.reconciler import (
    ReconcilerCancelRequest,
    ReconcilerDecisionRequest,
    ReconcilerRunRequest,
)
from app.core.services.curation import CurationService
from app.core.services.doc_proposal import DocProposalService
from app.core.services.llm_resolver import resolve_service_llm
from app.core.services.memory_reconciler import (
    MemoryReconcilerService,
    ReconcilerConflictError,
    ReconcilerValidationError,
)
from app.web.common.dependencies import (
    get_database,
    get_embedding_service,
    get_memory_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/curation", tags=["Curation"])


def get_curation_service(
    db=Depends(get_database),
    memory_service=Depends(get_memory_service),
) -> CurationService:
    return CurationService(db, memory_service=memory_service)


def get_doc_proposal_service(db=Depends(get_database)) -> DocProposalService:
    return DocProposalService(db)


async def get_reconciler_service(
    db=Depends(get_database), embedding_service=Depends(get_embedding_service)
) -> MemoryReconcilerService:
    resolved = await resolve_service_llm(db, get_settings(), "reconcile")
    return MemoryReconcilerService(
        db,
        embedding_service=embedding_service,
        model=resolved["model"],
        provider=resolved["provider"],
        llm_base_url=resolved["base_url"],
        llm_configured=bool(resolved["api_key"] and resolved["model"]),
    )


@router.post("/reconciler/runs")
async def create_reconciler_run(
    payload: ReconcilerRunRequest,
    service: MemoryReconcilerService = Depends(get_reconciler_service),
):
    try:
        return await service.create_run(
            payload.project_id,
            dry_run=payload.dry_run,
            anchored_path=payload.anchored_path,
            created_after=payload.created_after,
            created_before=payload.created_before,
            defer_detection=True,
        )
    except ReconcilerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/reconciler/runs/{run_id}")
async def get_reconciler_run(
    run_id: str,
    service: MemoryReconcilerService = Depends(get_reconciler_service),
):
    try:
        return await service.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/reconciler/runs")
async def list_reconciler_runs(
    project_id: str = Query(pattern=r"^[a-zA-Z0-9_-]+$", max_length=100),
    limit: int = Query(default=10, ge=1, le=50),
    service: MemoryReconcilerService = Depends(get_reconciler_service),
):
    return await service.list_runs(project_id, limit)


@router.get("/reconciler/runs/{run_id}/candidates")
async def list_reconciler_candidates(
    run_id: str,
    project_id: str = Query(pattern=r"^[a-zA-Z0-9_-]+$", max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: MemoryReconcilerService = Depends(get_reconciler_service),
):
    try:
        return await service.list_candidates(run_id, project_id, limit, offset)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/reconciler/metrics")
async def get_reconciler_metrics(
    project_id: str = Query(pattern=r"^[a-zA-Z0-9_-]+$", max_length=100),
    service: MemoryReconcilerService = Depends(get_reconciler_service),
):
    return await service.get_metrics(project_id)


@router.get("/reconciler/candidates/{candidate_id}")
async def get_reconciler_candidate_detail(
    candidate_id: str,
    project_id: str = Query(pattern=r"^[a-zA-Z0-9_-]+$", max_length=100),
    service: MemoryReconcilerService = Depends(get_reconciler_service),
):
    try:
        return await service.get_candidate_detail(candidate_id, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/reconciler/runs/{run_id}/cancel")
async def cancel_reconciler_run(
    run_id: str,
    service: MemoryReconcilerService = Depends(get_reconciler_service),
):
    try:
        return await service.cancel_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/reconciler/proposals")
async def list_reconciler_proposals(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    service: MemoryReconcilerService = Depends(get_reconciler_service),
):
    proposals = await service.list_proposals(
        project_id=project_id, status=status, limit=limit
    )
    return {"proposals": proposals, "count": len(proposals)}


@router.post("/reconciler/proposals/{proposal_id}/decision")
async def decide_reconciler_proposal(
    proposal_id: str,
    payload: ReconcilerDecisionRequest,
    service: MemoryReconcilerService = Depends(get_reconciler_service),
):
    try:
        return await service.decide_proposal(
            proposal_id, payload.decision, payload.expected_revision
        )
    except ReconcilerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ReconcilerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/reconciler/results/{result_id}/cancel")
async def cancel_reconciler_result(
    result_id: str,
    payload: ReconcilerCancelRequest,
    service: MemoryReconcilerService = Depends(get_reconciler_service),
):
    try:
        return await service.cancel_result(result_id, payload.expected_revision)
    except ReconcilerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/reconciler/results/{result_id}")
async def get_reconciler_result(
    result_id: str,
    project_id: str = Query(pattern=r"^[a-zA-Z0-9_-]+$", max_length=100),
    service: MemoryReconcilerService = Depends(get_reconciler_service),
):
    try:
        return await service.get_result_detail(result_id, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/reconciler/results/{result_id}/validate")
async def validate_reconciler_result(
    result_id: str,
    service: MemoryReconcilerService = Depends(get_reconciler_service),
):
    try:
        return await service.validate_result(result_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/queue")
async def list_queue(
    project_id: Optional[str] = None,
    limit: int = 50,
    service: CurationService = Depends(get_curation_service),
):
    """List PROPOSED reconcile relations awaiting a human decision."""
    try:
        return {"items": await service.list_queue(project_id=project_id, limit=limit)}
    except Exception as e:
        logger.exception("Curation queue failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/activity")
async def list_activity(
    service: CurationService = Depends(get_curation_service),
):
    """List LLM worker queue activity (status counts + recent rows per worker)."""
    try:
        return await service.list_activity()
    except Exception as e:
        logger.exception("Curation activity failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/supersede/{relation_id}/approve")
async def approve_supersede(
    relation_id: str,
    service: CurationService = Depends(get_curation_service),
):
    """Approve a supersede proposal: deprecate the loser memory."""
    try:
        return await service.approve_supersede(relation_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Approve supersede failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject-new/{memory_id}")
async def reject_new(
    memory_id: str,
    service: CurationService = Depends(get_curation_service),
):
    """C3: deprecate a new memory the human judged wrong."""
    try:
        return await service.reject_new(memory_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Reject-new failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/merge/{relation_id}/approve")
async def approve_merge(
    relation_id: str,
    merged_text: Optional[str] = Body(default=None, embed=True),
    service: CurationService = Depends(get_curation_service),
):
    """Approve a merge: create a new canonical from merged_text, deprecate both.

    ``merged_text`` (optional) overrides the LLM proposal when the human edited it.
    """
    try:
        return await service.approve_merge(relation_id, merged_text=merged_text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Approve merge failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dismiss/{relation_id}")
async def dismiss(
    relation_id: str,
    service: CurationService = Depends(get_curation_service),
):
    """Dismiss a proposal (keep both, no status change)."""
    try:
        return await service.dismiss(relation_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Dismiss failed")
        raise HTTPException(status_code=500, detail=str(e))


# ── Doc promotion proposals (P4) ─────────────────────────────────────────────
# Human gate over doc-promotion proposals: review the queue and approve/reject.
# The server never writes files — approval only flips state; the actual file
# edit is applied by the agent in the target repo (see the doc_proposals /
# doc_proposal_applied MCP tools). Transition guards live in the service state
# machine and surface as MemMeshError → code-specific HTTP status.


@router.get("/doc-proposals")
async def list_doc_proposals(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    service: DocProposalService = Depends(get_doc_proposal_service),
):
    """List doc-promotion proposals awaiting review (filter by project/status)."""
    proposals = await service.list_proposals(
        project_id=project_id, status=status, limit=limit
    )
    return {"proposals": proposals, "count": len(proposals)}


@router.get("/doc-proposals/{proposal_id}")
async def get_doc_proposal(
    proposal_id: str,
    service: DocProposalService = Depends(get_doc_proposal_service),
):
    """Fetch a single doc proposal (full proposed_content + rationale)."""
    proposal = await service.get_proposal(proposal_id)
    if proposal is None:
        raise DocProposalNotFoundError(proposal_id)
    return proposal


@router.post("/doc-proposals/{proposal_id}/approve")
async def approve_doc_proposal(
    proposal_id: str,
    service: DocProposalService = Depends(get_doc_proposal_service),
):
    """Approve a doc proposal (pending → approved).

    Unlike the improve-proposal approve, there is no apply step here: the server
    cannot read the target file, so staleness is re-checked by the agent at apply
    time against ``original_hash``. Approval is a pure state transition; a
    non-pending proposal is rejected by the state machine (400).
    """
    return await service.approve_proposal(proposal_id)


@router.post("/doc-proposals/{proposal_id}/reject")
async def reject_doc_proposal(
    proposal_id: str,
    service: DocProposalService = Depends(get_doc_proposal_service),
):
    """Reject a doc proposal (pending → rejected, terminal)."""
    return await service.reject_proposal(proposal_id)
