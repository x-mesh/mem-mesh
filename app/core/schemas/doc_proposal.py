"""Doc proposal 스키마 정의 (P4 문서 승격).

고가치 메모리를 버전 관리되는 문서로 승격하기 위한 제안 데이터 계약.
서버는 파일에 절대 쓰지 않으며(project_id→경로 매핑 부재 + Docker 미마운트),
적용은 클라이언트(에이전트)가 수행하고 서버는 applied 보고만 받는다.

file_path의 path-traversal 검증은 저장 시점에 서비스가 중앙 에러
(`DocProposalPathError`)로 수행한다 — 여기서는 데이터 형태만 정의한다.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from app.core.schemas.requests import normalize_project_id


class DocProposalCreate(BaseModel):
    """Doc proposal 생성 요청."""

    project_id: str = Field(min_length=1, max_length=100)
    file_path: str = Field(
        min_length=1,
        max_length=1000,
        description="승격 대상 문서의 상대 경로 (path traversal 금지)",
    )
    original_hash: str = Field(
        min_length=1,
        max_length=128,
        description="제안 생성 시점 대상 파일 내용 해시 (클라이언트 제공, 적용 시 stale 감지용)",
    )
    proposed_content: str = Field(min_length=1, description="제안된 문서 전체 내용")
    rationale: Optional[str] = Field(
        default=None, max_length=4000, description="승격 근거"
    )
    source_memory_ids: List[str] = Field(
        default_factory=list, description="근거가 된 메모리 ID 목록"
    )
    model: Optional[str] = Field(
        default=None, max_length=100, description="제안을 생성한 모델"
    )

    def normalized_project_id(self) -> str:
        return normalize_project_id(self.project_id)


class DocProposalListParams(BaseModel):
    """Doc proposal 목록 조회 파라미터."""

    project_id: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None)
    limit: int = Field(default=50, ge=1, le=200)


class DocProposalResponse(BaseModel):
    """Doc proposal 응답."""

    id: str
    project_id: Optional[str] = None
    file_path: str
    original_hash: str
    proposed_content: str
    rationale: Optional[str] = None
    source_memory_ids: List[str] = Field(default_factory=list)
    status: str
    model: Optional[str] = None
    created_at: str
    updated_at: str


class DocProposalAgentView(BaseModel):
    """MCP ``doc_proposals`` 도구가 반환하는 에이전트-facing 제안 뷰.

    적용 주체는 대상 저장소 cwd의 에이전트다(서버는 파일에 쓰지 않는다). 따라서
    에이전트가 로컬에서 파일을 적용하는 데 필요한 필드만 담는다: 상대 경로,
    제안 전문(``proposed_content``), 그리고 적용 직전 stale 감지에 쓰는
    ``original_hash``. 근거(``rationale``)와 출처 메모리는 검토용으로 함께 준다.
    """

    id: str
    project_id: Optional[str] = None
    file_path: str
    original_hash: str
    proposed_content: str
    rationale: Optional[str] = None
    source_memory_ids: List[str] = Field(default_factory=list)
    status: str
    updated_at: str

    @classmethod
    def from_row(cls, row: dict) -> "DocProposalAgentView":
        """``DocProposalService`` 행 dict(전 컬럼)를 에이전트 뷰로 축약한다."""
        return cls(
            id=str(row["id"]),
            project_id=row.get("project_id"),
            file_path=str(row["file_path"]),
            original_hash=str(row["original_hash"]),
            proposed_content=str(row["proposed_content"]),
            rationale=row.get("rationale"),
            source_memory_ids=list(row.get("source_memory_ids") or []),
            status=str(row["status"]),
            updated_at=str(row.get("updated_at") or ""),
        )


class DocProposalAppliedResponse(BaseModel):
    """``doc_proposal_applied`` 도구 / 적용 보고 응답 (approved → applied)."""

    proposal_id: str
    status: str
    applied: bool = True
