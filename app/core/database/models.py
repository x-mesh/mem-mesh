"""데이터 모델 정의

This module defines the data models used throughout the application.
"""

import hashlib
import json
from datetime import datetime
from typing import Optional, List
from uuid import uuid4
from pydantic import BaseModel, Field


class Memory(BaseModel):
    """메모리 데이터 모델"""
    
    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str = Field(min_length=10, max_length=10000)
    content_hash: str = Field(default="")
    project_id: Optional[str] = Field(default=None)
    category: str = Field(default="task")
    source: str
    embedding: bytes
    tags: Optional[str] = Field(default=None)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + 'Z')
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + 'Z')
    
    def model_post_init(self, __context):
        """모델 초기화 후 처리"""
        if not self.content_hash:
            self.content_hash = self.compute_hash(self.content)
    
    @staticmethod
    def compute_hash(content: str) -> str:
        """content의 SHA256 해시 계산"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
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
