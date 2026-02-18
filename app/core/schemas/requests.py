"""요청 스키마 정의"""

from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
import re


class AddParams(BaseModel):
    """메모리 추가 요청 파라미터"""

    content: str = Field(min_length=10, max_length=10000)
    project_id: Optional[str] = Field(default=None)
    category: str = Field(default="task")
    source: Optional[str] = Field(default=None)
    tags: Optional[List[str]] = Field(default=None)

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not isinstance(v, str) or len(v) == 0:
                raise ValueError("project_id must be a non-empty string")
            if not re.match(r"^[a-z0-9_-]+$", v):
                raise ValueError(
                    "project_id must contain only lowercase letters, numbers, hyphens, and underscores"
                )
        return v

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


class SearchParams(BaseModel):
    """메모리 검색 요청 파라미터"""

    query: str = Field(min_length=0)  # 빈 쿼리 허용
    project_id: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None)
    limit: int = Field(default=5, ge=1, le=20)
    recency_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    search_mode: str = Field(
        default="hybrid", description="검색 모드: hybrid, exact, semantic, fuzzy"
    )

    @field_validator("search_mode")
    @classmethod
    def validate_search_mode(cls, v: str) -> str:
        valid_modes = {"hybrid", "exact", "semantic", "fuzzy"}
        if v not in valid_modes:
            raise ValueError(f"Invalid search_mode: {v}. Must be one of {valid_modes}")
        return v

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not isinstance(v, str) or len(v) == 0:
                raise ValueError("project_id must be a non-empty string")
            if not re.match(r"^[a-z0-9_-]+$", v):
                raise ValueError(
                    "project_id must contain only lowercase letters, numbers, hyphens, and underscores"
                )
        return v

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
        if v is not None:
            if not isinstance(v, str) or len(v) == 0:
                raise ValueError("project_id must be a non-empty string")
            if not re.match(r"^[a-z0-9_-]+$", v):
                raise ValueError(
                    "project_id must contain only lowercase letters, numbers, hyphens, and underscores"
                )
        return v


class DeleteParams(BaseModel):
    """메모리 삭제 요청 파라미터"""

    memory_id: str = Field(description="삭제할 메모리 ID")


class UpdateParams(BaseModel):
    """메모리 업데이트 요청 파라미터"""

    content: Optional[str] = Field(default=None, min_length=10, max_length=10000)
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
        if v is not None:
            if not isinstance(v, str) or len(v) == 0:
                raise ValueError("project_id must be a non-empty string")
            if not re.match(r"^[a-z0-9_-]+$", v):
                raise ValueError(
                    "project_id must contain only lowercase letters, numbers, hyphens, and underscores"
                )
        return v

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
