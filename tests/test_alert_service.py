"""AlertService 단위 테스트"""

from unittest.mock import AsyncMock

import pytest

from app.core.services.alert import AlertService, AlertSeverity, AlertType


class TestAlertService:
    """AlertService 테스트"""

    @pytest.fixture
    def mock_db(self):
        """Mock Database"""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.fetchone = AsyncMock()
        db.fetchall = AsyncMock(return_value=[])
        return db

    @pytest.fixture
    def alert_service(self, mock_db):
        """AlertService 인스턴스"""
        return AlertService(database=mock_db)

    def test_init_with_default_thresholds(self, mock_db):
        """기본 임계값으로 초기화 테스트"""
        service = AlertService(database=mock_db)

        assert service.thresholds["min_avg_similarity"] == 0.5
        assert service.thresholds["max_no_results_rate"] == 20.0
        assert service.thresholds["max_response_time_ms"] == 1000

    def test_init_with_custom_thresholds(self, mock_db):
        """커스텀 임계값으로 초기화 테스트"""
        custom = {"min_avg_similarity": 0.7, "max_response_time_ms": 500}
        service = AlertService(database=mock_db, thresholds=custom)

        assert service.thresholds["min_avg_similarity"] == 0.7
        assert service.thresholds["max_response_time_ms"] == 500
        # 기본값 유지
        assert service.thresholds["max_no_results_rate"] == 20.0

    @pytest.mark.asyncio
    async def test_check_thresholds_not_enough_samples(self, alert_service, mock_db):
        """샘플 부족 시 알림 생성 안함"""
        mock_db.fetchone.return_value = {
            "total_searches": 5,  # min_samples(10) 미만
            "avg_similarity": 0.3,
            "avg_response_time_ms": 2000,
            "no_results_rate": 50,
        }

        alerts = await alert_service.check_thresholds()

        assert len(alerts) == 0

    @pytest.mark.asyncio
    async def test_check_thresholds_low_similarity(self, alert_service, mock_db):
        """낮은 유사도 알림 생성 테스트"""
        # 메트릭 조회 결과
        mock_db.fetchone.side_effect = [
            {
                "total_searches": 100,
                "avg_similarity": 0.3,  # 임계값(0.5) 미만
                "avg_response_time_ms": 200,
                "no_results_rate": 5,
            },
            None,  # 기존 알림 없음
        ]

        alerts = await alert_service.check_thresholds()

        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.LOW_SIMILARITY.value
        assert alerts[0].severity == AlertSeverity.WARNING.value

    @pytest.mark.asyncio
    async def test_check_thresholds_high_no_results(self, alert_service, mock_db):
        """높은 결과없음 비율 알림 생성 테스트"""
        mock_db.fetchone.side_effect = [
            {
                "total_searches": 100,
                "avg_similarity": 0.7,
                "avg_response_time_ms": 200,
                "no_results_rate": 25,  # 임계값(20) 초과
            },
            None,  # 기존 알림 없음
        ]

        alerts = await alert_service.check_thresholds()

        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.HIGH_NO_RESULTS.value

    @pytest.mark.asyncio
    async def test_check_thresholds_slow_response(self, alert_service, mock_db):
        """느린 응답 시간 알림 생성 테스트"""
        mock_db.fetchone.side_effect = [
            {
                "total_searches": 100,
                "avg_similarity": 0.7,
                "avg_response_time_ms": 1500,  # 임계값(1000) 초과
                "no_results_rate": 5,
            },
            None,  # 기존 알림 없음
        ]

        alerts = await alert_service.check_thresholds()

        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.SLOW_RESPONSE.value

    @pytest.mark.asyncio
    async def test_check_thresholds_no_duplicate_alert(self, alert_service, mock_db):
        """중복 알림 방지 테스트"""
        mock_db.fetchone.side_effect = [
            {
                "total_searches": 100,
                "avg_similarity": 0.3,
                "avg_response_time_ms": 200,
                "no_results_rate": 5,
            },
            {"id": "existing-alert-id"},  # 기존 알림 있음
        ]

        alerts = await alert_service.check_thresholds()

        assert len(alerts) == 0

    @pytest.mark.asyncio
    async def test_get_active_alerts(self, alert_service, mock_db):
        """활성 알림 조회 테스트"""
        mock_db.fetchall.return_value = [
            {
                "id": "alert-1",
                "timestamp": "2024-01-01T00:00:00Z",
                "alert_type": "low_similarity",
                "severity": "warning",
                "message": "Test alert",
                "metric_value": 0.3,
                "threshold_value": 0.5,
            }
        ]

        alerts = await alert_service.get_active_alerts()

        assert len(alerts) == 1
        assert alerts[0]["id"] == "alert-1"
        assert alerts[0]["alert_type"] == "low_similarity"

    @pytest.mark.asyncio
    async def test_resolve_alert_success(self, alert_service, mock_db):
        """알림 해결 성공 테스트"""
        mock_db.fetchone.return_value = {"id": "alert-1", "resolved_at": None}

        result = await alert_service.resolve_alert("alert-1", "admin")

        assert result is True
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_alert_not_found(self, alert_service, mock_db):
        """존재하지 않는 알림 해결 테스트"""
        mock_db.fetchone.return_value = None

        result = await alert_service.resolve_alert("nonexistent", "admin")

        assert result is False

    @pytest.mark.asyncio
    async def test_resolve_alert_already_resolved(self, alert_service, mock_db):
        """이미 해결된 알림 테스트"""
        mock_db.fetchone.return_value = {
            "id": "alert-1",
            "resolved_at": "2024-01-01T00:00:00Z",
        }

        result = await alert_service.resolve_alert("alert-1", "admin")

        assert result is True
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_alert_summary(self, alert_service, mock_db):
        """알림 요약 조회 테스트"""
        mock_db.fetchone.side_effect = [
            {"count": 3},  # 활성 알림 수
            {"count": 10},  # 최근 24시간 알림 수
        ]
        mock_db.fetchall.return_value = [
            {"severity": "warning", "count": 2},
            {"severity": "error", "count": 1},
        ]

        summary = await alert_service.get_alert_summary()

        assert summary["active_count"] == 3
        assert summary["by_severity"]["warning"] == 2
        assert summary["by_severity"]["error"] == 1
        assert summary["last_24h_count"] == 10

    def test_update_thresholds(self, alert_service):
        """임계값 업데이트 테스트"""
        alert_service.update_thresholds(
            {"min_avg_similarity": 0.8, "max_response_time_ms": 500}
        )

        assert alert_service.thresholds["min_avg_similarity"] == 0.8
        assert alert_service.thresholds["max_response_time_ms"] == 500
