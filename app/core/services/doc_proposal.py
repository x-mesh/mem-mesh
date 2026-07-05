"""Doc proposal 상태 머신 (P4 문서 승격).

고가치 메모리를 버전 관리되는 문서로 승격하기 위한 제안을 관리한다.
``maintenance.py``의 refine_proposal human-gate 패턴을 파일(문서) 버전으로
옮긴 것으로, 승인 상태 머신이 문서 반영의 관문 역할을 한다(nori bots 모델:
기본 거부, 사람 승인).

**서버는 파일에 절대 쓰지 않는다.** project_id → 실제 파일 경로 매핑이 없고
Docker 배포에서 작업 트리가 마운트되지 않기 때문이다(연구로 확정). 제안의
적용(파일 쓰기)은 클라이언트(에이전트)가 수행하고, 서버는 ``applied`` 보고만
받아 상태를 전이시킨다. 따라서 이 서비스의 어떤 공개 메서드도 파일시스템에
쓰지 않는다.

상태 전이:

    pending ──approve──▶ approved ──mark_applied──▶ applied   (terminal)
       └────reject────▶ rejected                              (terminal)

정의되지 않은 전이(예: pending → applied, approved → rejected, terminal에서의
모든 전이)는 중앙 에러 ``InvalidStatusTransitionError``로 거부한다.

스키마는 Database 인스턴스별로 lazy/memoize(EnrichmentStore/MaintenanceService
전례)하므로 마이그레이션 bump이 필요 없다.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
import weakref
from datetime import datetime, timezone
from typing import Any, List, Optional

from ..errors import (
    ChatNotConfiguredError,
    ChatProviderError,
    DocProposalNotFoundError,
    DocProposalPathError,
    InvalidStatusTransitionError,
    ValidationError,
)
from ..schemas.doc_proposal import DocProposalCreate
from .enrich_store import EnrichmentStore

# 승격 후보 휴리스틱: 카테고리 가중치. 지식 밀도가 높은 결정/장애/버그를 우선하고,
# 아이디어/코드 스니펫이 그다음, 나머지(task 등)는 0. LLM 없이도 동작하는
# feature-gate free tier가 이 점수로 후보를 정렬한다.
_CATEGORY_WEIGHTS: dict[str, int] = {
    "decision": 3,
    "incident": 3,
    "bug": 3,
    "idea": 1,
    "code_snippet": 1,
}
# access_count 기여 상한 — 자주 조회된 한 메모리가 카테고리 신호를 압도하지 않도록.
_ACCESS_SCORE_CAP = 5

# 상태 머신: {현재 상태: 허용된 다음 상태들}. 여기에 없는 전이는 모두 불법.
_ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "pending": ("approved", "rejected"),
    "approved": ("applied",),
    "applied": (),  # terminal
    "rejected": (),  # terminal
}

_SEPARATOR_RE = re.compile(r"[\\/]+")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(text: str) -> str:
    """제공된 파일 내용의 해시 — 클라이언트가 적용 시 stale 감지에 쓰는
    original_hash. 서버는 파일을 읽지 않으므로 클라이언트가 준 file_content에서만
    계산한다(overview.py의 source_hash 전례와 동일한 sha256 hexdigest)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _first_line(content: str) -> str:
    for ln in (content or "").splitlines():
        s = ln.strip(" #").strip()
        if s:
            return s
    return ""


def _parse_tags(raw: Any) -> List[str]:
    """memories/enrichment의 tags(JSON 문자열 또는 list)를 문자열 리스트로 정규화."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(t) for t in raw]
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(t) for t in parsed] if isinstance(parsed, list) else []


def _validate_relative_path(file_path: str) -> str:
    """상대 경로만 허용하고 path traversal을 문자열 수준에서 거부한다.

    서버가 파일을 쓰지 않더라도, 클라이언트가 이 경로로 파일을 적용할 때
    작업 트리 밖으로 벗어나지 않도록 저장 시점에 검증한다. 정규화된(공백 제거된)
    경로를 반환한다.
    """
    raw = file_path or ""
    path = raw.strip()
    if not path:
        raise DocProposalPathError(raw, "empty path")
    if "\x00" in path:
        raise DocProposalPathError(raw, "null byte in path")
    if path.startswith("~"):
        raise DocProposalPathError(raw, "home-relative path not allowed")
    # 절대 경로: POSIX("/x"), UNC 또는 백슬래시 루트("\\host"), Windows 드라이브("C:..").
    if path.startswith("/") or path.startswith("\\"):
        raise DocProposalPathError(raw, "absolute path not allowed")
    if len(path) >= 2 and path[1] == ":":
        raise DocProposalPathError(raw, "absolute path not allowed")
    if ".." in _SEPARATOR_RE.split(path):
        raise DocProposalPathError(raw, "path traversal segment '..' not allowed")
    return path


class DocProposalService:
    """Doc proposal 생성 및 승인 상태 머신.

    서버는 파일에 쓰지 않는다 — 적용은 클라이언트가 하고 서버는 상태 전이만
    관리한다.
    """

    _schema_ready: "weakref.WeakSet" = weakref.WeakSet()

    def __init__(self, db: Any):
        self.db = db

    # ── schema ──────────────────────────────────────────────────────────────

    async def ensure_schema(self) -> None:
        if self.db in DocProposalService._schema_ready:
            return
        async with self.db.transaction():
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS doc_proposals (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    file_path TEXT NOT NULL,
                    original_hash TEXT NOT NULL,
                    proposed_content TEXT NOT NULL,
                    rationale TEXT,
                    source_memory_ids TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    model TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """)
            await self.db.execute("""
                CREATE INDEX IF NOT EXISTS idx_doc_proposals_project_status
                ON doc_proposals(project_id, status, created_at)
                """)
        DocProposalService._schema_ready.add(self.db)

    # ── create ──────────────────────────────────────────────────────────────

    async def create_proposal(self, params: DocProposalCreate) -> dict:
        """``pending`` 상태로 새 제안을 생성한다.

        file_path는 상대 경로 + no-traversal이어야 하며, 위반 시
        ``DocProposalPathError``를 발생시킨다.
        """
        await self.ensure_schema()
        file_path = _validate_relative_path(params.file_path)
        proposal_id = str(uuid.uuid4())
        now = _utc_now()
        source_ids_json = json.dumps(
            list(params.source_memory_ids or []), ensure_ascii=False
        )
        await self.db.execute(
            """
            INSERT INTO doc_proposals (
                id, project_id, file_path, original_hash, proposed_content,
                rationale, source_memory_ids, status, model,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                proposal_id,
                params.normalized_project_id(),
                file_path,
                params.original_hash,
                params.proposed_content,
                params.rationale,
                source_ids_json,
                params.model,
                now,
                now,
            ),
        )
        created = await self.get_proposal(proposal_id)
        assert created is not None  # just inserted
        return created

    # ── promotion candidates (no LLM) ─────────────────────────────────────────

    _SNIPPET_CHARS = 300

    async def list_promotion_candidates(
        self, project_id: str, *, limit: int = 20
    ) -> List[dict]:
        """고가치 메모리를 승격 후보로 반환한다 (LLM 불필요).

        feature-gate의 free tier: LLM 미등록 사용자도 이 목록은 받는다. importance
        컬럼이 없는 memories 테이블에서 기존 컬럼 기반 휴리스틱으로 순위를 매긴다 —
        카테고리(decision/incident/bug 최우선), access_count(검색이 자주 노출한
        정도), enrichment(title/abstract) 유무를 합산한 score로 정렬. 생성은 하지
        않는다: 클라이언트가 후보를 골라 ``generate_proposal``(LLM)로 개정본을
        만든다.
        """
        await self.ensure_schema()
        # memory_enrichment는 lazy 생성 — LEFT JOIN 전에 존재를 보장한다(enrichment를
        # 한 번도 돌리지 않은 DB에서 'no such table' 방지, overview.py 전례).
        await EnrichmentStore(self.db).ensure_schema()
        bounded = max(1, min(limit, 100))
        rows = await self.db.fetchall(
            """
            SELECT m.id AS id, m.category AS category, m.content AS content,
                   COALESCE(m.access_count, 0) AS access_count,
                   m.created_at AS created_at, m.updated_at AS updated_at,
                   e.title AS e_title, e.abstract AS e_abstract,
                   (CASE m.category
                        WHEN 'decision' THEN 3
                        WHEN 'incident' THEN 3
                        WHEN 'bug' THEN 3
                        WHEN 'idea' THEN 1
                        WHEN 'code_snippet' THEN 1
                        ELSE 0 END
                    + MIN(COALESCE(m.access_count, 0), ?)
                    + CASE WHEN e.memory_id IS NOT NULL THEN 1 ELSE 0 END
                   ) AS score
            FROM memories m
            LEFT JOIN memory_enrichment e ON e.memory_id = m.id
            WHERE m.project_id = ?
              AND COALESCE(m.status, 'canonical') = 'canonical'
            ORDER BY score DESC, COALESCE(m.access_count, 0) DESC,
                     m.updated_at DESC, m.created_at DESC
            LIMIT ?
            """,
            (_ACCESS_SCORE_CAP, project_id, bounded),
        )
        candidates: List[dict] = []
        for r in rows:
            content = str(r["content"] or "")
            title = (r["e_title"] or "").strip() or _first_line(content)[:80]
            abstract = (r["e_abstract"] or "").strip() or content[: self._SNIPPET_CHARS]
            candidates.append(
                {
                    "id": str(r["id"]),
                    "category": str(r["category"] or ""),
                    "title": title,
                    "abstract": abstract,
                    "access_count": int(r["access_count"] or 0),
                    "has_enrichment": bool(r["e_title"] or r["e_abstract"]),
                    "score": int(r["score"] or 0),
                    "created_at": str(r["created_at"] or ""),
                    "updated_at": str(r["updated_at"] or ""),
                }
            )
        return candidates

    # ── generate (LLM-gated) ──────────────────────────────────────────────────

    async def generate_proposal(
        self,
        *,
        project_id: str,
        file_path: str,
        file_content: str,
        memory_ids: List[str],
        chat_service: Any,
        settings: Any,
        http_client: Any = None,
        language: Optional[str] = None,
    ) -> dict:
        """선택된 메모리를 대상 파일에 통합한 개정본 제안을 ``pending``으로 생성한다.

        서버는 대상 파일을 읽지 못하므로 원본 내용은 클라이언트가 ``file_content``로
        제공하고, ``original_hash``는 서버가 그 내용에서 계산한다. LLM 미등록 시
        ``ChatNotConfiguredError``로 명확히 거부한다 — 이 경우 클라이언트는
        ``list_promotion_candidates``만 사용할 수 있다(feature gate).
        """
        await self.ensure_schema()
        # Feature gate: 생성은 LLM 필수. 미등록이면 후보 조회로 안내하며 거부한다.
        if not await chat_service.is_configured(settings):
            raise ChatNotConfiguredError(
                "Chat assistant LLM is not configured; doc proposal generation "
                "requires an LLM. Use list_promotion_candidates to review "
                "promotion candidates instead."
            )
        # LLM 호출 전에 값싼 검증부터: 잘못된 경로/빈 선택은 토큰을 쓰기 전에 거른다.
        file_path = _validate_relative_path(file_path)
        memories = await self._load_memories(memory_ids, project_id=project_id)
        revision = await chat_service.generate_doc_revision(
            file_path=file_path,
            file_content=file_content,
            memories=memories,
            settings=settings,
            http_client=http_client,
            language=language,
        )
        proposed_content = str(revision.get("proposed_content") or "").strip()
        if not proposed_content:
            raise ChatProviderError(
                "doc revision response did not include proposed_content"
            )
        params = DocProposalCreate(
            project_id=project_id,
            file_path=file_path,
            original_hash=_sha256(file_content),
            proposed_content=proposed_content,
            rationale=(str(revision.get("rationale") or "").strip() or None),
            source_memory_ids=[str(m["id"]) for m in memories],
            model=(str(revision.get("model") or "").strip() or None),
        )
        return await self.create_proposal(params)

    async def _load_memories(
        self, memory_ids: List[str], *, project_id: Optional[str] = None
    ) -> List[dict]:
        """선택된 메모리의 content + enrichment(abstract/tags)를 로드한다.

        호출자가 준 순서를 유지하고 존재하지 않는 id는 건너뛴다. ``project_id``가
        주어지면 해당 프로젝트의 메모리만 허용한다 — 다른 프로젝트 id는 존재하지
        않는 id와 동일하게 건너뛰어, 타 프로젝트 내용이 문서 제안에 섞이지 않는다.
        유효한 id가 하나도 없으면 ``ValidationError``로 거부한다(LLM에 빈 입력을
        보내지 않는다).
        """
        ids = [str(m).strip() for m in (memory_ids or []) if str(m).strip()]
        if not ids:
            raise ValidationError(
                "generate_proposal requires at least one source memory id"
            )
        await EnrichmentStore(self.db).ensure_schema()
        placeholders = ",".join("?" for _ in ids)
        project_clause = ""
        params: tuple = tuple(ids)
        if project_id:
            project_clause = "AND m.project_id = ?"
            params = tuple(ids) + (project_id,)
        rows = await self.db.fetchall(
            f"""
            SELECT m.id AS id, m.category AS category, m.content AS content,
                   m.tags AS tags,
                   e.abstract AS e_abstract, e.tags AS e_tags
            FROM memories m
            LEFT JOIN memory_enrichment e ON e.memory_id = m.id
            WHERE m.id IN ({placeholders}) {project_clause}
            """,
            params,
        )
        by_id = {str(r["id"]): r for r in rows}
        memories: List[dict] = []
        for mem_id in ids:  # preserve caller order; drop unknown ids
            r = by_id.get(mem_id)
            if r is None:
                continue
            memories.append(
                {
                    "id": mem_id,
                    "category": str(r["category"] or ""),
                    "content": str(r["content"] or ""),
                    "tags": _parse_tags(r["e_tags"]) or _parse_tags(r["tags"]),
                    "abstract": (r["e_abstract"] or "").strip(),
                }
            )
        if not memories:
            raise ValidationError(
                "none of the given source memory ids exist for this project"
            )
        return memories

    # ── read ────────────────────────────────────────────────────────────────

    async def get_proposal(self, proposal_id: str) -> Optional[dict]:
        await self.ensure_schema()
        row = await self.db.fetchone(
            "SELECT * FROM doc_proposals WHERE id = ?", (proposal_id,)
        )
        return self._row_to_dict(row) if row else None

    async def list_proposals(
        self,
        *,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        await self.ensure_schema()
        clauses: List[str] = []
        params: List[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 200)))
        rows = await self.db.fetchall(
            f"SELECT * FROM doc_proposals {where} " f"ORDER BY created_at DESC LIMIT ?",
            tuple(params),
        )
        return [self._row_to_dict(r) for r in rows]

    async def count_proposals(
        self, *, project_id: Optional[str] = None, status: str = "pending"
    ) -> int:
        await self.ensure_schema()
        clauses = ["status = ?"]
        params: List[Any] = [status]
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        row = await self.db.fetchone(
            f"SELECT COUNT(*) AS c FROM doc_proposals "
            f"WHERE {' AND '.join(clauses)}",
            tuple(params),
        )
        return int(row["c"]) if row else 0

    # ── transitions ─────────────────────────────────────────────────────────

    async def approve_proposal(self, proposal_id: str) -> dict:
        """pending → approved."""
        return await self._transition(proposal_id, "approved")

    async def reject_proposal(self, proposal_id: str) -> dict:
        """pending → rejected (terminal)."""
        return await self._transition(proposal_id, "rejected")

    async def mark_applied(self, proposal_id: str) -> dict:
        """approved → applied (terminal).

        클라이언트가 파일을 적용한 뒤 보고하는 종료 전이. 서버는 파일을 쓰지
        않으므로 여기서 하는 일은 상태 전이 기록뿐이다.
        """
        return await self._transition(proposal_id, "applied")

    async def _transition(self, proposal_id: str, target: str) -> dict:
        """상태 머신에 따라 하나의 전이를 검증하고 적용한다.

        제안이 없으면 ``DocProposalNotFoundError``, 정의되지 않은 전이면
        ``InvalidStatusTransitionError``를 발생시킨다.
        """
        await self.ensure_schema()
        row = await self.db.fetchone(
            "SELECT status FROM doc_proposals WHERE id = ?", (proposal_id,)
        )
        if row is None:
            raise DocProposalNotFoundError(proposal_id)
        current = str(row["status"])
        if target not in _ALLOWED_TRANSITIONS.get(current, ()):
            raise InvalidStatusTransitionError(current, target)
        await self.db.execute(
            "UPDATE doc_proposals SET status = ?, updated_at = ? WHERE id = ?",
            (target, _utc_now(), proposal_id),
        )
        updated = await self.get_proposal(proposal_id)
        assert updated is not None  # existed a statement ago, same txn scope
        return updated

    # ── helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: Any) -> dict:
        data = dict(row)
        try:
            data["source_memory_ids"] = (
                json.loads(data["source_memory_ids"])
                if data.get("source_memory_ids")
                else []
            )
        except (json.JSONDecodeError, TypeError):
            data["source_memory_ids"] = []
        return data
