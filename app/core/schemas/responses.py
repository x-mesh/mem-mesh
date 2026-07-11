"""응답 스키마 정의"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConflictInfo(BaseModel):
    """충돌 감지 정보"""

    memory_id: str = Field(description="충돌하는 기존 메모리 ID")
    content_preview: str = Field(description="기존 메모리 내용 미리보기 (최대 200자)")
    contradiction_score: float = Field(
        description="모순 확률 (0.0~1.0, NLI 모델 미사용 시 0.0)"
    )
    similarity_score: float = Field(description="벡터 유사도 점수 (0.0~1.0)")


class AddResponse(BaseModel):
    """메모리 추가 응답"""

    id: str = Field(description="생성된 메모리 ID")
    status: str = Field(description="저장 상태 ('saved' 또는 'duplicate')")
    created_at: str = Field(description="생성 시간 (ISO8601 형식)")
    conflicts: Optional[List[ConflictInfo]] = Field(
        default=None,
        description="충돌 감지된 기존 메모리 목록 (conflict_detection 활성화 시)",
    )
    quality_hint: Optional[str] = Field(
        default=None,
        description=(
            "저장은 됐으나 대화 덤프/파생 가능 콘텐츠로 판별되어 improve 큐로 "
            "라우팅된 경우의 안내 (예: 'conversation_dump — improve 큐에 등록됨'). "
            "정상 콘텐츠는 None"
        ),
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "status": "saved",
                "created_at": "2024-01-15T10:30:00Z",
                "conflicts": None,
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
    client: Optional[str] = Field(
        default=None, description="생성 도구 (cursor, kiro, claude_code 등)"
    )
    tags: Optional[List[str]] = Field(default=None, description="태그 목록")
    anchors: Optional[Dict[str, Any]] = Field(
        default=None,
        description="git 앵커 (commit_hash/file_paths/branch) — 표시·수명 판단용",
    )
    # default False, not required: hub/federated rows never carry the column.
    is_starred: bool = Field(
        default=False,
        description="사용자가 표시한 별표 — 표시·필터 전용 (랭킹/주입에 영향 없음)",
    )
    origin: str = Field(
        default="local",
        description="결과 출처: 'local'(내 노드) 또는 'hub'(팀 hub, federated)",
    )
    title: Optional[str] = Field(
        default=None, description="hub enrichment 제목 (hub 결과에만)"
    )
    abstract: Optional[str] = Field(
        default=None, description="hub enrichment 요약 (hub 결과에만)"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "content": "Implemented user authentication with JWT tokens",
                "similarity_score": 0.85,
                "created_at": "2024-01-15T10:30:00Z",
                "project_id": "my-app",
                "category": "task",
                "source": "cursor",
                "tags": ["authentication", "jwt", "security"],
            }
        }
    }


class SearchResponse(BaseModel):
    """검색 응답"""

    results: List[SearchResult] = Field(description="검색 결과 목록")
    total: Optional[int] = Field(None, description="전체 결과 개수 (페이지네이션용)")
    suggestions: Optional[List[str]] = Field(
        None, description="검색 결과 부족 시 제안 쿼리"
    )
    related_memories: Optional[List[SearchResult]] = Field(
        None, description="관계 그래프 기반 관련 메모리"
    )
    hub_status: Optional[str] = Field(
        None,
        description=(
            "federated 검색 시 hub 상태: 'ok' | 'unavailable'(타임아웃/에러, "
            "로컬만 반환) | 'skipped'(hub 미설정). scope=local이면 None"
        ),
    )

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
                        "source": "cursor",
                    }
                ],
                "total": 150,
                "suggestions": None,
                "related_memories": None,
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
                "project_id": "my-app",
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
                    "source": "cursor",
                },
                "related_memories": [
                    {
                        "id": "456e7890-e89b-12d3-a456-426614174001",
                        "content": "Started working on authentication system",
                        "similarity_score": 0.75,
                        "relationship": "before",
                        "created_at": "2024-01-14T15:20:00Z",
                    }
                ],
                "timeline": [
                    "456e7890-e89b-12d3-a456-426614174001",
                    "123e4567-e89b-12d3-a456-426614174000",
                ],
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
                "status": "deleted",
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
                "status": "updated",
            }
        }
    }


class StatsResponse(BaseModel):
    """통계 조회 응답"""

    total_memories: int = Field(description="총 메모리 수")
    unique_projects: int = Field(description="고유 프로젝트 수")
    categories_breakdown: Dict[str, int] = Field(description="카테고리별 분포")
    sources_breakdown: Dict[str, int] = Field(description="소스별 분포")
    clients_breakdown: Dict[str, int] = Field(
        default_factory=dict, description="클라이언트 도구별 분포"
    )
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
                    "decision": 15,
                },
                "sources_breakdown": {"cursor": 90, "kiro": 35, "api": 25},
                "projects_breakdown": {"my-app": 60, "web-project": 45, "global": 45},
                "date_range": {"start": "2024-01-01", "end": "2024-01-31"},
                "query_time_ms": 15.5,
            }
        }
    }


class EnrichmentProjectCoverage(BaseModel):
    """프로젝트별 enrichment 커버리지"""

    project_id: str = Field(description="프로젝트 ID ('global'=미지정)")
    total: int = Field(description="프로젝트 메모리 수")
    enriched: int = Field(description="title이 채워진 메모리 수")
    coverage_ratio: float = Field(description="커버리지 비율 (0.0~1.0)")


class EnrichmentCoverage(BaseModel):
    """enrichment title 커버리지 요약"""

    total_memories: int = Field(description="전체 메모리 수")
    enriched_count: int = Field(description="title이 채워진 메모리 수")
    coverage_ratio: float = Field(description="전체 커버리지 비율 (0.0~1.0)")
    by_project: List[EnrichmentProjectCoverage] = Field(
        description="프로젝트별 커버리지"
    )


class HookEventsStats(BaseModel):
    """hook_events 축적 통계"""

    total_events: int = Field(description="총 hook 이벤트 수")
    prompt_events: int = Field(
        description="prompt가 기록된 UserPromptSubmit 이벤트 수 (replay 신호)"
    )
    by_event: Dict[str, int] = Field(description="이벤트명별 분포")
    by_project: Dict[str, int] = Field(description="프로젝트별 분포")
    first_event_at: Optional[str] = Field(
        None, description="가장 오래된 이벤트 시각 (ISO8601)"
    )
    last_event_at: Optional[str] = Field(
        None, description="가장 최근 이벤트 시각 (ISO8601)"
    )
    archived_prompt_events: int = Field(
        0,
        description="hook_events_archive에 보존된 prompt 이벤트 수 (prune 이후 장기 보관분)",
    )
    replay_prompts_total: int = Field(
        0, description="replay 가용 prompt 총량 (live + archive) — A3 판단 기준"
    )


class CoverageStatsResponse(BaseModel):
    """커버리지·축적 통계 응답 (enrichment 커버리지 + hook_events 축적)"""

    enrichment: EnrichmentCoverage = Field(description="enrichment title 커버리지")
    hook_events: HookEventsStats = Field(description="hook_events 축적 통계")
    query_time_ms: float = Field(description="쿼리 실행 시간 (밀리초)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "enrichment": {
                    "total_memories": 150,
                    "enriched_count": 120,
                    "coverage_ratio": 0.8,
                    "by_project": [
                        {
                            "project_id": "mem-mesh",
                            "total": 60,
                            "enriched": 55,
                            "coverage_ratio": 0.9167,
                        }
                    ],
                },
                "hook_events": {
                    "total_events": 4200,
                    "prompt_events": 1800,
                    "by_event": {
                        "UserPromptSubmit": 1800,
                        "SessionStart": 1200,
                        "Stop": 1200,
                    },
                    "by_project": {"mem-mesh": 3000, "web-project": 1200},
                    "first_event_at": "2026-06-21T09:00:00Z",
                    "last_event_at": "2026-07-05T18:30:00Z",
                },
                "query_time_ms": 12.3,
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
                "message": "Content must be between 10 and 50,000 characters",
                "details": {
                    "provided_length": 5,
                    "min_length": 10,
                    "max_length": 50000,
                },
            }
        }
    }
