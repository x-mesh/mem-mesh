"""Project 관련 스키마 정의"""

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ProjectCreate(BaseModel):
    """Project 생성 요청"""

    id: str = Field(min_length=1, max_length=100)
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    tech_stack: Optional[str] = Field(default=None, max_length=500)
    global_rules: Optional[str] = Field(default=None, max_length=10000)
    global_context: Optional[str] = Field(default=None, max_length=10000)

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "id must contain only letters, numbers, hyphens, and underscores"
            )
        return v


class ProjectUpdate(BaseModel):
    """Project 업데이트 요청"""

    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    tech_stack: Optional[str] = Field(default=None, max_length=500)
    global_rules: Optional[str] = Field(default=None, max_length=10000)
    global_context: Optional[str] = Field(default=None, max_length=10000)


class ProjectResponse(BaseModel):
    """Project 응답"""

    id: str
    name: str
    description: Optional[str] = None
    tech_stack: Optional[str] = None
    global_rules: Optional[str] = None
    global_context: Optional[str] = None
    created_at: str
    updated_at: str


class ProjectWithStats(BaseModel):
    """Project 응답 (통계 포함)"""

    id: str
    name: str
    description: Optional[str] = None
    tech_stack: Optional[str] = None
    global_rules: Optional[str] = None
    memory_count: int = 0
    pin_count: int = 0
    active_session: Optional[str] = None
    avg_lead_time_hours: Optional[float] = None
