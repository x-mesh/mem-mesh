"""context-token-optimization 관련 스키마 정의

Requirements: 전체
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class TokenInfo(BaseModel):
    """토큰 정보"""
    loaded_tokens: int = Field(..., description="실제 로드된 토큰 수")
    unloaded_tokens: int = Field(..., description="지연 로딩으로 절감된 토큰 수")
    estimated_total: int = Field(..., description="예상 총 토큰 수")
    savings_rate: float = Field(..., ge=0.0, le=1.0, description="절감률 (0.0-1.0)")


class SessionStatistics(BaseModel):
    """세션 통계"""
    total_sessions: int = Field(..., description="총 세션 수")
    avg_duration_hours: float = Field(..., description="평균 세션 지속 시간 (시간)")
    avg_pins_per_session: float = Field(..., description="세션당 평균 핀 수")
    importance_distribution: Dict[int, int] = Field(..., description="중요도별 핀 분포")
    avg_token_savings_rate: float = Field(..., description="평균 토큰 절감률")


class PinStatistics(BaseModel):
    """핀 통계"""
    total: int = Field(..., description="총 핀 수")
    by_status: Dict[str, int] = Field(..., description="상태별 핀 분포")
    by_importance: Dict[int, int] = Field(..., description="중요도별 핀 분포")
    avg_lead_time_hours: Optional[float] = Field(None, description="평균 리드 타임 (시간)")
    promotion_candidates: int = Field(..., description="승격 후보 핀 수 (importance >= 4)")


class OptimizedSessionContext(BaseModel):
    """최적화된 세션 맥락"""
    session_context: Any = Field(..., description="세션 컨텍스트")
    token_info: TokenInfo = Field(..., description="토큰 정보")
    optimization_applied: bool = Field(..., description="최적화 적용 여부")
    recommendations: List[str] = Field(default_factory=list, description="권장사항 목록")


class SessionStatRecord(BaseModel):
    """세션 통계 레코드"""
    id: str = Field(..., description="레코드 ID")
    session_id: str = Field(..., description="세션 ID")
    timestamp: str = Field(..., description="타임스탬프")
    event_type: str = Field(..., description="이벤트 타입 (resume, search, pin_add, end)")
    tokens_loaded: int = Field(..., description="로드된 토큰 수")
    tokens_saved: int = Field(..., description="절감된 토큰 수")
    context_depth: Optional[int] = Field(None, description="맥락 깊이")
    created_at: str = Field(..., description="생성 시각")


class TokenUsageRecord(BaseModel):
    """토큰 사용량 레코드"""
    id: str = Field(..., description="레코드 ID")
    project_id: str = Field(..., description="프로젝트 ID")
    session_id: Optional[str] = Field(None, description="세션 ID")
    operation_type: str = Field(..., description="작업 타입 (session_resume, search, context_load)")
    query: Optional[str] = Field(None, description="검색 쿼리")
    tokens_used: int = Field(..., description="사용된 토큰 수")
    tokens_saved: int = Field(default=0, description="절감된 토큰 수")
    optimization_applied: bool = Field(default=False, description="최적화 적용 여부")
    created_at: str = Field(..., description="생성 시각")


class TokenSavingsReport(BaseModel):
    """토큰 절감 리포트"""
    total_tokens: int = Field(..., description="총 토큰 수")
    loaded_tokens: int = Field(..., description="로드된 토큰 수")
    saved_tokens: int = Field(..., description="절감된 토큰 수")
    savings_rate: float = Field(..., ge=0.0, le=1.0, description="절감률")
    optimization_details: Dict[str, Any] = Field(default_factory=dict, description="최적화 상세 정보")


class PromotionSuggestion(BaseModel):
    """승격 제안"""
    pin_id: str = Field(..., description="핀 ID")
    importance: int = Field(..., ge=1, le=5, description="중요도")
    reason: str = Field(..., description="승격 제안 이유")
    auto_promote: bool = Field(default=False, description="자동 승격 여부")
