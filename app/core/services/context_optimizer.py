"""ContextOptimizer 서비스 - 검색 의도에 따른 맥락 로딩 최적화

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from app.core.schemas.sessions import SessionContext

    from .search_quality import SearchIntent
    from .session import SessionService

logger = logging.getLogger(__name__)


@dataclass
class ContextLoadingParams:
    """맥락 로딩 파라미터"""

    expand: bool  # 상세 로딩 여부
    limit: int  # 로드할 핀 개수
    min_importance: int  # 최소 중요도 필터


class ContextOptimizer:
    """맥락 로딩 최적화 서비스

    검색 의도에 따라 맥락 로딩 깊이를 조정하여 토큰 사용량을 최적화합니다.

    의도별 전략:
    - Debug: 상세 모드, 적은 개수, 높은 중요도 (정확한 정보 필요)
    - Explore: 요약 모드, 많은 개수, 낮은 중요도 (넓은 범위 탐색)
    - Implement: 중간 모드, 중간 개수, 중간 중요도 (실행 가능한 정보)
    - 기타: 요약 모드, 기본 개수, 낮은 중요도 (일반적인 검색)
    """

    def __init__(self, session_service: "SessionService"):
        """
        Args:
            session_service: SessionService 인스턴스
        """
        self.session_service = session_service

        # 의도별 기본 파라미터 설정
        self._intent_params = {
            "debug": ContextLoadingParams(expand=True, limit=5, min_importance=4),
            "explore": ContextLoadingParams(expand=False, limit=20, min_importance=1),
            "implement": ContextLoadingParams(expand=True, limit=10, min_importance=3),
            "lookup": ContextLoadingParams(expand=False, limit=10, min_importance=2),
            "learn": ContextLoadingParams(expand=False, limit=15, min_importance=2),
            "review": ContextLoadingParams(expand=False, limit=15, min_importance=1),
        }

        # 기본 파라미터 (의도 불명확 시)
        self._default_params = ContextLoadingParams(
            expand=False, limit=10, min_importance=1
        )

        logger.info("ContextOptimizer initialized with intent-based loading strategies")

    async def adjust_for_intent(
        self, intent: "SearchIntent", project_id: str, base_limit: int = 10
    ) -> Tuple[bool, int, int]:
        """검색 의도에 따라 맥락 로딩 파라미터 조정

        Args:
            intent: 검색 의도 분석 결과
            project_id: 프로젝트 ID
            base_limit: 기본 제한 수 (의도에 따라 조정됨)

        Returns:
            (expand, limit, min_importance) 튜플
            - expand: 상세 로딩 여부 (True면 핀 전체 내용 포함)
            - limit: 로드할 핀 개수
            - min_importance: 최소 중요도 필터 (1-5)

        Requirements: 6.1, 6.2, 6.3, 6.4
        """
        # 의도 타입에 따른 기본 파라미터 선택
        params = self._intent_params.get(intent.intent_type, self._default_params)

        # 기본 파라미터 복사
        expand = params.expand
        limit = params.limit
        min_importance = params.min_importance

        # 긴급도에 따른 조정
        if intent.urgency > 0.8:
            # 매우 긴급한 경우: 결과 수 줄이고 중요도 높임
            limit = min(limit, 5)
            min_importance = max(min_importance, 4)
            expand = True  # 상세 정보 필요
            logger.debug(
                f"High urgency detected ({intent.urgency:.2f}): limit={limit}, min_importance={min_importance}"
            )

        # 구체성에 따른 조정
        if intent.specificity > 0.8:
            # 매우 구체적인 경우: 정확한 매칭 필요
            limit = min(limit, 3)
            expand = True
            logger.debug(
                f"High specificity detected ({intent.specificity:.2f}): limit={limit}, expand=True"
            )
        elif intent.specificity < 0.3:
            # 모호한 경우: 넓은 범위 탐색
            limit = max(limit, 15)
            expand = False
            min_importance = 1
            logger.debug(
                f"Low specificity detected ({intent.specificity:.2f}): limit={limit}, expand=False"
            )

        # 시간적 초점에 따른 조정
        if intent.temporal_focus == "recent":
            # 최근 정보 중심: 더 많은 결과 (최신성 우선)
            limit = max(limit, 10)
            logger.debug(f"Recent temporal focus: limit={limit}")

        # base_limit 고려 (사용자 명시적 요청)
        if base_limit != 10:  # 기본값이 아닌 경우
            # 사용자 요청과 의도 기반 조정의 중간값 사용
            limit = int((limit + base_limit) / 2)
            logger.debug(f"Adjusted limit with base_limit: {base_limit} -> {limit}")

        logger.info(
            f"Context loading adjusted for intent '{intent.intent_type}': "
            f"expand={expand}, limit={limit}, min_importance={min_importance}"
        )

        return expand, limit, min_importance

    async def load_context_for_search(
        self, query: str, project_id: str, intent: "SearchIntent"
    ) -> Optional["SessionContext"]:
        """검색 의도에 최적화된 맥락 로드

        Args:
            query: 검색 쿼리
            project_id: 프로젝트 ID
            intent: 검색 의도

        Returns:
            최적화된 세션 맥락 (세션이 없으면 None)

        Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
        """
        # 의도에 따른 파라미터 조정
        expand, limit, min_importance = await self.adjust_for_intent(
            intent=intent, project_id=project_id, base_limit=10
        )

        # 세션 맥락 로드
        context = await self.session_service.resume_last_session(
            project_id=project_id,
            user_id=None,  # 현재 사용자 자동 감지
            expand=expand,
            limit=limit,
        )

        if not context:
            logger.info(f"No active session found for project: {project_id}")
            return None

        # 중요도 필터링 (expand=True인 경우에만 적용)
        if expand and context.pins and min_importance > 1:
            original_count = len(context.pins)
            context.pins = [
                pin for pin in context.pins if pin.importance >= min_importance
            ]
            filtered_count = len(context.pins)

            if filtered_count < original_count:
                logger.debug(
                    f"Filtered pins by importance >= {min_importance}: "
                    f"{original_count} -> {filtered_count}"
                )

        # 토큰 수 추정 (간단한 추정)
        estimated_tokens = self._estimate_context_tokens(context, expand)

        logger.info(
            f"Context loaded for search: "
            f"query='{query[:50]}...', "
            f"intent={intent.intent_type}, "
            f"pins={len(context.pins) if context.pins else 0}, "
            f"estimated_tokens={estimated_tokens}"
        )

        return context

    def _estimate_context_tokens(self, context: "SessionContext", expand: bool) -> int:
        """맥락의 예상 토큰 수 계산

        간단한 추정 방식:
        - 요약 모드 (expand=False): 기본 정보만 (~100 토큰)
        - 상세 모드 (expand=True): 기본 정보 + 핀 내용 (핀당 ~50-200 토큰)

        Args:
            context: 세션 맥락
            expand: 상세 로딩 여부

        Returns:
            예상 토큰 수

        Requirements: 6.5
        """
        # 기본 세션 정보 토큰 (~50 토큰)
        base_tokens = 50

        # 요약 정보 토큰 (~50 토큰)
        summary_tokens = 50 if context.summary else 0

        if not expand:
            # 요약 모드: 기본 정보만
            return base_tokens + summary_tokens

        # 상세 모드: 핀 내용 포함
        pin_tokens = 0
        if context.pins:
            for pin in context.pins:
                # 핀 내용 길이에 따른 토큰 추정 (대략 4자당 1토큰)
                content_length = len(pin.content) if pin.content else 0
                pin_tokens += max(50, min(200, content_length // 4))

        total_tokens = base_tokens + summary_tokens + pin_tokens

        logger.debug(
            f"Token estimation: base={base_tokens}, summary={summary_tokens}, "
            f"pins={pin_tokens}, total={total_tokens}"
        )

        return total_tokens

    def get_intent_strategy_info(self, intent_type: str) -> dict:
        """특정 의도에 대한 전략 정보 반환 (디버깅/모니터링용)

        Args:
            intent_type: 의도 타입

        Returns:
            전략 정보 딕셔너리
        """
        params = self._intent_params.get(intent_type, self._default_params)
        return {
            "intent_type": intent_type,
            "expand": params.expand,
            "limit": params.limit,
            "min_importance": params.min_importance,
            "description": self._get_strategy_description(intent_type),
        }

    def _get_strategy_description(self, intent_type: str) -> str:
        """의도별 전략 설명"""
        descriptions = {
            "debug": "디버깅: 상세 정보, 높은 중요도, 적은 개수",
            "explore": "탐색: 요약 정보, 낮은 중요도, 많은 개수",
            "implement": "구현: 상세 정보, 중간 중요도, 중간 개수",
            "lookup": "조회: 요약 정보, 낮은 중요도, 중간 개수",
            "learn": "학습: 요약 정보, 낮은 중요도, 많은 개수",
            "review": "리뷰: 요약 정보, 낮은 중요도, 많은 개수",
        }
        return descriptions.get(intent_type, "기본: 요약 정보, 낮은 중요도, 중간 개수")
