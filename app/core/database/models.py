"""데이터 모델 정의

This module defines the data models used throughout the application.
"""

import hashlib
import json
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class Memory(BaseModel):
    """메모리 데이터 모델"""

    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str = Field(min_length=10, max_length=50000)
    content_hash: str = Field(default="")
    project_id: Optional[str] = Field(default=None)
    category: str = Field(default="task")
    source: str
    client: Optional[str] = Field(default=None)
    embedding: bytes
    tags: Optional[str] = Field(default=None)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def model_post_init(self, __context):
        """모델 초기화 후 처리"""
        if not self.content_hash:
            self.content_hash = self.compute_hash(self.content)

    @staticmethod
    def compute_hash(content: str) -> str:
        """content의 SHA256 해시 계산"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def get_tags(self) -> Optional[List[str]]:
        """태그 JSON 문자열을 리스트로 변환"""
        if self.tags is None:
            return None
        try:
            return json.loads(self.tags)
        except json.JSONDecodeError:
            return None

    def set_tags(self, tags: Optional[List[str]]) -> None:
        """태그 리스트를 JSON 문자열로 설정"""
        if tags is None:
            self.tags = None
        else:
            self.tags = json.dumps(tags)


class SearchMetric(BaseModel):
    """검색 메트릭 데이터 모델"""

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    query: str
    query_length: int
    project_id: Optional[str] = None
    category: Optional[str] = None

    # 검색 결과
    result_count: int
    avg_similarity_score: Optional[float] = None
    top_similarity_score: Optional[float] = None

    # 성능
    response_time_ms: int
    embedding_time_ms: Optional[int] = None
    search_time_ms: Optional[int] = None

    # 압축
    response_format: Optional[str] = None  # 'full', 'compact', 'minimal'
    original_size_bytes: Optional[int] = None
    compressed_size_bytes: Optional[int] = None

    # 메타데이터
    user_agent: Optional[str] = None
    source: str  # 'mcp_stdio', 'mcp_pure', 'web_api'


class EmbeddingMetric(BaseModel):
    """임베딩 메트릭 데이터 모델"""

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    operation: str  # 'generate', 'batch_generate'

    # 성능
    count: int  # 생성된 임베딩 수
    total_time_ms: int
    avg_time_per_embedding_ms: float

    # 캐시
    cache_hit: bool

    # 리소스
    memory_usage_mb: Optional[float] = None
    model_name: str


class Alert(BaseModel):
    """알림 데이터 모델"""

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    alert_type: (
        str  # 'low_similarity', 'high_no_results', 'slow_response', 'embedding_failure'
    )
    severity: str  # 'warning', 'error', 'critical'
    message: str
    metric_value: float
    threshold_value: float
    status: str = "active"  # 'active', 'resolved'
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
