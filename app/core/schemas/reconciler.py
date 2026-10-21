"""Memory Reconciler contracts and stable identifiers."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .requests import normalize_anchored_path, normalize_project_id

READ_VIEWS = {"effective", "raw"}
RECONCILER_ACTIONS = {
    "keep",
    "merge",
    "supersede",
    "archive",
    "add_relation",
    "mark_stale",
    "quarantine",
    "noise_suppression",
    "needs_review",
    "no_op",
}
CURATED_ID_RE = re.compile(r"^cr_[0-9a-f]{32}$")


def make_curated_id(proposal_id: str) -> str:
    """Return a deterministic curated-result identifier for one proposal."""

    return "cr_" + hashlib.sha256(str(proposal_id).encode("utf-8")).hexdigest()[:32]


def is_curated_id(value: str) -> bool:
    return bool(CURATED_ID_RE.fullmatch(str(value or "")))


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ClaimSourceRef(BaseModel):
    memory_id: str = Field(min_length=1)
    input_hash: str = Field(min_length=1)


class ReconcilerClaim(BaseModel):
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    conditions: List[str] = Field(default_factory=list)
    source_refs: List[ClaimSourceRef] = Field(min_length=1)


class ReconcilerPolicy(BaseModel):
    auto_noise_suppression: bool = False
    auto_derived_relations: bool = False
    retain_evidence_content: bool = True


class ReconcilerRunRequest(BaseModel):
    project_id: str
    dry_run: bool = True
    anchored_path: Optional[str] = Field(default=None, max_length=500)
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None

    @field_validator("project_id")
    @classmethod
    def validate_project(cls, value: str) -> str:
        normalized = normalize_project_id(value)
        if not normalized:
            raise ValueError("project_id is required")
        return normalized

    @field_validator("anchored_path")
    @classmethod
    def validate_anchored_path(cls, value: Optional[str]) -> Optional[str]:
        return normalize_anchored_path(value)

    @field_validator("created_after", "created_before")
    @classmethod
    def require_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.utcoffset() is None:
            raise ValueError("time range requires a timezone")
        return value

    @model_validator(mode="after")
    def validate_time_range(self) -> "ReconcilerRunRequest":
        if (
            self.created_after is not None
            and self.created_before is not None
            and self.created_after > self.created_before
        ):
            raise ValueError("created_after must not exceed created_before")
        return self


class ReconcilerRunLookup(BaseModel):
    project_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=100)
    run_id: str = Field(pattern=r"^rr_[0-9a-f]{32}$")

    @field_validator("project_id")
    @classmethod
    def validate_project(cls, value: str) -> str:
        return normalize_project_id(value)


class ReconcilerProposalListRequest(BaseModel):
    project_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=100)
    status: Optional[str] = Field(default=None, max_length=32)
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("project_id")
    @classmethod
    def validate_project(cls, value: str) -> str:
        return normalize_project_id(value)


class ReconcilerCandidateListRequest(ReconcilerRunLookup):
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ReconcilerCandidateLookup(BaseModel):
    project_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=100)
    candidate_id: str = Field(pattern=r"^rc_[0-9a-f]{32}$")

    @field_validator("project_id")
    @classmethod
    def validate_project(cls, value: str) -> str:
        return normalize_project_id(value)


class ReconcilerResultLookup(BaseModel):
    project_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=100)
    result_id: str = Field(pattern=r"^cr_[0-9a-f]{32}$")

    @field_validator("project_id")
    @classmethod
    def validate_project(cls, value: str) -> str:
        return normalize_project_id(value)


class ReconcilerDecisionRequest(BaseModel):
    decision: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)


class ReconcilerCancelRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class ReconcilerResult(BaseModel):
    id: str
    project_id: str
    body: str
    representative_memory_id: Optional[str] = None
    status: str
    revision: int = 0
    citations: List[Dict[str, Any]] = Field(default_factory=list)


class ReconcilerOverview(BaseModel):
    project_id: str
    overview: Optional[Dict[str, Any]] = None
    generated_at: Optional[str] = None
    coverage: Dict[str, int] = Field(default_factory=dict)
    unreviewed_count: int = 0
    partial: bool = False
    stale: bool = False
    stale_reason: Optional[str] = None
    source_references: List[Dict[str, Any]] = Field(default_factory=list)
