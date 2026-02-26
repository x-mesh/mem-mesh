"""
Search Scoring System for mem-mesh

확장 가능한 검색 점수 계산 시스템
- 다양한 스코어러를 조합하여 최종 점수 계산
- 새로운 스코어링 로직을 쉽게 추가 가능
"""

import re
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class ScoringContext:
    """스코어링에 필요한 컨텍스트 정보"""
    query: str
    content: str
    vector_score: float  # 벡터 유사도 점수 (0.0 ~ 1.0)
    category: Optional[str] = None
    project_id: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoringResult:
    """스코어링 결과"""
    final_score: float
    breakdown: Dict[str, float]  # 각 스코어러별 점수
    should_include: bool = True  # 결과에 포함할지 여부
    reason: Optional[str] = None  # 제외 사유


class BaseScorer(ABC):
    """스코어러 기본 클래스"""
    
    def __init__(self, weight: float = 1.0, enabled: bool = True):
        self.weight = weight
        self.enabled = enabled
    
    @property
    @abstractmethod
    def name(self) -> str:
        """스코어러 이름"""
        pass
    
    @abstractmethod
    def calculate(self, context: ScoringContext) -> float:
        """점수 계산 (0.0 ~ 1.0 범위)"""
        pass
    
    def should_exclude(self, context: ScoringContext) -> Optional[str]:
        """결과에서 제외해야 하는지 확인. 제외 사유 반환, None이면 포함"""
        return None


class ExactMatchScorer(BaseScorer):
    """정확한 텍스트 매칭 스코어러"""
    
    def __init__(self, 
                 weight: float = 1.0,
                 substring_bonus: float = 0.15,
                 word_boundary_bonus: float = 0.10,
                 enabled: bool = True):
        super().__init__(weight, enabled)
        self.substring_bonus = substring_bonus
        self.word_boundary_bonus = word_boundary_bonus
    
    @property
    def name(self) -> str:
        return "exact_match"
    
    def calculate(self, context: ScoringContext) -> float:
        if not self.enabled:
            return 0.0
        
        query_lower = context.query.lower()
        content_lower = context.content.lower()
        
        score = 0.0
        
        # 1. 부분 문자열 매칭
        if query_lower in content_lower:
            score += self.substring_bonus
            logger.debug(f"Substring match: '{context.query}' in content")
        
        # 2. 단어 경계 매칭 (더 정확한 매칭)
        word_boundary_pattern = r'\b' + re.escape(query_lower) + r'\b'
        if re.search(word_boundary_pattern, content_lower):
            score += self.word_boundary_bonus
            logger.debug(f"Word boundary match: '{context.query}'")
        
        return score


class ContentQualityScorer(BaseScorer):
    """콘텐츠 품질 스코어러"""
    
    def __init__(self,
                 weight: float = 1.0,
                 min_length: int = 5,
                 simple_responses: Optional[set] = None,
                 simple_response_penalty: float = 0.2,
                 enabled: bool = True):
        super().__init__(weight, enabled)
        self.min_length = min_length
        self.simple_responses = simple_responses or {
            "understood", "ok", "okay", "yes", "no", "done", "sure", "thanks",
            "got it", "noted", "ack", "roger", "yep", "nope", "fine",
            "확인", "알겠습니다", "네", "예", "아니오", "아니요",
            "감사합니다", "알겠어요", "좋아", "좋아요",
            "넵", "완료", "확인했습니다", "오케이",
        }
        self.simple_response_penalty = simple_response_penalty
    
    @property
    def name(self) -> str:
        return "content_quality"
    
    def calculate(self, context: ScoringContext) -> float:
        """품질 점수 반환 (1.0이 최고, 낮을수록 페널티)"""
        if not self.enabled:
            return 1.0
        
        content = context.content.strip()
        
        # 단순 응답인 경우 페널티
        if content.lower() in self.simple_responses:
            return self.simple_response_penalty
        
        return 1.0
    
    def should_exclude(self, context: ScoringContext) -> Optional[str]:
        """제외 조건 확인"""
        content = context.content.strip()
        
        # 최소 길이 미달
        if len(content) < self.min_length:
            return f"Content too short: {len(content)} < {self.min_length}"
        
        # 단순 응답이면서 검색어와 정확히 매칭되지 않는 경우
        if content.lower() in self.simple_responses:
            if context.query.lower() not in content.lower():
                return f"Simple response without exact match: '{content}'"
        
        return None


class RecencyScorer(BaseScorer):
    """최신성 스코어러"""
    
    def __init__(self, weight: float = 0.0, enabled: bool = True):
        super().__init__(weight, enabled)
    
    @property
    def name(self) -> str:
        return "recency"
    
    def calculate(self, context: ScoringContext) -> float:
        """최신성 점수 (metadata에서 recency_score 사용)"""
        if not self.enabled or self.weight == 0:
            return 0.0
        
        return context.metadata.get('recency_score', 0.5)


class CategoryBoostScorer(BaseScorer):
    """카테고리 부스트 스코어러"""
    
    def __init__(self,
                 weight: float = 1.0,
                 category_boosts: Optional[Dict[str, float]] = None,
                 enabled: bool = True):
        super().__init__(weight, enabled)
        self.category_boosts = category_boosts or {
            "bug": 0.05,
            "decision": 0.03,
            "code_snippet": 0.02,
        }
    
    @property
    def name(self) -> str:
        return "category_boost"
    
    def calculate(self, context: ScoringContext) -> float:
        if not self.enabled or not context.category:
            return 0.0
        
        return self.category_boosts.get(context.category, 0.0)


class TagMatchScorer(BaseScorer):
    """태그 매칭 스코어러"""
    
    def __init__(self,
                 weight: float = 1.0,
                 tag_match_bonus: float = 0.05,
                 enabled: bool = True):
        super().__init__(weight, enabled)
        self.tag_match_bonus = tag_match_bonus
    
    @property
    def name(self) -> str:
        return "tag_match"
    
    def calculate(self, context: ScoringContext) -> float:
        if not self.enabled or not context.tags:
            return 0.0
        
        query_lower = context.query.lower()
        score = 0.0
        
        for tag in context.tags:
            if query_lower in tag.lower() or tag.lower() in query_lower:
                score += self.tag_match_bonus
        
        return min(score, 0.15)  # 최대 0.15


class ScoringPipeline:
    """스코어링 파이프라인 - 여러 스코어러를 조합"""
    
    def __init__(self, scorers: Optional[List[BaseScorer]] = None):
        self.scorers = scorers or self._default_scorers()
    
    def _default_scorers(self) -> List[BaseScorer]:
        """기본 스코어러 구성"""
        return [
            ExactMatchScorer(weight=1.0),
            ContentQualityScorer(weight=1.0),
            RecencyScorer(weight=0.1),  # 최소 가중치로 시간 인식 활성화
            CategoryBoostScorer(weight=1.0),
            TagMatchScorer(weight=1.0),
        ]
    
    def add_scorer(self, scorer: BaseScorer) -> 'ScoringPipeline':
        """스코어러 추가"""
        self.scorers.append(scorer)
        return self
    
    def remove_scorer(self, name: str) -> 'ScoringPipeline':
        """스코어러 제거"""
        self.scorers = [s for s in self.scorers if s.name != name]
        return self
    
    def get_scorer(self, name: str) -> Optional[BaseScorer]:
        """스코어러 조회"""
        for scorer in self.scorers:
            if scorer.name == name:
                return scorer
        return None
    
    def set_recency_weight(self, weight: float) -> 'ScoringPipeline':
        """최신성 가중치 설정"""
        recency_scorer = self.get_scorer("recency")
        if recency_scorer:
            recency_scorer.weight = weight
            recency_scorer.enabled = weight > 0
        return self
    
    def calculate(self, context: ScoringContext) -> ScoringResult:
        """최종 점수 계산"""
        breakdown = {"vector": context.vector_score}
        
        # 1. 제외 조건 확인
        for scorer in self.scorers:
            if scorer.enabled:
                exclude_reason = scorer.should_exclude(context)
                if exclude_reason:
                    logger.debug(f"Excluding result: {exclude_reason}")
                    return ScoringResult(
                        final_score=0.0,
                        breakdown=breakdown,
                        should_include=False,
                        reason=exclude_reason
                    )
        
        # 2. 각 스코어러의 점수 계산
        bonus_score = 0.0
        quality_multiplier = 1.0
        
        for scorer in self.scorers:
            if not scorer.enabled:
                continue
            
            score = scorer.calculate(context)
            breakdown[scorer.name] = score
            
            if scorer.name == "content_quality":
                # 품질 점수는 곱셈으로 적용
                quality_multiplier = score
            else:
                # 나머지는 가중치 적용하여 합산
                bonus_score += score * scorer.weight
        
        # 3. 최종 점수 계산
        # (벡터 점수 + 보너스) * 품질 배수
        final_score = (context.vector_score + bonus_score) * quality_multiplier
        final_score = max(0.0, min(1.0, final_score))  # 0~1 범위로 제한
        
        breakdown["final"] = final_score
        
        return ScoringResult(
            final_score=final_score,
            breakdown=breakdown,
            should_include=True
        )


# 편의를 위한 기본 파이프라인 인스턴스
default_pipeline = ScoringPipeline()


def calculate_score(
    query: str,
    content: str,
    vector_score: float,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
    recency_weight: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None
) -> ScoringResult:
    """편의 함수: 기본 파이프라인으로 점수 계산"""
    pipeline = ScoringPipeline()
    pipeline.set_recency_weight(recency_weight)
    
    context = ScoringContext(
        query=query,
        content=content,
        vector_score=vector_score,
        category=category,
        tags=tags,
        metadata=metadata or {}
    )
    
    return pipeline.calculate(context)
