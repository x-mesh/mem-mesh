"""
시간 인식 검색 (Temporal-Aware Search) 테스트

- SearchParams 시간 파라미터 검증
- QueryExpander 시간 표현 추출
- UnifiedSearchService 시간 필터/부스트/감쇠
"""

import math
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.core.schemas.requests import SearchParams, VALID_TIME_RANGES, VALID_TEMPORAL_MODES
from app.core.services.query_expander import (
    extract_time_expression,
    KOREAN_TIME_EXPRESSIONS,
    ENGLISH_TIME_EXPRESSIONS,
)
from app.core.services.unified_search import UnifiedSearchService
from app.core.schemas.responses import SearchResult, SearchResponse


# ── SearchParams 시간 파라미터 검증 ──


class TestSearchParamsTemporalFields:
    """SearchParams 시간 관련 필드 검증 테스트"""

    def test_default_values(self):
        params = SearchParams(query="test")
        assert params.time_range is None
        assert params.date_from is None
        assert params.date_to is None
        assert params.temporal_mode == "boost"

    @pytest.mark.parametrize("tr", list(VALID_TIME_RANGES))
    def test_valid_time_ranges(self, tr: str):
        params = SearchParams(query="test", time_range=tr)
        assert params.time_range == tr

    def test_invalid_time_range_rejected(self):
        with pytest.raises(ValueError):
            SearchParams(query="test", time_range="next_year")

    def test_valid_date_from(self):
        params = SearchParams(query="test", date_from="2026-02-01")
        assert params.date_from == "2026-02-01"

    def test_invalid_date_format_rejected(self):
        with pytest.raises(ValueError):
            SearchParams(query="test", date_from="02-01-2026")

    @pytest.mark.parametrize("mode", list(VALID_TEMPORAL_MODES))
    def test_valid_temporal_modes(self, mode: str):
        params = SearchParams(query="test", temporal_mode=mode)
        assert params.temporal_mode == mode

    def test_invalid_temporal_mode_rejected(self):
        with pytest.raises(ValueError):
            SearchParams(query="test", temporal_mode="warp")

    def test_combined_params(self):
        params = SearchParams(
            query="migration",
            date_from="2026-02-01",
            date_to="2026-02-15",
            temporal_mode="filter",
        )
        assert params.date_from == "2026-02-01"
        assert params.date_to == "2026-02-15"
        assert params.temporal_mode == "filter"


# ── QueryExpander 시간 표현 추출 ──


class TestExtractTimeExpression:
    """쿼리에서 시간 표현을 추출하는 함수 테스트"""

    # 한국어 시간 표현
    @pytest.mark.parametrize(
        "query, expected_range, expected_cleaned",
        [
            ("이번주 결정사항", "this_week", "결정사항"),
            ("지난달 버그 수정", "last_month", "버그 수정"),
            ("오늘 작업 내용", "today", "작업 내용"),
            ("어제 회의 내용", "yesterday", "회의 내용"),
            ("이번 달 진행상황", "this_month", "진행상황"),
            ("지난 주 리뷰", "last_week", "리뷰"),
            ("이번 분기 목표", "this_quarter", "목표"),
        ],
    )
    def test_korean_time_expressions(
        self, query: str, expected_range: str, expected_cleaned: str
    ):
        time_range, cleaned = extract_time_expression(query)
        assert time_range == expected_range
        assert cleaned.strip() == expected_cleaned.strip()

    # 영어 시간 표현
    @pytest.mark.parametrize(
        "query, expected_range",
        [
            ("today's work", "today"),
            ("this week decisions", "this_week"),
            ("last month bugs", "last_month"),
        ],
    )
    def test_english_time_expressions(self, query: str, expected_range: str):
        time_range, cleaned = extract_time_expression(query)
        assert time_range == expected_range
        assert len(cleaned) > 0

    def test_no_time_expression(self):
        time_range, cleaned = extract_time_expression("DB 스키마 변경")
        assert time_range is None
        assert cleaned == "DB 스키마 변경"

    def test_time_expression_only_returns_original(self):
        """시간 표현만 있으면 원본 쿼리 유지"""
        time_range, cleaned = extract_time_expression("오늘")
        assert time_range == "today"
        assert cleaned == "오늘"  # 원본 유지

    def test_longer_expression_takes_priority(self):
        """'이번 주'가 '이번'보다 긴 패턴으로 우선 매칭"""
        time_range, cleaned = extract_time_expression("이번 주 리뷰")
        assert time_range == "this_week"


# ── UnifiedSearchService 시간 처리 ──


def _make_result(
    memory_id: str, score: float, created_at: str
) -> SearchResult:
    """테스트용 SearchResult 생성"""
    return SearchResult(
        id=memory_id,
        content=f"Memory {memory_id}",
        similarity_score=score,
        created_at=created_at,
        project_id="test-project",
        category="task",
        source="mcp",
        tags=None,
    )


def _make_response(results: list[SearchResult]) -> SearchResponse:
    return SearchResponse(
        results=results,
        total=len(results),
        query="test",
    )


class TestApplyTemporal:
    """UnifiedSearchService._apply_temporal 메서드 테스트"""

    def _get_service(self) -> UnifiedSearchService:
        """최소 mock으로 서비스 인스턴스 생성"""
        db = MagicMock()
        embedding = MagicMock()
        return UnifiedSearchService(
            db=db,
            embedding_service=embedding,
            enable_quality_features=False,
            enable_korean_optimization=False,
            enable_noise_filter=False,
            enable_score_normalization=False,
        )

    def test_filter_mode_removes_out_of_range(self):
        service = self._get_service()
        now = datetime.now(timezone.utc)

        results = [
            _make_result("old", 0.9, (now - timedelta(days=30)).isoformat()),
            _make_result("recent", 0.8, (now - timedelta(hours=1)).isoformat()),
            _make_result("mid", 0.7, (now - timedelta(days=5)).isoformat()),
        ]
        response = _make_response(results)

        filtered = service._apply_temporal(
            response,
            time_range="this_week",
            date_from=None,
            date_to=None,
            temporal_mode="filter",
        )
        ids = [r.id for r in filtered.results]
        assert "recent" in ids
        assert "mid" in ids
        assert "old" not in ids

    def test_filter_mode_with_date_range(self):
        service = self._get_service()

        results = [
            _make_result("jan", 0.9, "2026-01-15T10:00:00+00:00"),
            _make_result("feb", 0.8, "2026-02-10T10:00:00+00:00"),
            _make_result("mar", 0.7, "2026-03-05T10:00:00+00:00"),
        ]
        response = _make_response(results)

        filtered = service._apply_temporal(
            response,
            time_range=None,
            date_from="2026-02-01",
            date_to="2026-02-28",
            temporal_mode="filter",
        )
        ids = [r.id for r in filtered.results]
        assert ids == ["feb"]

    def test_boost_mode_increases_in_range_scores(self):
        service = self._get_service()
        now = datetime.now(timezone.utc)

        results = [
            _make_result("old", 0.6, (now - timedelta(days=30)).isoformat()),
            _make_result("recent", 0.5, (now - timedelta(hours=1)).isoformat()),
        ]
        response = _make_response(results)

        boosted = service._apply_temporal(
            response,
            time_range="this_week",
            date_from=None,
            date_to=None,
            temporal_mode="boost",
        )

        # recent은 부스트됨, old는 유지
        recent_result = next(r for r in boosted.results if r.id == "recent")
        old_result = next(r for r in boosted.results if r.id == "old")
        assert recent_result.similarity_score > 0.5  # 부스트됨
        assert old_result.similarity_score == 0.6  # 유지

    def test_boost_mode_reorders_by_score(self):
        service = self._get_service()
        now = datetime.now(timezone.utc)

        results = [
            _make_result("old_high", 0.9, (now - timedelta(days=30)).isoformat()),
            _make_result("recent_low", 0.65, (now - timedelta(hours=1)).isoformat()),
        ]
        response = _make_response(results)

        boosted = service._apply_temporal(
            response,
            time_range="this_week",
            date_from=None,
            date_to=None,
            temporal_mode="boost",
        )

        # recent_low가 1.5배 부스트되면 0.975 → old_high(0.9)보다 높아짐
        assert boosted.results[0].id == "recent_low"

    def test_decay_mode_reduces_old_scores(self):
        service = self._get_service()
        now = datetime.now(timezone.utc)

        results = [
            _make_result("new", 0.8, (now - timedelta(days=1)).isoformat()),
            _make_result("old", 0.8, (now - timedelta(days=100)).isoformat()),
        ]
        response = _make_response(results)

        decayed = service._apply_temporal(
            response,
            time_range=None,
            date_from=None,
            date_to=None,
            temporal_mode="decay",
        )

        new_result = next(r for r in decayed.results if r.id == "new")
        old_result = next(r for r in decayed.results if r.id == "old")

        # 1일: exp(-0.01 * 1) ≈ 0.99 → 0.8 * 0.99 ≈ 0.792
        # 100일: exp(-0.01 * 100) ≈ 0.368 → 0.8 * 0.368 ≈ 0.294
        assert new_result.similarity_score > old_result.similarity_score
        assert new_result.similarity_score > 0.7
        assert old_result.similarity_score < 0.4

    def test_no_temporal_params_returns_unchanged(self):
        service = self._get_service()
        now = datetime.now(timezone.utc)

        results = [
            _make_result("a", 0.9, now.isoformat()),
            _make_result("b", 0.8, now.isoformat()),
        ]
        response = _make_response(results)

        # temporal_mode가 boost이지만 time_range/date가 없으면
        # _apply_temporal이 호출되지 않음 (search 메서드에서 조건 확인)
        # 여기서는 직접 호출하여 boost with no range 확인
        result = service._apply_temporal(
            response,
            time_range=None,
            date_from=None,
            date_to=None,
            temporal_mode="boost",
        )
        # has_range가 False이므로 변경 없음
        assert result.results[0].similarity_score == 0.9


class TestResolveTimeRange:
    """_resolve_time_range 메서드 테스트"""

    def _get_service(self) -> UnifiedSearchService:
        db = MagicMock()
        embedding = MagicMock()
        return UnifiedSearchService(
            db=db,
            embedding_service=embedding,
            enable_quality_features=False,
            enable_korean_optimization=False,
            enable_noise_filter=False,
            enable_score_normalization=False,
        )

    def test_today_resolves_to_1_day_ago(self):
        service = self._get_service()
        dt_from, dt_to = service._resolve_time_range("today", None, None)
        now = datetime.now(timezone.utc)
        assert dt_from is not None
        assert dt_to is not None
        assert (now - dt_from).total_seconds() < 86400 + 5  # 1일 + 여유

    def test_this_week_resolves_to_7_days_ago(self):
        service = self._get_service()
        dt_from, dt_to = service._resolve_time_range("this_week", None, None)
        now = datetime.now(timezone.utc)
        assert dt_from is not None
        diff_days = (now - dt_from).total_seconds() / 86400
        assert 6.9 < diff_days < 7.1

    def test_date_from_to_parsed(self):
        service = self._get_service()
        dt_from, dt_to = service._resolve_time_range(
            None, "2026-02-01", "2026-02-28"
        )
        assert dt_from is not None
        assert dt_to is not None
        assert dt_from.day == 1
        assert dt_to.day == 28
        assert dt_to.hour == 23  # 종료일은 23:59:59

    def test_no_params_returns_none(self):
        service = self._get_service()
        dt_from, dt_to = service._resolve_time_range(None, None, None)
        assert dt_from is None
        assert dt_to is None


class TestParseCreatedAt:
    """_parse_created_at 정적 메서드 테스트"""

    def test_iso_with_z(self):
        dt = UnifiedSearchService._parse_created_at("2026-02-25T10:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.hour == 10

    def test_iso_with_offset(self):
        dt = UnifiedSearchService._parse_created_at("2026-02-25T10:00:00+09:00")
        assert dt is not None

    def test_iso_naive(self):
        dt = UnifiedSearchService._parse_created_at("2026-02-25T10:00:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc  # UTC로 간주

    def test_none_returns_none(self):
        assert UnifiedSearchService._parse_created_at(None) is None

    def test_invalid_returns_none(self):
        assert UnifiedSearchService._parse_created_at("not-a-date") is None
