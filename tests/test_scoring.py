#!/usr/bin/env python3
"""
스코어링 시스템 테스트
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.services.scoring import (
    CategoryBoostScorer,
    ContentQualityScorer,
    ExactMatchScorer,
    ScoringContext,
    ScoringPipeline,
    TagMatchScorer,
    calculate_score,
)


class TestExactMatchScorer:
    """ExactMatchScorer 테스트"""

    def test_substring_match(self):
        """부분 문자열 매칭 테스트"""
        scorer = ExactMatchScorer()
        context = ScoringContext(
            query="threshold", content="The threshold value is 0.5", vector_score=0.7
        )
        score = scorer.calculate(context)
        assert score >= 0.15  # substring bonus

    def test_word_boundary_match(self):
        """단어 경계 매칭 테스트"""
        scorer = ExactMatchScorer()
        context = ScoringContext(
            query="threshold", content="threshold is important", vector_score=0.7
        )
        score = scorer.calculate(context)
        assert score >= 0.25  # substring + word boundary

    def test_no_match(self):
        """매칭 없음 테스트"""
        scorer = ExactMatchScorer()
        context = ScoringContext(
            query="threshold", content="understood", vector_score=0.7
        )
        score = scorer.calculate(context)
        assert score == 0.0

    def test_case_insensitive(self):
        """대소문자 무시 테스트"""
        scorer = ExactMatchScorer()
        context = ScoringContext(
            query="Threshold", content="THRESHOLD value", vector_score=0.7
        )
        score = scorer.calculate(context)
        assert score >= 0.15


class TestContentQualityScorer:
    """ContentQualityScorer 테스트"""

    def test_normal_content(self):
        """일반 콘텐츠 테스트"""
        scorer = ContentQualityScorer()
        context = ScoringContext(
            query="test", content="This is a normal content", vector_score=0.7
        )
        score = scorer.calculate(context)
        assert score == 1.0

    def test_simple_response_penalty(self):
        """단순 응답 페널티 테스트"""
        scorer = ContentQualityScorer()
        context = ScoringContext(query="test", content="understood", vector_score=0.7)
        score = scorer.calculate(context)
        assert score == 0.2  # penalty

    def test_should_exclude_short_content(self):
        """짧은 콘텐츠 제외 테스트"""
        scorer = ContentQualityScorer(min_length=10)
        context = ScoringContext(query="test", content="hi", vector_score=0.7)
        reason = scorer.should_exclude(context)
        assert reason is not None
        assert "too short" in reason

    def test_should_exclude_simple_response_without_match(self):
        """매칭 없는 단순 응답 제외 테스트"""
        scorer = ContentQualityScorer()
        context = ScoringContext(
            query="threshold", content="understood", vector_score=0.7
        )
        reason = scorer.should_exclude(context)
        assert reason is not None
        assert "Simple response" in reason

    def test_should_include_simple_response_with_match(self):
        """매칭 있는 단순 응답 포함 테스트"""
        scorer = ContentQualityScorer()
        context = ScoringContext(
            query="understood", content="understood", vector_score=0.7
        )
        reason = scorer.should_exclude(context)
        assert reason is None  # 포함되어야 함


class TestCategoryBoostScorer:
    """CategoryBoostScorer 테스트"""

    def test_bug_category_boost(self):
        """버그 카테고리 부스트 테스트"""
        scorer = CategoryBoostScorer()
        context = ScoringContext(
            query="test", content="test content", vector_score=0.7, category="bug"
        )
        score = scorer.calculate(context)
        assert score == 0.05

    def test_no_category(self):
        """카테고리 없음 테스트"""
        scorer = CategoryBoostScorer()
        context = ScoringContext(
            query="test", content="test content", vector_score=0.7, category=None
        )
        score = scorer.calculate(context)
        assert score == 0.0


class TestTagMatchScorer:
    """TagMatchScorer 테스트"""

    def test_tag_match(self):
        """태그 매칭 테스트"""
        scorer = TagMatchScorer()
        context = ScoringContext(
            query="threshold",
            content="test content",
            vector_score=0.7,
            tags=["threshold", "search"],
        )
        score = scorer.calculate(context)
        assert score >= 0.05

    def test_no_tags(self):
        """태그 없음 테스트"""
        scorer = TagMatchScorer()
        context = ScoringContext(
            query="test", content="test content", vector_score=0.7, tags=None
        )
        score = scorer.calculate(context)
        assert score == 0.0


class TestScoringPipeline:
    """ScoringPipeline 테스트"""

    def test_default_pipeline(self):
        """기본 파이프라인 테스트"""
        pipeline = ScoringPipeline()
        context = ScoringContext(
            query="threshold",
            content="The threshold value is important",
            vector_score=0.7,
        )
        result = pipeline.calculate(context)

        assert result.should_include
        assert result.final_score > 0.7  # 보너스가 적용되어야 함
        assert "exact_match" in result.breakdown

    def test_exclude_simple_response(self):
        """단순 응답 제외 테스트"""
        pipeline = ScoringPipeline()
        context = ScoringContext(
            query="threshold", content="understood", vector_score=0.86
        )
        result = pipeline.calculate(context)

        assert not result.should_include
        assert result.reason is not None

    def test_add_custom_scorer(self):
        """커스텀 스코어러 추가 테스트"""
        from app.core.services.scoring import BaseScorer

        class CustomScorer(BaseScorer):
            @property
            def name(self):
                return "custom"

            def calculate(self, context):
                return 0.1

        pipeline = ScoringPipeline()
        pipeline.add_scorer(CustomScorer())

        context = ScoringContext(
            query="test", content="test content here", vector_score=0.7
        )
        result = pipeline.calculate(context)

        assert "custom" in result.breakdown
        assert result.breakdown["custom"] == 0.1

    def test_recency_weight(self):
        """최신성 가중치 테스트"""
        pipeline = ScoringPipeline()
        pipeline.set_recency_weight(0.3)

        context = ScoringContext(
            query="test",
            content="test content here",
            vector_score=0.7,
            metadata={"recency_score": 1.0},
        )
        result = pipeline.calculate(context)

        assert result.final_score > 0.7  # 최신성 보너스 적용


class TestCalculateScoreFunction:
    """calculate_score 편의 함수 테스트"""

    def test_basic_usage(self):
        """기본 사용법 테스트"""
        result = calculate_score(
            query="threshold", content="The threshold is set", vector_score=0.7
        )

        assert result.should_include
        assert result.final_score > 0.7

    def test_with_category(self):
        """카테고리 포함 테스트"""
        result = calculate_score(
            query="bug",
            content="This is a bug report",
            vector_score=0.7,
            category="bug",
        )

        assert result.should_include
        assert result.breakdown.get("category_boost", 0) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
