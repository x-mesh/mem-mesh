"""요청 스키마 정의"""

import re
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


def normalize_project_id(v: Optional[str]) -> Optional[str]:
    """project_id를 kebab-case로 정규화.

    camelCase/PascalCase → kebab-case 변환 후 소문자화.
    예: "jmonServerWeb" → "jmon-server-web"
        "MyProject" → "my-project"
        "already-kebab" → "already-kebab" (변경 없음)
    """
    if v is None:
        return v
    if not isinstance(v, str) or len(v) == 0:
        raise ValueError("project_id must be a non-empty string")

    # camelCase/PascalCase → kebab-case: insert hyphen before uppercase letters
    normalized = re.sub(r"(?<=[a-z0-9])([A-Z])", r"-\1", v)
    # Handle consecutive uppercase: "HTMLParser" → "html-parser"
    normalized = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", normalized)
    normalized = normalized.lower()
    # Replace spaces/underscores with hyphens
    normalized = re.sub(r"[\s_]+", "-", normalized)
    # Remove consecutive hyphens
    normalized = re.sub(r"-+", "-", normalized).strip("-")

    if not re.match(r"^[a-z0-9][a-z0-9_-]*$", normalized):
        raise ValueError(
            f"project_id '{v}' cannot be normalized to a valid format. "
            "Must contain only letters, numbers, hyphens, and underscores"
        )
    return normalized


class AddParams(BaseModel):
    """메모리 추가 요청 파라미터"""

    content: str = Field(min_length=100, max_length=50000)
    project_id: Optional[str] = Field(default=None)
    category: str = Field(default="task")
    source: Optional[str] = Field(default=None)
    client: Optional[str] = Field(default=None, max_length=50)
    tags: Optional[List[str]] = Field(default=None)

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, v: Optional[str]) -> Optional[str]:
        return normalize_project_id(v)

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
