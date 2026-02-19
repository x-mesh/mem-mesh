"""
Score Normalization Service
임베딩 점수를 정규화하여 더 직관적인 범위로 변환
"""

import logging
from typing import List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScoreStats:
    """점수 통계"""
    min_score: float
    max_score: float
    mean_score: float
    std_score: float


class ScoreNormalizer:
    """
    임베딩 점수 정규화 서비스
    
    다양한 정규화 방법을 제공:
    1. Min-Max Normalization: [0, 1] 범위로 변환
    2. Z-Score Normalization: 표준 정규분포로 변환
    3. Sigmoid Normalization: S-curve 적용
    4. Percentile Normalization: 백분위 기반 변환
    """
    
    def __init__(
        self,
        method: str = "sigmoid",
        min_score: float = 0.0,
        max_score: float = 1.0,
        sigmoid_k: float = 10.0,
        sigmoid_threshold: float = 0.45,
    ):
        """
        Args:
            method: 정규화 방법 (minmax/zscore/sigmoid/percentile)
            min_score: 최소 점수 (minmax용)
            max_score: 최대 점수 (minmax용)
            sigmoid_k: sigmoid 기울기 (클수록 가파름)
            sigmoid_threshold: sigmoid 중심점 (모델 평균 유사도 근처)
        """
        self.method = method
        self.min_score = min_score
        self.max_score = max_score
        self.sigmoid_k = sigmoid_k
        self.sigmoid_threshold = sigmoid_threshold
        
        # 통계 캐시
        self._stats_cache: Optional[ScoreStats] = None
        
        logger.info(f"ScoreNormalizer initialized with method: {method}")
    
    def normalize(
        self,
        scores: List[float],
        method: Optional[str] = None
    ) -> List[float]:
        """
        점수 리스트를 정규화
        
        Args:
            scores: 원본 점수 리스트
            method: 정규화 방법 (None이면 기본값 사용)
            
        Returns:
            정규화된 점수 리스트
        """
        if not scores:
            return []
        
        method = method or self.method
        
        if method == "minmax":
            return self._minmax_normalize(scores)
        elif method == "zscore":
            return self._zscore_normalize(scores)
        elif method == "sigmoid":
            return self._sigmoid_normalize(scores)
        elif method == "percentile":
            return self._percentile_normalize(scores)
        else:
            logger.warning(f"Unknown normalization method: {method}, using sigmoid")
            return self._sigmoid_normalize(scores)
    
    def _minmax_normalize(self, scores: List[float]) -> List[float]:
        """
        Min-Max 정규화: [min, max] → [0, 1]
        
        Formula: (x - min) / (max - min)
        """
        if len(scores) == 1:
            return [0.5]  # 단일 값은 중간값으로
        
        min_val = min(scores)
        max_val = max(scores)
        
        if max_val == min_val:
            return [0.5] * len(scores)
        
        normalized = [
            (score - min_val) / (max_val - min_val)
            for score in scores
        ]
        
        return normalized
    
    def _zscore_normalize(self, scores: List[float]) -> List[float]:
        """
        Z-Score 정규화: 표준 정규분포로 변환
        
        Formula: (x - mean) / std
        Then map to [0, 1] using sigmoid
        """
        if len(scores) == 1:
            return [0.5]
        
        mean = sum(scores) / len(scores)
        variance = sum((x - mean) ** 2 for x in scores) / len(scores)
        std = variance ** 0.5
        
        if std == 0:
            return [0.5] * len(scores)
        
        # Z-score 계산
        z_scores = [(score - mean) / std for score in scores]
        
        # Sigmoid로 [0, 1] 범위로 변환
        import math
        normalized = [
            1 / (1 + math.exp(-z))
            for z in z_scores
        ]
        
        return normalized
    
    def _sigmoid_normalize(self, scores: List[float]) -> List[float]:
        """
        Sigmoid 정규화: S-curve 적용
        
        점수 분포를 더 균등하게 만들어 차이를 명확하게 함
        
        Formula: 1 / (1 + exp(-k * (x - threshold)))
        """
        import math
        
        k = self.sigmoid_k
        threshold = self.sigmoid_threshold
        
        normalized = []
        for score in scores:
            sigmoid_score = 1 / (1 + math.exp(-k * (score - threshold)))
            normalized.append(sigmoid_score)
        
        return normalized
    
    def _percentile_normalize(self, scores: List[float]) -> List[float]:
        """
        Percentile 정규화: 백분위 기반 변환
        
        각 점수를 전체 점수 중 몇 번째인지로 변환
        """
        if len(scores) == 1:
            return [0.5]
        
        # 점수와 인덱스를 함께 정렬
        sorted_scores = sorted(enumerate(scores), key=lambda x: x[1])
        
        # 백분위 계산
        normalized = [0.0] * len(scores)
        for rank, (original_idx, _) in enumerate(sorted_scores):
            percentile = rank / (len(scores) - 1)
            normalized[original_idx] = percentile
        
        return normalized
    
    def normalize_single(self, score: float, context_scores: List[float]) -> float:
        """
        단일 점수를 컨텍스트 점수들과 함께 정규화
        
        Args:
            score: 정규화할 점수
            context_scores: 비교 대상 점수들
            
        Returns:
            정규화된 점수
        """
        all_scores = context_scores + [score]
        normalized = self.normalize(all_scores)
        return normalized[-1]
    
    def get_stats(self, scores: List[float]) -> ScoreStats:
        """점수 통계 계산"""
        if not scores:
            return ScoreStats(0.0, 0.0, 0.0, 0.0)
        
        min_score = min(scores)
        max_score = max(scores)
        mean_score = sum(scores) / len(scores)
        
        variance = sum((x - mean_score) ** 2 for x in scores) / len(scores)
        std_score = variance ** 0.5
        
        return ScoreStats(min_score, max_score, mean_score, std_score)
    
    def auto_calibrate(self, scores: List[float]) -> dict:
        """
        점수 분포를 분석하여 최적의 정규화 방법 추천
        
        Returns:
            {
                "recommended_method": str,
                "stats": ScoreStats,
                "reason": str
            }
        """
        stats = self.get_stats(scores)
        
        # 점수 범위 분석
        score_range = stats.max_score - stats.min_score
        
        # 추천 로직
        if score_range < 0.1:
            # 점수가 매우 좁은 범위에 몰려있음
            return {
                "recommended_method": "sigmoid",
                "stats": stats,
                "reason": "점수가 좁은 범위에 집중되어 있어 sigmoid로 분산 필요"
            }
        elif stats.std_score < 0.05:
            # 표준편차가 작음 (점수가 비슷함)
            return {
                "recommended_method": "percentile",
                "stats": stats,
                "reason": "점수가 비슷하여 percentile로 순위 기반 정규화 필요"
            }
        elif score_range > 0.5:
            # 점수 범위가 넓음
            return {
                "recommended_method": "minmax",
                "stats": stats,
                "reason": "점수 범위가 넓어 minmax로 정규화 적합"
            }
        else:
            # 일반적인 경우
            return {
                "recommended_method": "sigmoid",
                "stats": stats,
                "reason": "일반적인 분포로 sigmoid 정규화 적합"
            }


# 전역 인스턴스
_normalizer: Optional[ScoreNormalizer] = None


def get_score_normalizer(
    method: str = "sigmoid",
    sigmoid_k: Optional[float] = None,
    sigmoid_threshold: Optional[float] = None,
) -> ScoreNormalizer:
    """전역 ScoreNormalizer 인스턴스 반환 (config에서 기본값 로드)"""
    global _normalizer

    if sigmoid_k is None or sigmoid_threshold is None:
        try:
            from ..config import get_settings
            settings = get_settings()
            sigmoid_k = sigmoid_k if sigmoid_k is not None else settings.sigmoid_k
            sigmoid_threshold = sigmoid_threshold if sigmoid_threshold is not None else settings.sigmoid_threshold
        except Exception:
            sigmoid_k = sigmoid_k if sigmoid_k is not None else 10.0
            sigmoid_threshold = sigmoid_threshold if sigmoid_threshold is not None else 0.45

    if _normalizer is None or _normalizer.method != method:
        _normalizer = ScoreNormalizer(
            method=method,
            sigmoid_k=sigmoid_k,
            sigmoid_threshold=sigmoid_threshold,
        )
    return _normalizer
