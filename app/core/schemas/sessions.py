"""Session 관련 스키마 정의"""

from typing import Optional, List, Any, Union
from pydantic import BaseModel, Field, field_validator

from .pins import PinResponse


class PinCompact(BaseModel):
    """컴팩트 핀 정보 (expand=false용, 토큰 절약)"""
    id: str
    content: str = Field(description="80자로 제한된 내용 요약")
    importance: int
    status: str


class SessionCreate(BaseModel):
    """Session 생성 요청 (내부용)"""
    project_id: str
    user_id: str = Field(default="default")


class SessionResponse(BaseModel):
    """Session 응답"""
    id: str
    project_id: str
    user_id: str
    started_at: str
    ended_at: Optional[str] = None
    status: str
    summary: Optional[str] = None
    initial_context_tokens: Optional[int] = Field(default=0, description="초기 맥락 토큰 수")
    total_loaded_tokens: Optional[int] = Field(default=0, description="총 로드된 토큰 수")
    total_saved_tokens: Optional[int] = Field(default=0, description="절감된 토큰 수")
    created_at: str
    updated_at: str


class SessionContext(BaseModel):
    """세션 컨텍스트 (resume 시 반환)"""
    session_id: str
    project_id: str
    user_id: str
    status: str
    started_at: str
    summary: Optional[str] = None
    pins_count: int
    open_pins: int
    completed_pins: int
    pins: List[Union[PinResponse, PinCompact, dict]] = Field(
        default_factory=list,
        description="expand=true: PinResponse 전체, expand=false: PinCompact 요약"
    )


class SessionResumeParams(BaseModel):
    """세션 재개 파라미터"""
    project_id: str
    user_id: Optional[str] = Field(default=None)
    expand: bool = Field(default=False)
    limit: int = Field(default=10, ge=1, le=100)


class SessionEndParams(BaseModel):
    """세션 종료 파라미터"""
    project_id: str
    summary: Optional[str] = Field(default=None, max_length=5000)
