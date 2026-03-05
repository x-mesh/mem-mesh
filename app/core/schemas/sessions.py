"""Session 관련 스키마 정의"""

from typing import Any, List, Optional, Union

from pydantic import BaseModel, Field, field_validator

from .pins import PinResponse


class PinCompact(BaseModel):
    """컴팩트 핀 정보 (expand=false용, 토큰 절약)"""

    id: str
    content: str = Field(description="80자로 제한된 내용 요약")
    importance: int
    status: str
    client: Optional[str] = None


class SessionCreate(BaseModel):
    """Session 생성 요청 (내부용)"""

    project_id: str
    user_id: str = Field(default="default")


class SessionResponse(BaseModel):
    """Session 응답"""

    id: str
    project_id: str
    user_id: str
    ide_session_id: Optional[str] = Field(
        default=None, description="IDE 네이티브 세션 ID (Claude Code session_id 등)"
    )
    client_type: Optional[str] = Field(
        default=None, description="IDE/도구 유형 (claude-ai, Cursor, Windsurf 등)"
    )
    started_at: str
    ended_at: Optional[str] = None
    status: str
    summary: Optional[str] = None
    initial_context_tokens: Optional[int] = Field(
        default=0, description="초기 맥락 토큰 수"
    )
    total_loaded_tokens: Optional[int] = Field(
        default=0, description="총 로드된 토큰 수"
    )
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
    pins: List[Union[dict, PinResponse, PinCompact]] = Field(
        default_factory=list,
        description="expand=true: PinResponse 전체, expand=false: PinCompact 요약, expand='smart': dict (4-Tier)",
    )


class SessionResumeParams(BaseModel):
    """세션 재개 파라미터"""

    project_id: str
    user_id: Optional[str] = Field(default=None)
    expand: Union[bool, str] = Field(
        default=False,
        description="false=compact, true=full, 'smart'=open/in_progress만 full",
    )
    limit: int = Field(default=10, ge=1, le=100)

    @field_validator("expand", mode="before")
    @classmethod
    def validate_expand(cls, v: Any) -> Union[bool, str]:
        if isinstance(v, bool):
            return v
        if isinstance(v, str) and v == "smart":
            return v
        raise ValueError("expand must be bool or 'smart'")


class SessionEndParams(BaseModel):
    """세션 종료 파라미터"""

    project_id: str
    summary: Optional[str] = Field(default=None, max_length=5000)
