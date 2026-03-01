"""
TokenTracker: 토큰 사용량 추적 및 최적화 서비스

세션별 토큰 사용량을 추적하고, 절감률을 계산하며, 임계값 초과 시 경고를 제공합니다.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from app.core.database.base import Database
from app.core.services.token_estimator import TokenEstimator

logger = logging.getLogger(__name__)


class TokenTracker:
    """토큰 사용량 추적 및 최적화 서비스

    세션의 토큰 사용량을 추적하고 최적화 효과를 측정합니다.

    Requirements:
    - 7.1: 세션 시작 시 초기 맥락 토큰 수 기록
    - 7.2: 세션 중 맥락 로드 시마다 누적 토큰 수 업데이트
    - 7.3: 세션 종료 시 총 토큰 사용량과 절감률 계산
    - 7.4: 지연 로딩으로 절감된 토큰 수 추적
    - 7.5: 토큰 사용량 임계값 초과 시 경고
    """

    def __init__(self, db: Database, default_threshold: int = 10000):
        """
        TokenTracker 초기화

        Args:
            db: Database 인스턴스
            default_threshold: 기본 토큰 임계값 (기본값: 10,000)
        """
        self.db = db
        self.token_estimator = TokenEstimator()
        self.default_threshold = default_threshold
        logger.info(f"TokenTracker initialized with threshold: {default_threshold}")

    async def estimate_tokens(self, content: str, model: Optional[str] = None) -> int:
        """
        컨텐츠의 예상 토큰 수 계산

        Args:
            content: 분석할 텍스트
            model: 모델 이름 (None이면 기본 모델 사용)

        Returns:
            예상 토큰 수

        Requirements: 7.1, 7.2
        """
        try:
            token_count = self.token_estimator.estimate_tokens(content, model)
            logger.debug(
                f"Estimated {token_count} tokens for content length {len(content)}"
            )
            return token_count
        except Exception as e:
            logger.error(f"Token estimation failed: {e}")
            # 폴백: 간단한 휴리스틱 (평균 4자당 1토큰)
            fallback_count = max(1, len(content) // 4)
            logger.warning(f"Using fallback estimation: {fallback_count} tokens")
            return fallback_count

    async def record_session_tokens(
        self,
        session_id: str,
        loaded_tokens: int,
        unloaded_tokens: int,
        event_type: str = "context_load",
        context_depth: Optional[int] = None,
    ) -> None:
        """
        세션의 토큰 사용량 기록

        Args:
            session_id: 세션 ID
            loaded_tokens: 실제 로드된 토큰 수
            unloaded_tokens: 지연 로딩으로 절감된 토큰 수
            event_type: 이벤트 타입 (resume, search, pin_add, end, context_load)
            context_depth: 맥락 깊이 (선택적)

        Requirements: 7.1, 7.2, 7.4
        """
        try:
            # 1. session_stats 테이블에 기록
            stat_id = str(uuid.uuid4())
            timestamp = datetime.utcnow().isoformat()

            await self.db.execute(
                """
                INSERT INTO session_stats (
                    id, session_id, timestamp, event_type,
                    tokens_loaded, tokens_saved, context_depth, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stat_id,
                    session_id,
                    timestamp,
                    event_type,
                    loaded_tokens,
                    unloaded_tokens,
                    context_depth,
                    timestamp,
                ),
            )

            # 2. sessions 테이블의 누적 토큰 수 업데이트
            await self.db.execute(
                """
                UPDATE sessions
                SET total_loaded_tokens = total_loaded_tokens + ?,
                    total_saved_tokens = total_saved_tokens + ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (loaded_tokens, unloaded_tokens, timestamp, session_id),
            )

            logger.info(
                f"Recorded tokens for session {session_id}: "
                f"loaded={loaded_tokens}, saved={unloaded_tokens}, event={event_type}"
            )

        except Exception as e:
            logger.error(f"Failed to record session tokens: {e}")
            raise

    async def calculate_savings(self, session_id: str) -> Dict[str, Any]:
        """
        세션의 토큰 절감률 계산

        Args:
            session_id: 세션 ID

        Returns:
            {
                "total_tokens": int,      # 예상 총 토큰 수 (로드 + 미로드)
                "loaded_tokens": int,     # 실제 로드된 토큰 수
                "saved_tokens": int,      # 절감된 토큰 수
                "savings_rate": float     # 절감률 (0.0-1.0)
            }

        Requirements: 7.3, 7.4
        """
        try:
            # 세션의 토큰 사용량 조회
            result = await self.db.fetchone(
                """
                SELECT 
                    initial_context_tokens,
                    total_loaded_tokens,
                    total_saved_tokens
                FROM sessions
                WHERE id = ?
                """,
                (session_id,),
            )

            if not result:
                logger.warning(f"Session {session_id} not found")
                return {
                    "total_tokens": 0,
                    "loaded_tokens": 0,
                    "saved_tokens": 0,
                    "savings_rate": 0.0,
                }

            result["initial_context_tokens"] or 0
            loaded_tokens = result["total_loaded_tokens"] or 0
            saved_tokens = result["total_saved_tokens"] or 0

            # 총 토큰 수 = 로드된 토큰 + 절감된 토큰
            total_tokens = loaded_tokens + saved_tokens

            # 절감률 계산 (0으로 나누기 방지)
            if total_tokens > 0:
                savings_rate = saved_tokens / total_tokens
            else:
                savings_rate = 0.0

            result_dict = {
                "total_tokens": total_tokens,
                "loaded_tokens": loaded_tokens,
                "saved_tokens": saved_tokens,
                "savings_rate": round(savings_rate, 4),
            }

            logger.info(
                f"Token savings for session {session_id}: "
                f"{saved_tokens}/{total_tokens} ({savings_rate:.2%})"
            )

            return result_dict

        except Exception as e:
            logger.error(f"Failed to calculate token savings: {e}")
            raise

    async def check_threshold(
        self, session_id: str, threshold: Optional[int] = None
    ) -> bool:
        """
        토큰 사용량이 임계값을 초과했는지 확인

        Args:
            session_id: 세션 ID
            threshold: 임계값 (None이면 기본값 사용)

        Returns:
            True if exceeded, False otherwise

        Requirements: 7.5
        """
        try:
            threshold = threshold or self.default_threshold

            # 세션의 누적 토큰 수 조회
            result = await self.db.fetchone(
                """
                SELECT total_loaded_tokens
                FROM sessions
                WHERE id = ?
                """,
                (session_id,),
            )

            if not result:
                logger.warning(f"Session {session_id} not found")
                return False

            loaded_tokens = result["total_loaded_tokens"] or 0
            exceeded = loaded_tokens > threshold

            if exceeded:
                logger.warning(
                    f"Token threshold exceeded for session {session_id}: "
                    f"{loaded_tokens} > {threshold}"
                )
            else:
                logger.debug(
                    f"Token usage within threshold for session {session_id}: "
                    f"{loaded_tokens} <= {threshold}"
                )

            return exceeded

        except Exception as e:
            logger.error(f"Failed to check token threshold: {e}")
            raise

    async def record_token_usage(
        self,
        project_id: str,
        operation_type: str,
        tokens_used: int,
        session_id: Optional[str] = None,
        query: Optional[str] = None,
        tokens_saved: int = 0,
        optimization_applied: bool = False,
    ) -> str:
        """
        토큰 사용량을 token_usage 테이블에 기록

        Args:
            project_id: 프로젝트 ID
            operation_type: 작업 타입 (session_resume, search, context_load)
            tokens_used: 사용된 토큰 수
            session_id: 세션 ID (선택적)
            query: 검색 쿼리 (선택적)
            tokens_saved: 절감된 토큰 수
            optimization_applied: 최적화 적용 여부

        Returns:
            생성된 레코드 ID
        """
        try:
            record_id = str(uuid.uuid4())
            timestamp = datetime.utcnow().isoformat()

            await self.db.execute(
                """
                INSERT INTO token_usage (
                    id, project_id, session_id, operation_type,
                    query, tokens_used, tokens_saved,
                    optimization_applied, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    project_id,
                    session_id,
                    operation_type,
                    query,
                    tokens_used,
                    tokens_saved,
                    1 if optimization_applied else 0,
                    timestamp,
                ),
            )

            logger.debug(
                f"Recorded token usage: project={project_id}, "
                f"operation={operation_type}, used={tokens_used}, saved={tokens_saved}"
            )

            return record_id

        except Exception as e:
            logger.error(f"Failed to record token usage: {e}")
            raise

    async def get_project_token_statistics(
        self,
        project_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        프로젝트의 토큰 사용 통계 조회

        Args:
            project_id: 프로젝트 ID
            start_date: 시작 날짜 (ISO 형식, 선택적)
            end_date: 종료 날짜 (ISO 형식, 선택적)

        Returns:
            {
                "total_tokens_used": int,
                "total_tokens_saved": int,
                "avg_savings_rate": float,
                "operation_breakdown": Dict[str, int]
            }
        """
        try:
            # 기본 쿼리
            query = """
                SELECT 
                    SUM(tokens_used) as total_used,
                    SUM(tokens_saved) as total_saved,
                    operation_type,
                    COUNT(*) as count
                FROM token_usage
                WHERE project_id = ?
            """
            params = [project_id]

            # 날짜 필터 추가
            if start_date:
                query += " AND created_at >= ?"
                params.append(start_date)
            if end_date:
                query += " AND created_at <= ?"
                params.append(end_date)

            query += " GROUP BY operation_type"

            results = await self.db.fetchall(query, tuple(params))

            # 통계 계산
            total_used = 0
            total_saved = 0
            operation_breakdown = {}

            for row in results:
                total_used += row["total_used"] or 0
                total_saved += row["total_saved"] or 0
                operation_breakdown[row["operation_type"]] = row["total_used"] or 0

            # 평균 절감률 계산
            total_tokens = total_used + total_saved
            avg_savings_rate = total_saved / total_tokens if total_tokens > 0 else 0.0

            return {
                "total_tokens_used": total_used,
                "total_tokens_saved": total_saved,
                "avg_savings_rate": round(avg_savings_rate, 4),
                "operation_breakdown": operation_breakdown,
            }

        except Exception as e:
            logger.error(f"Failed to get project token statistics: {e}")
            raise
