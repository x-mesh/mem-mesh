"""
Memory Relations 스키마.

메모리 간 관계를 정의하는 Pydantic 모델들.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class RelationType(str, Enum):
    """관계 유형"""
    RELATED = "related"        # 일반적인 관련성
    PARENT = "parent"          # 부모-자식 관계 (source가 parent)
    CHILD = "child"            # 자식-부모 관계 (source가 child)
    SUPERSEDES = "supersedes"  # source가 target을 대체
    REFERENCES = "references"  # source가 target을 참조
    DEPENDS_ON = "depends_on"  # source가 target에 의존
    SIMILAR = "similar"        # 유사한 내용


class RelationCreate(BaseModel):
    """관계 생성 요청"""
    source_id: str = Field(..., description="소스 메모리 ID")
    target_id: str = Field(..., description="타겟 메모리 ID")
    relation_type: RelationType = Field(default=RelationType.RELATED, description="관계 유형")
    strength: float = Field(default=1.0, ge=0.0, le=1.0, description="관계 강도 (0.0-1.0)")
    metadata: Optional[dict] = Field(default=None, description="추가 메타데이터")


class RelationUpdate(BaseModel):
    """관계 수정 요청"""
    relation_type: Optional[RelationType] = None
    strength: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    metadata: Optional[dict] = None


class Relation(BaseModel):
    """관계 모델"""
    id: str
    source_id: str
    target_id: str
    relation_type: RelationType
    strength: float
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RelationWithMemory(Relation):
    """메모리 정보가 포함된 관계"""
    source_content: Optional[str] = None
    source_project_id: Optional[str] = None
    target_content: Optional[str] = None
    target_project_id: Optional[str] = None


class RelationGraph(BaseModel):
    """관계 그래프 응답"""
    center_id: str
    relations: List[RelationWithMemory]
    depth: int
    total_nodes: int
