"""응답 스키마 정의"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class AddResponse(BaseModel):
    """메모리 추가 응답"""
    id: str = Field(description="생성된 메모리 ID")
    status: str = Field(description="저장 상태 ('saved' 또는 'duplicate')")
    created_at: str = Field(description="생성 시간 (ISO8601 형식)")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "status": "saved",
                "created_at": "2024-01-15T10:30:00Z"
            }
        }
    }


class SearchResult(BaseModel):
    """검색 결과 항목"""
    id: str = Field(description="메모리 ID")
    content: str = Field(description="메모리 내용")
    similarity_score: float = Field(description="유사도 점수 (0.0 ~ 1.0)")
    created_at: str = Field(description="생성 시간")
    project_id: Optional[str] = Field(description="프로젝트 ID")
    category: str = Field(description="카테고리")
    source: str = Field(description="생성 소스")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "content": "Implemented user authentication with JWT tokens",
                "similarity_score": 0.85,
                "created_at": "2024-01-15T10:30:00Z",
                "project_id": "my-app",
                "category": "task",
                "source": "cursor"
            }
        }
    }


class SearchResponse(BaseModel):
    """검색 응답"""
    results: List[SearchResult] = Field(description="검색 결과 목록")
    total: Optional[int] = Field(None, description="전체 결과 개수 (페이지네이션용)")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "results": [
                    {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "content": "Implemented user authentication with JWT tokens",
                        "similarity_score": 0.85,
                        "created_at": "2024-01-15T10:30:00Z",
                        "project_id": "my-app",
                        "category": "task",
                        "source": "cursor"
                    }
                ],
                "total": 150
            }
        }
    }


class RelatedMemory(BaseModel):
    """관련 메모리 항목"""
    id: str = Field(description="메모리 ID")
    content: str = Field(description="메모리 내용")
    similarity_score: float = Field(description="유사도 점수")
    relationship: str = Field(description="관계 유형 ('before', 'after', 'similar')")
    created_at: str = Field(description="생성 시간")
    category: Optional[str] = Field(None, description="카테고리")
    project_id: Optional[str] = Field(None, description="프로젝트 ID")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "456e7890-e89b-12d3-a456-426614174001",
                "content": "Started working on authentication system",
                "similarity_score": 0.75,
                "relationship": "before",
                "created_at": "2024-01-14T15:20:00Z",
                "category": "task",
                "project_id": "my-app"
            }
        }
    }


class ContextResponse(BaseModel):
    """맥락 조회 응답"""
    primary_memory: SearchResult = Field(description="주요 메모리")
    related_memories: List[RelatedMemory] = Field(description="관련 메모리 목록")
    timeline: List[str] = Field(description="시간순 메모리 ID 목록")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "primary_memory": {
                    "id": "123e4567-e89b-12d3-a456-426614174000",
                    "content": "Implemented user authentication with JWT tokens",
                    "similarity_score": 1.0,
                    "created_at": "2024-01-15T10:30:00Z",
                    "project_id": "my-app",
                    "category": "task",
                    "source": "cursor"
                },
                "related_memories": [
                    {
                        "id": "456e7890-e89b-12d3-a456-426614174001",
                        "content": "Started working on authentication system",
                        "similarity_score": 0.75,
                        "relationship": "before",
                        "created_at": "2024-01-14T15:20:00Z"
                    }
                ],
                "timeline": [
                    "456e7890-e89b-12d3-a456-426614174001",
                    "123e4567-e89b-12d3-a456-426614174000"
                ]
            }
        }
    }


class DeleteResponse(BaseModel):
    """메모리 삭제 응답"""
    id: str = Field(description="삭제된 메모리 ID")
    status: str = Field(description="삭제 상태 ('deleted')")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "status": "deleted"
            }
        }
    }


class UpdateResponse(BaseModel):
    """메모리 업데이트 응답"""
    id: str = Field(description="업데이트된 메모리 ID")
    status: str = Field(description="업데이트 상태 ('updated')")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "status": "updated"
            }
        }
    }


class StatsResponse(BaseModel):
    """통계 조회 응답"""
    total_memories: int = Field(description="총 메모리 수")
    unique_projects: int = Field(description="고유 프로젝트 수")
    categories_breakdown: Dict[str, int] = Field(description="카테고리별 분포")
    sources_breakdown: Dict[str, int] = Field(description="소스별 분포")
    projects_breakdown: Dict[str, int] = Field(description="프로젝트별 분포")
    date_range: Optional[Dict[str, str]] = Field(None, description="조회 날짜 범위")
    query_time_ms: float = Field(description="쿼리 실행 시간 (밀리초)")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "total_memories": 150,
                "unique_projects": 5,
                "categories_breakdown": {
                    "task": 80,
                    "bug": 30,
                    "idea": 25,
                    "decision": 15
                },
                "sources_breakdown": {
                    "cursor": 90,
                    "kiro": 35,
                    "api": 25
                },
                "projects_breakdown": {
                    "my-app": 60,
                    "web-project": 45,
                    "global": 45
                },
                "date_range": {
                    "start": "2024-01-01",
                    "end": "2024-01-31"
                },
                "query_time_ms": 15.5
            }
        }
    }


class ErrorResponse(BaseModel):
    """에러 응답"""
    error: str = Field(description="에러 코드")
    message: str = Field(description="에러 메시지")
    details: Optional[Dict[str, Any]] = Field(None, description="추가 에러 정보")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "error": "INVALID_CONTENT_LENGTH",
                "message": "Content must be between 10 and 10,000 characters",
                "details": {
                    "provided_length": 5,
                    "min_length": 10,
                    "max_length": 10000
                }
            }
        }
    }
