"""LongMemEval 벤치마크 데이터 모델"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class BenchmarkItem(BaseModel):
    """데이터셋 1개 항목"""

    question_id: str = Field(description="질문 고유 ID")
    question_type: str = Field(description="질문 유형 (single-session-user-centric 등)")
    question: str = Field(description="질문 텍스트")
    answer: str = Field(description="정답 텍스트")
    question_date: Optional[str] = Field(
        default=None, description="질문 시점 날짜"
    )
    haystack_sessions: List[List[str]] = Field(
        description="대화 세션 목록 (각 세션 = 발화 리스트)"
    )
    haystack_dates: List[str] = Field(
        description="각 세션의 날짜"
    )
    answer_session_ids: List[int] = Field(
        description="정답이 포함된 세션 인덱스 목록"
    )


class RetrievalMetrics(BaseModel):
    """검색 메트릭"""

    recall_any: Dict[int, float] = Field(
        default_factory=dict,
        description="recall_any@k: 정답 세션 중 하나라도 검색되었는지",
    )
    recall_all: Dict[int, float] = Field(
        default_factory=dict,
        description="recall_all@k: 정답 세션이 모두 검색되었는지",
    )
    ndcg: Dict[int, float] = Field(
        default_factory=dict, description="NDCG@k"
    )
    retrieval_time_ms: float = Field(
        default=0.0, description="검색 소요 시간 (밀리초)"
    )


class QuestionResult(BaseModel):
    """1개 질문의 결과"""

    question_id: str
    question_type: str
    question: str
    answer: str
    hypothesis: str = Field(default="", description="LLM 생성 답변")
    retrieved_session_ids: List[int] = Field(
        default_factory=list, description="검색된 세션 ID 목록"
    )
    retrieval_metrics: RetrievalMetrics = Field(
        default_factory=RetrievalMetrics
    )
    eval_label: Optional[int] = Field(
        default=None, description="평가 결과 (0: 오답, 1: 정답)"
    )
    error: Optional[str] = Field(
        default=None, description="에러 메시지 (실패 시)"
    )


class CategoryReport(BaseModel):
    """카테고리별 결과 요약"""

    category: str
    total: int
    correct: int
    accuracy: float
    avg_recall_any_at_10: float = 0.0
    avg_recall_all_at_10: float = 0.0
    avg_retrieval_time_ms: float = 0.0


class BenchmarkReport(BaseModel):
    """최종 벤치마크 리포트"""

    experiment_name: str
    language: str
    indexing_strategy: str
    total_questions: int
    evaluated_questions: int
    overall_accuracy: float
    category_results: List[CategoryReport] = Field(default_factory=list)
    avg_retrieval_metrics: RetrievalMetrics = Field(
        default_factory=RetrievalMetrics
    )
    config_summary: Dict[str, str] = Field(default_factory=dict)
