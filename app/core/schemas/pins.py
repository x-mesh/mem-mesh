"""Pin 관련 스키마 정의"""

from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
import re


class PinCreate(BaseModel):
    """Pin 생성 요청"""
    content: str = Field(min_length=1, max_length=10000)
    project_id: str = Field(min_length=1, max_length=100)
    importance: Optional[int] = Field(default=None, ge=1, le=5)
    tags: Optional[List[str]] = Field(default=None)
    user_id: Optional[str] = Field(default=None)
    
    @field_validator('project_id')
    @classmethod
    def validate_project_id(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("project_id must contain only letters, numbers, hyphens, and underscores")
        return v


class PinUpdate(BaseModel):
    """Pin 업데이트 요청"""
    content: Optional[str] = Field(default=None, min_length=1, max_length=10000)
    importance: Optional[int] = Field(default=None, ge=1, le=5)
    status: Optional[str] = Field(default=None)
    tags: Optional[List[str]] = Field(default=None)
    
    @field_validator('status')
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            valid_statuses = {'open', 'in_progress', 'completed'}
            if v not in valid_statuses:
                raise ValueError(f"Invalid status: {v}. Must be one of {valid_statuses}")
        return v


class PinResponse(BaseModel):
    """Pin 응답"""
    id: str
    session_id: str
    project_id: str
    user_id: str
    content: str
    importance: int
    status: str
    tags: List[str]
    completed_at: Optional[str] = None
    lead_time_hours: Optional[float] = None
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
    
    @field_validator('status')
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            valid_statuses = {'open', 'in_progress', 'completed'}
            if v not in valid_statuses:
                raise ValueError(f"Invalid status: {v}. Must be one of {valid_statuses}")
        return v
