"""Project 관련 스키마 정의"""

import re
from typing import List, Optional

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


class ProjectRenameRequest(BaseModel):
    """프로젝트 이름 변경/병합 요청.

    target_id가 이미 존재하면 병합(흡수), 없으면 단순 rename이다.
    """

    target_id: str = Field(min_length=1, max_length=100)
    dry_run: bool = Field(
        default=False,
        description="True면 아무것도 쓰지 않고 이동 대상 건수만 반환한다",
    )

    @field_validator("target_id")
    @classmethod
    def validate_target_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "target_id는 영문/숫자/하이픈/언더스코어만 사용할 수 있습니다"
            )
        return v


class ProjectRenameTableResult(BaseModel):
    """테이블 하나에 대한 이동 결과"""

    table: str
    moved: int = 0
    # project_id가 UNIQUE인 설정성 테이블(구독/스케줄 등)에서 target 행이 이미
    # 있어 옮길 수 없던 source 행 수. 이 행들은 삭제된다(target 것이 유지).
    dropped: int = 0


class ProjectRenameResult(BaseModel):
    """프로젝트 rename/merge 결과"""

    source_id: str
    target_id: str
    merged: bool  # target이 이미 존재했는가 (= 병합)
    dry_run: bool
    total_moved: int = 0
    total_dropped: int = 0
    sessions_ended: int = 0  # 활성 세션 충돌로 ended 처리된 세션 수
    tables: List[ProjectRenameTableResult] = Field(default_factory=list)
