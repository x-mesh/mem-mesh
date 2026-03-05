"""Pin 관련 스키마 정의"""

import re
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class PinCreate(BaseModel):
    """Pin 생성 요청"""

    content: str = Field(
        min_length=10, max_length=10000, description="Pin 내용 (최소 10자)"
    )
    project_id: str = Field(min_length=1, max_length=100)
    importance: Optional[int] = Field(default=None, ge=1, le=5)
    tags: Optional[List[str]] = Field(default=None)
    user_id: Optional[str] = Field(default=None)
    client: Optional[str] = Field(default=None, max_length=50)

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "project_id must contain only letters, numbers, hyphens, and underscores"
            )
        return v


class PinUpdate(BaseModel):
    """Pin 업데이트 요청"""

    content: Optional[str] = Field(
        default=None,
        min_length=10,
        max_length=10000,
        description="Pin 내용 (최소 10자)",
    )
    importance: Optional[int] = Field(default=None, ge=1, le=5)
    status: Optional[str] = Field(default=None)
    tags: Optional[List[str]] = Field(default=None)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            valid_statuses = {"open", "in_progress", "completed"}
            if v not in valid_statuses:
                raise ValueError(
                    f"Invalid status: {v}. Must be one of {valid_statuses}"
                )
        return v


class PinResponse(BaseModel):
    """Pin 응답"""

    id: str
    session_id: str
    project_id: str
    user_id: str
    client: Optional[str] = Field(default=None)
    content: str
    importance: int
    status: str
    tags: List[str]
    completed_at: Optional[str] = None
    lead_time_hours: Optional[float] = None
    estimated_tokens: Optional[int] = Field(default=0, description="예상 토큰 수")
    promoted_to_memory_id: Optional[str] = Field(
        default=None, description="승격된 메모리 ID"
    )
    auto_importance: Optional[bool] = Field(
        default=False, description="자동 중요도 추정 여부"
    )
    created_at: str
    updated_at: str


class PinListParams(BaseModel):
    """Pin 목록 조회 파라미터"""

    session_id: Optional[str] = Field(default=None)
    project_id: Optional[str] = Field(default=None)
    user_id: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None)
    limit: int = Field(default=10, ge=1, le=100)
    order_by_importance: bool = Field(default=True)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            valid_statuses = {"open", "in_progress", "completed"}
            if v not in valid_statuses:
                raise ValueError(
                    f"Invalid status: {v}. Must be one of {valid_statuses}"
                )
        return v
