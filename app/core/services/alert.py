"""알림 서비스

검색 성능 임계값을 모니터링하고 알림을 생성/관리합니다.
"""

import asyncio
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.database.base import Database
from app.core.database.models import Alert
from app.core.utils.logger import get_logger

logger = get_logger(__name__)


class AlertSeverity(str, Enum):
    """알림 심각도"""

    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertType(str, Enum):
    """알림 유형"""

    LOW_SIMILARITY = "low_similarity"
    HIGH_NO_RESULTS = "high_no_results"
    SLOW_RESPONSE = "slow_response"
    HIGH_ERROR_RATE = "high_error_rate"


class AlertService:
    """알림 서비스 - 임계값 모니터링 및 알림 관리"""

    # 기본 임계값 설정
    DEFAULT_THRESHOLDS = {
        "min_avg_similarity": 0.5,  # 평균 유사도 최소값
        "max_no_results_rate": 20.0,  # 결과없음 비율 최대값 (%)
        "max_response_time_ms": 1000,  # 응답 시간 최대값 (ms)
        "check_window_minutes": 15,  # 체크 윈도우 (분)
        "min_samples": 10,  # 최소 샘플 수
    }

    def __init__(self, database: Database, thresholds: Optional[Dict[str, Any]] = None):
        """
        Args:
            database: 데이터베이스 인스턴스
            thresholds: 커스텀 임계값 설정 (선택적)
        """
        self.database = database
        self.thresholds = {**self.DEFAULT_THRESHOLDS, **(thresholds or {})}
        self._check_task: Optional[asyncio.Task] = None
        logger.info(f"AlertService initialized with thresholds: {self.thresholds}")

    async def start_background_check(self, interval_minutes: int = 5):
        """백그라운드 임계값 체크 시작"""
        if self._check_task is None or self._check_task.done():
            self._check_task = asyncio.create_task(
                self._background_check_loop(interval_minutes)
            )
            logger.info(
                f"Alert background check started (interval: {interval_minutes}min)"
            )

    async def stop_background_check(self):
        """백그라운드 체크 중지"""
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        logger.info("Alert background check stopped")

    async def _background_check_loop(self, interval_minutes: int):
        """백그라운드 체크 루프"""
        while True:
            try:
                await asyncio.sleep(interval_minutes * 60)
                await self.check_thresholds()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Background check error: {e}")

    async def check_thresholds(self) -> List[Alert]:
        """
        임계값 체크 및 알림 생성

        Returns:
            생성된 알림 목록
        """
        created_alerts = []
        window_minutes = self.thresholds["check_window_minutes"]
        min_samples = self.thresholds["min_samples"]

        try:
            # 최근 윈도우 내 메트릭 집계
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=window_minutes)

            metrics = await self._get_recent_metrics(start_time, end_time)

            if metrics["total_searches"] < min_samples:
                logger.debug(
                    f"Not enough samples ({metrics['total_searches']} < {min_samples})"
                )
                return []

            # 1. 평균 유사도 체크
            if metrics["avg_similarity"] is not None:
                if metrics["avg_similarity"] < self.thresholds["min_avg_similarity"]:
                    alert = await self._create_alert_if_not_exists(
                        alert_type=AlertType.LOW_SIMILARITY,
                        severity=AlertSeverity.WARNING,
                        message=f"평균 유사도가 임계값 미만입니다: {metrics['avg_similarity']:.2%} < {self.thresholds['min_avg_similarity']:.0%}",
                        metric_value=metrics["avg_similarity"],
                        threshold_value=self.thresholds["min_avg_similarity"],
                    )
                    if alert:
                        created_alerts.append(alert)

            # 2. 결과없음 비율 체크
            if metrics["no_results_rate"] > self.thresholds["max_no_results_rate"]:
                severity = (
                    AlertSeverity.ERROR
                    if metrics["no_results_rate"] > 30
                    else AlertSeverity.WARNING
                )
                alert = await self._create_alert_if_not_exists(
                    alert_type=AlertType.HIGH_NO_RESULTS,
                    severity=severity,
                    message=f"결과없음 비율이 임계값 초과입니다: {metrics['no_results_rate']:.1f}% > {self.thresholds['max_no_results_rate']:.0f}%",
                    metric_value=metrics["no_results_rate"],
                    threshold_value=self.thresholds["max_no_results_rate"],
                )
                if alert:
                    created_alerts.append(alert)

            # 3. 응답 시간 체크
            if (
                metrics["avg_response_time_ms"]
                > self.thresholds["max_response_time_ms"]
            ):
                severity = (
                    AlertSeverity.ERROR
                    if metrics["avg_response_time_ms"] > 2000
                    else AlertSeverity.WARNING
                )
                alert = await self._create_alert_if_not_exists(
                    alert_type=AlertType.SLOW_RESPONSE,
                    severity=severity,
                    message=f"평균 응답 시간이 임계값 초과입니다: {metrics['avg_response_time_ms']:.0f}ms > {self.thresholds['max_response_time_ms']}ms",
                    metric_value=metrics["avg_response_time_ms"],
                    threshold_value=self.thresholds["max_response_time_ms"],
                )
                if alert:
                    created_alerts.append(alert)

            if created_alerts:
                logger.warning(f"Created {len(created_alerts)} new alerts")

            return created_alerts

        except Exception as e:
            logger.error(f"Threshold check failed: {e}")
            return []

    async def _get_recent_metrics(
        self, start_time: datetime, end_time: datetime
    ) -> Dict[str, Any]:
        """최근 메트릭 집계"""
        query = """
            SELECT 
                COUNT(*) as total_searches,
                AVG(avg_similarity_score) as avg_similarity,
                AVG(response_time_ms) as avg_response_time_ms,
                SUM(CASE WHEN result_count = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as no_results_rate
            FROM search_metrics
            WHERE timestamp >= ? AND timestamp <= ?
        """

        row = await self.database.fetchone(
            query, (start_time.isoformat() + "Z", end_time.isoformat() + "Z")
        )

        return {
            "total_searches": row["total_searches"] or 0,
            "avg_similarity": row["avg_similarity"],
            "avg_response_time_ms": row["avg_response_time_ms"] or 0,
            "no_results_rate": row["no_results_rate"] or 0,
        }

    async def _create_alert_if_not_exists(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        message: str,
        metric_value: float,
        threshold_value: float,
    ) -> Optional[Alert]:
        """중복되지 않은 경우에만 알림 생성"""
        # 같은 유형의 활성 알림이 있는지 확인
        existing = await self.database.fetchone(
            """
            SELECT id FROM alerts 
            WHERE alert_type = ? AND resolved_at IS NULL
            """,
            (alert_type.value,),
        )

        if existing:
            logger.debug(f"Alert already exists for type: {alert_type.value}")
            return None

        # 새 알림 생성
        alert = Alert(
            alert_type=alert_type.value,
            severity=severity.value,
            message=message,
            metric_value=metric_value,
            threshold_value=threshold_value,
        )

        await self.database.execute(
            """
            INSERT INTO alerts (id, timestamp, alert_type, severity, message, 
                               metric_value, threshold_value, resolved_at, resolved_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            (
                alert.id,
                alert.timestamp,
                alert.alert_type,
                alert.severity,
                alert.message,
                alert.metric_value,
                alert.threshold_value,
            ),
        )

        logger.info(f"Created alert: {alert_type.value} - {message}")
        return alert

    async def get_active_alerts(self) -> List[Dict[str, Any]]:
        """활성 알림 목록 조회"""
        rows = await self.database.fetchall("""
            SELECT id, timestamp, alert_type, severity, message, 
                   metric_value, threshold_value
            FROM alerts 
            WHERE resolved_at IS NULL
            ORDER BY timestamp DESC
            """)

        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "alert_type": row["alert_type"],
                "severity": row["severity"],
                "message": row["message"],
                "metric_value": row["metric_value"],
                "threshold_value": row["threshold_value"],
            }
            for row in rows
        ]

    async def get_alert_history(
        self, limit: int = 50, include_resolved: bool = True
    ) -> List[Dict[str, Any]]:
        """알림 히스토리 조회"""
        if include_resolved:
            query = """
                SELECT id, timestamp, alert_type, severity, message, 
                       metric_value, threshold_value, resolved_at, resolved_by
                FROM alerts 
                ORDER BY timestamp DESC
                LIMIT ?
            """
            rows = await self.database.fetchall(query, (limit,))
        else:
            query = """
                SELECT id, timestamp, alert_type, severity, message, 
                       metric_value, threshold_value, resolved_at, resolved_by
                FROM alerts 
                WHERE resolved_at IS NULL
                ORDER BY timestamp DESC
                LIMIT ?
            """
            rows = await self.database.fetchall(query, (limit,))

        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "alert_type": row["alert_type"],
                "severity": row["severity"],
                "message": row["message"],
                "metric_value": row["metric_value"],
                "threshold_value": row["threshold_value"],
                "resolved_at": row["resolved_at"],
                "resolved_by": row["resolved_by"],
                "is_resolved": row["resolved_at"] is not None,
            }
            for row in rows
        ]

    async def resolve_alert(self, alert_id: str, resolved_by: str = "user") -> bool:
        """알림 해결 처리"""
        try:
            # 알림 존재 확인
            existing = await self.database.fetchone(
                "SELECT id, resolved_at FROM alerts WHERE id = ?", (alert_id,)
            )

            if not existing:
                logger.warning(f"Alert not found: {alert_id}")
                return False

            if existing["resolved_at"]:
                logger.info(f"Alert already resolved: {alert_id}")
                return True

            # 해결 처리
            resolved_at = datetime.utcnow().isoformat() + "Z"
            await self.database.execute(
                """
                UPDATE alerts 
                SET resolved_at = ?, resolved_by = ?
                WHERE id = ?
                """,
                (resolved_at, resolved_by, alert_id),
            )

            logger.info(f"Alert resolved: {alert_id} by {resolved_by}")
            return True

        except Exception as e:
            logger.error(f"Failed to resolve alert {alert_id}: {e}")
            return False

    async def get_alert_summary(self) -> Dict[str, Any]:
        """알림 요약 정보"""
        # 활성 알림 수
        active_row = await self.database.fetchone(
            "SELECT COUNT(*) as count FROM alerts WHERE resolved_at IS NULL"
        )

        # 심각도별 활성 알림 수
        severity_rows = await self.database.fetchall("""
            SELECT severity, COUNT(*) as count 
            FROM alerts 
            WHERE resolved_at IS NULL
            GROUP BY severity
            """)

        # 최근 24시간 알림 수
        yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"
        recent_row = await self.database.fetchone(
            "SELECT COUNT(*) as count FROM alerts WHERE timestamp >= ?", (yesterday,)
        )

        severity_counts = {row["severity"]: row["count"] for row in severity_rows}

        return {
            "active_count": active_row["count"] if active_row else 0,
            "by_severity": {
                "warning": severity_counts.get("warning", 0),
                "error": severity_counts.get("error", 0),
                "critical": severity_counts.get("critical", 0),
            },
            "last_24h_count": recent_row["count"] if recent_row else 0,
        }

    def update_thresholds(self, new_thresholds: Dict[str, Any]) -> None:
        """임계값 업데이트"""
        self.thresholds.update(new_thresholds)
        logger.info(f"Thresholds updated: {self.thresholds}")
