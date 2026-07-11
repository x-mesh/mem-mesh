"""요청 스키마 정의"""

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

# Git-worktree checkouts append ``-wt-<hex>`` / ``_wt_<hex>`` to the repo dir;
# that suffix would otherwise fragment one repo into many project ids.
_WT_SUFFIX_RE = re.compile(r"[-_]wt[-_][0-9a-f]{6,}$", re.IGNORECASE)

# Git commit hash: abbreviated (7) up to full sha-256 (64) hex chars.
_COMMIT_HASH_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")

# Anchor keys the server accepts; anything else is rejected so a typo can't be
# silently swallowed and lost.
_ANCHOR_KEYS = {"commit_hash", "file_paths", "branch", "file_hashes"}
_MAX_ANCHOR_FILE_PATHS = 20

# File content hash: algorithm prefix + hex digest (e.g. "xxh64:a1b2...",
# "sha256:..."). The prefix keeps algorithms migratable side by side.
# \Z (not $): $ would accept a trailing newline — exactly what an agent
# produces by capturing `shasum` output unstripped — and the corrupt digest
# would then never string-equal a clean re-hash, wrongly reporting stale.
_FILE_HASH_RE = re.compile(r"^[a-z0-9_]+:[0-9a-fA-F]{8,128}\Z")


def validate_anchors(v: Optional[dict]) -> Optional[dict]:
    """Validate a memory git-anchor payload and return a cleaned dict (or None).

    Single source of truth for the ``anchors`` field. Anchors are metadata the
    client (agent) collects — the server has no git access — pinning a memory to
    the commit/files/branch it was written against, used for display and
    lifetime judgement only (never embedded or searched).

    Shape: ``{commit_hash: str(7-64 hex), file_paths: list[str] (relative, no
    ``..``, <=20), branch: str, file_hashes: dict[rel_path, "algo:hex"] (<=20)}``.
    Every field is optional; an all-empty payload normalizes to ``None``. Raises
    ``ValueError`` (→ HTTP 422 via Pydantic) on a bad hash, an absolute/traversal
    path, an over-long list, or an unknown key.

    ``file_hashes`` lets the client verify staleness per file: if the anchored
    file's current content hash still matches, the memory is fresh even when
    ``commit_hash`` is old (unrelated commits don't invalidate it). The server
    only stores and returns these values — hashing happens client-side.
    """
    if v is None:
        return None
    if not isinstance(v, dict):
        raise ValueError("anchors must be an object")

    unknown = set(v) - _ANCHOR_KEYS
    if unknown:
        raise ValueError(
            f"anchors has unknown keys: {sorted(unknown)}. "
            f"Allowed: {sorted(_ANCHOR_KEYS)}"
        )

    cleaned: dict = {}

    commit_hash = v.get("commit_hash")
    if commit_hash is not None:
        if not isinstance(commit_hash, str) or not _COMMIT_HASH_RE.match(commit_hash):
            raise ValueError("anchors.commit_hash must be 7-64 hexadecimal characters")
        cleaned["commit_hash"] = commit_hash

    file_paths = v.get("file_paths")
    if file_paths is not None:
        if not isinstance(file_paths, list):
            raise ValueError("anchors.file_paths must be a list of relative paths")
        if len(file_paths) > _MAX_ANCHOR_FILE_PATHS:
            raise ValueError(
                f"anchors.file_paths cannot exceed {_MAX_ANCHOR_FILE_PATHS} entries"
            )
        validated_paths: List[str] = []
        for path in file_paths:
            if not isinstance(path, str) or not path.strip():
                raise ValueError("anchors.file_paths entries must be non-empty strings")
            # Reject absolute paths (POSIX ``/foo`` and Windows ``C:\\foo``).
            if path.startswith("/") or (len(path) >= 2 and path[1] == ":"):
                raise ValueError(f"anchors.file_paths must be relative: {path!r}")
            # Reject ``..`` traversal in any segment (both separators).
            if ".." in re.split(r"[\\/]+", path):
                raise ValueError(f"anchors.file_paths must not contain '..': {path!r}")
            # Canonical separators on write: a Windows client's backslash path
            # would otherwise be invisible to the anchored_path SQL filter.
            validated_paths.append(path.replace("\\", "/"))
        cleaned["file_paths"] = validated_paths

    branch = v.get("branch")
    if branch is not None:
        if not isinstance(branch, str) or not branch.strip():
            raise ValueError("anchors.branch must be a non-empty string")
        cleaned["branch"] = branch

    file_hashes = v.get("file_hashes")
    if file_hashes is not None:
        if not isinstance(file_hashes, dict):
            raise ValueError(
                "anchors.file_hashes must be an object of {relative_path: 'algo:hex'}"
            )
        if len(file_hashes) > _MAX_ANCHOR_FILE_PATHS:
            raise ValueError(
                f"anchors.file_hashes cannot exceed {_MAX_ANCHOR_FILE_PATHS} entries"
            )
        validated_hashes: Dict[str, str] = {}
        for path, digest in file_hashes.items():
            if not isinstance(path, str) or not path.strip():
                raise ValueError("anchors.file_hashes keys must be non-empty strings")
            if path.startswith("/") or (len(path) >= 2 and path[1] == ":"):
                raise ValueError(f"anchors.file_hashes keys must be relative: {path!r}")
            if ".." in re.split(r"[\\/]+", path):
                raise ValueError(
                    f"anchors.file_hashes keys must not contain '..': {path!r}"
                )
            if not isinstance(digest, str) or not _FILE_HASH_RE.match(digest):
                raise ValueError(
                    "anchors.file_hashes values must be 'algo:hexdigest' "
                    f"(e.g. 'xxh64:1a2b...'): {digest!r}"
                )
            validated_hashes[path.replace("\\", "/")] = digest
        cleaned["file_hashes"] = validated_hashes

    return cleaned or None


def normalize_anchored_path(v: Optional[str]) -> Optional[str]:
    """Validate/normalize a search ``anchored_path`` prefix.

    Same rules as ``anchors.file_paths`` entries (relative, no ``..``), shared
    by every transport (Pydantic SearchParams AND the REST route, which calls
    UnifiedSearchService directly and would otherwise skip validation).
    Normalizes to forward slashes with the trailing ``/`` stripped so the SQL
    prefix clause can rely on one canonical form. Raises ``ValueError`` on an
    absolute or traversal path; empty input normalizes to ``None``.
    """
    if v is None:
        return None
    normalized = v.replace("\\", "/").strip().rstrip("/")
    if not normalized:
        return None
    if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
        raise ValueError(f"anchored_path must be relative: {v!r}")
    if ".." in normalized.split("/"):
        raise ValueError(f"anchored_path must not contain '..': {v!r}")
    return normalized


def normalize_project_id(v: Optional[str], *, strict: bool = True) -> Optional[str]:
    """project_id를 정규화하는 **단일 진실 공급원(single source of truth)**.

    The server normalizes; clients (HTTP-hook cwd basename, command-hook RAW
    basename, MCP explicit id) may send any variant of the same repo and they
    all converge to one id:

        "/Users/dev/work/OCI.Tools-wt-ABCDEF" → "oci-tools"  (path + worktree + dot)
        "jmonServerWeb" → "jmon-server-web"                  (camelCase)
        "MyProject" → "my-project"
        "HTMLParser" → "html-parser"                         (consecutive caps)
        "oci_tools" / "OCI-Tools" → "oci-tools"
        "already-kebab" → "already-kebab"                    (idempotent)

    Pipeline: filesystem path → last segment; strip git-worktree suffix;
    camelCase/PascalCase → kebab; lower-case; ``_`` ``.`` whitespace → ``-``;
    collapse repeated ``-``.

    ``strict=True`` (API/MCP via Pydantic schema): raise ValueError on an
    un-normalizable value, surfacing as HTTP 422. ``strict=False`` (hook entry
    points, which must never break the caller): return ``"unknown"`` instead.

    NOTE (historical data split): this is stricter than the pre-P2 hook
    normalizer, which only lower-cased (e.g. "MyProject" → "myproject"). Rows
    saved before this change keep their old id, so a repo may appear split
    across the old and new ids until/unless backfilled. No migration is done.
    """
    if v is None:
        return v
    if not isinstance(v, str) or len(v.strip()) == 0:
        if strict:
            raise ValueError("project_id must be a non-empty string")
        return "unknown"

    name = v.strip()
    # A filesystem path may leak in as the id. Split on BOTH separators: a
    # Windows client (cwd="C:\\Users\\dev\\work\\MyProject") reaching a POSIX
    # server would otherwise keep the whole backslash string — Path(cwd).name
    # on POSIX does not treat "\\" as a separator — and collapse every repo to
    # "unknown". Handling it here (the single normalize chokepoint) also fixes
    # the HTTP-hook _project_id path without a PureWindowsPath.
    if "/" in name or "\\" in name:
        name = re.split(r"[\\/]+", name.rstrip("/\\"))[-1]
    name = _WT_SUFFIX_RE.sub("", name)  # drop worktree suffix before casing

    # camelCase/PascalCase → kebab-case: insert hyphen before uppercase letters
    normalized = re.sub(r"(?<=[a-z0-9])([A-Z])", r"-\1", name)
    # Handle consecutive uppercase: "HTMLParser" → "html-parser"
    normalized = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", normalized)
    normalized = normalized.lower()
    # Unify separators: spaces/underscores/dots → hyphens
    normalized = re.sub(r"[\s_.]+", "-", normalized)
    # Collapse consecutive hyphens
    normalized = re.sub(r"-+", "-", normalized).strip("-")

    if not re.match(r"^[a-z0-9][a-z0-9_-]*$", normalized):
        if strict:
            raise ValueError(
                f"project_id '{v}' cannot be normalized to a valid format. "
                "Must contain only letters, numbers, hyphens, and underscores"
            )
        return "unknown"
    return normalized


class AddParams(BaseModel):
    """메모리 추가 요청 파라미터"""

    content: str = Field(
        min_length=100,
        max_length=50000,
        description=(
            "Memory body. Minimum 100 characters: permanent memories must be "
            "substantive (decision/bug/incident/idea/code_snippet). Shorter "
            "turns are transient and belong in a pin, not /api/memories. Hook "
            "auto-save filters apply the same >=100 bar, so a 50-99 char turn "
            "is dropped by the hook rather than rejected here with a 422."
        ),
    )
    project_id: Optional[str] = Field(default=None)
    category: str = Field(default="task")
    source: Optional[str] = Field(default=None)
    client: Optional[str] = Field(default=None, max_length=50)
    tags: Optional[List[str]] = Field(default=None)
    anchors: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Git anchors collected by the client: "
            "{commit_hash, file_paths, branch}. Metadata only — not embedded."
        ),
    )

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, v: Optional[str]) -> Optional[str]:
        return normalize_project_id(v)

    @field_validator("anchors")
    @classmethod
    def validate_anchors_field(cls, v: Optional[dict]) -> Optional[dict]:
        return validate_anchors(v)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        valid_categories = {
            "task",
            "bug",
            "idea",
            "decision",
            "incident",
            "code_snippet",
            "git-history",
        }
        if v not in valid_categories:
            raise ValueError(
                f"Invalid category: {v}. Must be one of {valid_categories}"
            )
        return v


VALID_TIME_RANGES = {
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "this_quarter",
}

VALID_TEMPORAL_MODES = {"filter", "boost", "decay"}


class SearchParams(BaseModel):
    """메모리 검색 요청 파라미터"""

    query: str = Field(min_length=0)  # Allow empty query
    project_id: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None)
    categories: Optional[List[str]] = Field(default=None)
    limit: int = Field(default=5, ge=1, le=20)
    recency_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    search_mode: str = Field(
        default="hybrid", description="검색 모드: hybrid, exact, semantic, fuzzy"
    )
    # Time-aware search (Temporal-Aware Search)
    time_range: Optional[str] = Field(
        default=None,
        description="시간 범위 단축어: today, yesterday, this_week, last_week, this_month, last_month, this_quarter",
    )
    date_from: Optional[str] = Field(
        default=None,
        description="시작 날짜 (YYYY-MM-DD)",
    )
    date_to: Optional[str] = Field(
        default=None,
        description="종료 날짜 (YYYY-MM-DD)",
    )
    temporal_mode: str = Field(
        default="boost",
        description="시간 모드: filter (범위 내만), boost (가중치), decay (시간 감쇠)",
    )
    anchored_path: Optional[str] = Field(
        default=None,
        max_length=500,
        description=(
            "anchors.file_paths 프리픽스 필터: repo-root 상대 경로 "
            "(예: 'app/core/'). 해당 파일/디렉토리에 앵커된 메모리만 반환"
        ),
    )
    starred_only: bool = Field(
        default=False,
        description="True면 사용자가 별표한 메모리만 반환 (표시·필터 전용 플래그)",
    )

    @field_validator("anchored_path")
    @classmethod
    def validate_anchored_path(cls, v: Optional[str]) -> Optional[str]:
        return normalize_anchored_path(v)

    @field_validator("search_mode")
    @classmethod
    def validate_search_mode(cls, v: str) -> str:
        valid_modes = {"hybrid", "exact", "semantic", "fuzzy"}
        if v not in valid_modes:
            raise ValueError(f"Invalid search_mode: {v}. Must be one of {valid_modes}")
        return v

    @field_validator("time_range")
    @classmethod
    def validate_time_range(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_TIME_RANGES:
            raise ValueError(
                f"Invalid time_range: {v}. Must be one of {VALID_TIME_RANGES}"
            )
        return v

    @field_validator("date_from", "date_to")
    @classmethod
    def validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
                raise ValueError("Date must be in YYYY-MM-DD format")
        return v

    @field_validator("temporal_mode")
    @classmethod
    def validate_temporal_mode(cls, v: str) -> str:
        if v not in VALID_TEMPORAL_MODES:
            raise ValueError(
                f"Invalid temporal_mode: {v}. Must be one of {VALID_TEMPORAL_MODES}"
            )
        return v

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, v: Optional[str]) -> Optional[str]:
        return normalize_project_id(v)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            valid_categories = {
                "task",
                "bug",
                "idea",
                "decision",
                "incident",
                "code_snippet",
                "git-history",
            }
            if v not in valid_categories:
                raise ValueError(
                    f"Invalid category: {v}. Must be one of {valid_categories}"
                )
        return v

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            valid_categories = {
                "task",
                "bug",
                "idea",
                "decision",
                "incident",
                "code_snippet",
                "git-history",
            }
            for item in v:
                if item not in valid_categories:
                    raise ValueError(
                        f"Invalid category: {item}. Must be one of {valid_categories}"
                    )
        return v


class ContextParams(BaseModel):
    """맥락 조회 요청 파라미터"""

    memory_id: str = Field(description="조회할 메모리 ID")
    depth: int = Field(default=2, ge=1, le=5, description="검색 깊이 (1-5)")
    project_id: Optional[str] = Field(default=None, description="프로젝트 ID 필터")

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, v: Optional[str]) -> Optional[str]:
        return normalize_project_id(v)


class DeleteParams(BaseModel):
    """메모리 삭제 요청 파라미터"""

    memory_id: str = Field(description="삭제할 메모리 ID")


class UpdateParams(BaseModel):
    """메모리 업데이트 요청 파라미터"""

    content: Optional[str] = Field(default=None, min_length=100, max_length=50000)
    category: Optional[str] = Field(default=None)
    tags: Optional[List[str]] = Field(default=None)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            valid_categories = {
                "task",
                "bug",
                "idea",
                "decision",
                "incident",
                "code_snippet",
                "git-history",
            }
            if v not in valid_categories:
                raise ValueError(
                    f"Invalid category: {v}. Must be one of {valid_categories}"
                )
        return v


class RuleUpdateParams(BaseModel):
    """Rules 파일 업데이트 요청 파라미터"""

    content: str = Field(min_length=1, max_length=200000)


class StatsParams(BaseModel):
    """통계 조회 요청 파라미터"""

    project_id: Optional[str] = Field(
        default=None, description="특정 프로젝트로 필터링"
    )
    start_date: Optional[str] = Field(
        default=None, description="시작 날짜 (YYYY-MM-DD)"
    )
    end_date: Optional[str] = Field(default=None, description="종료 날짜 (YYYY-MM-DD)")
    group_by: str = Field(default="overall", description="그룹화 방식")

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, v: Optional[str]) -> Optional[str]:
        return normalize_project_id(v)

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
                raise ValueError("Date must be in YYYY-MM-DD format")
        return v

    @field_validator("group_by")
    @classmethod
    def validate_group_by(cls, v: str) -> str:
        valid_groups = {"overall", "project", "category", "source"}
        if v not in valid_groups:
            raise ValueError(f"Invalid group_by: {v}. Must be one of {valid_groups}")
        return v
