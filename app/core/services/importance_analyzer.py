"""
ImportanceAnalyzer: 핀 중요도 자동 분석 서비스

컨텐츠와 태그를 분석하여 핀의 중요도(1-5)를 자동으로 추정합니다.
키워드 기반 분석을 통해 한국어와 영어를 모두 지원합니다.
"""

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ImportanceAnalyzer:
    """
    핀 중요도 자동 분석 서비스

    컨텐츠와 태그를 분석하여 중요도를 1-5 범위로 추정합니다.

    중요도 기준:
    - 5: architecture, design, critical, breaking (아키텍처, 설계, 중대)
    - 4: feature, implement, refactor, optimize (기능, 구현, 최적화)
    - 3: fix, update, improve (수정, 업데이트, 개선) - 기본값
    - 2: test, doc, comment (테스트, 문서, 주석)
    - 1: typo, format, style (오타, 포맷, 스타일)
    """

    DEFAULT_IMPORTANCE = 3  # 기본 중요도

    def __init__(self):
        """ImportanceAnalyzer 초기화"""
        self.keywords = self._load_importance_keywords()
        logger.info("ImportanceAnalyzer initialized with keyword dictionary")

    def _load_importance_keywords(self) -> Dict[int, List[str]]:
        """
        중요도별 키워드 사전을 로드합니다.

        Returns:
            중요도(1-5)를 키로, 키워드 리스트를 값으로 하는 딕셔너리
        """
        return {
            5: [
                # 영어 키워드
                "architecture",
                "design",
                "critical",
                "breaking",
                "major",
                "system",
                "infrastructure",
                "security",
                "migration",
                # 한국어 키워드
                "아키텍처",
                "설계",
                "중대",
                "중요",
                "시스템",
                "인프라",
                "보안",
                "마이그레이션",
                "구조",
            ],
            4: [
                # 영어 키워드
                "feature",
                "implement",
                "refactor",
                "optimize",
                "enhancement",
                "performance",
                "integration",
                "api",
                "service",
                # 한국어 키워드
                "기능",
                "구현",
                "리팩토링",
                "리팩터링",
                "최적화",
                "성능",
                "통합",
                "서비스",
            ],
            3: [
                # 영어 키워드
                "update",
                "change",
                "modify",
                "bug",
                "issue",
                "problem",
                "error",
                # 한국어 키워드
                "업데이트",
                "변경",
                "버그",
                "이슈",
                "문제",
                "에러",
                "오류",
            ],
            2: [
                # 영어 키워드
                "test",
                "doc",
                "comment",
                "documentation",
                "readme",
                "example",
                "guide",
                "tutorial",
                # 한국어 키워드
                "테스트",
                "문서",
                "주석",
                "예제",
                "가이드",
                "튜토리얼",
                "설명",
            ],
            1: [
                # 영어 키워드
                "typo",
                "format",
                "style",
                "whitespace",
                "indent",
                "lint",
                "cleanup",
                "cosmetic",
                # 한국어 키워드
                "오타",
                "포맷",
                "스타일",
                "정리",
                "공백",
                "들여쓰기",
                "린트",
            ],
        }

    def analyze(self, content: str, tags: Optional[List[str]] = None) -> int:
        """
        컨텐츠와 태그를 분석하여 중요도를 추정합니다.

        Args:
            content: 핀 내용
            tags: 태그 목록 (선택적)

        Returns:
            중요도 (1-5)

        Examples:
            >>> analyzer = ImportanceAnalyzer()
            >>> analyzer.analyze("Fix typo in README")
            1
            >>> analyzer.analyze("Implement new authentication feature")
            4
            >>> analyzer.analyze("Critical security vulnerability", tags=["security"])
            5
        """
        if not content:
            logger.warning("Empty content provided, returning default importance")
            return self.DEFAULT_IMPORTANCE

        # 컨텐츠를 소문자로 변환하여 대소문자 무시
        content_lower = content.lower()

        # 태그도 분석에 포함
        tags_text = " ".join(tags) if tags else ""
        tags_lower = tags_text.lower()

        # 전체 텍스트 (컨텐츠 + 태그)
        full_text = f"{content_lower} {tags_lower}"

        # 각 중요도 레벨별로 키워드 매칭 점수 계산
        scores: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

        for importance, keywords in self.keywords.items():
            for keyword in keywords:
                keyword_lower = keyword.lower()

                # 영어: 단어 경계(\b) 사용 — "test"는 "testing"과 매칭, "latest"와는 불매칭
                # 한국어: \b가 동작하지 않으므로 공백/문자열 경계 기반 포함 검사
                if keyword_lower.isascii():
                    pattern = r"\b" + re.escape(keyword_lower) + r"\w*\b"
                    matches = re.findall(pattern, full_text)
                else:
                    tokens = full_text.split()
                    matches = [t for t in tokens if keyword_lower in t]

                if matches:
                    # 매칭된 횟수만큼 점수 증가
                    scores[importance] += len(matches)
                    logger.debug(
                        f"Keyword '{keyword}' matched {len(matches)} times "
                        f"for importance {importance}"
                    )

        # 가장 높은 점수를 가진 중요도 선택
        max_score = max(scores.values())

        if max_score == 0:
            # 매칭된 키워드가 없으면 기본값 반환
            logger.debug(
                f"No keywords matched, returning default importance: {self.DEFAULT_IMPORTANCE}"
            )
            return self.DEFAULT_IMPORTANCE

        # 동점인 경우 더 높은 중요도 선택
        for importance in sorted(scores.keys(), reverse=True):
            if scores[importance] == max_score:
                logger.info(
                    f"Analyzed importance: {importance} "
                    f"(score: {max_score}, content: '{content[:50]}...')"
                )
                return importance

        # 폴백 (이론적으로 도달하지 않음)
        return self.DEFAULT_IMPORTANCE

    def get_keywords_for_importance(self, importance: int) -> List[str]:
        """
        특정 중요도에 해당하는 키워드 목록을 반환합니다.

        Args:
            importance: 중요도 (1-5)

        Returns:
            키워드 리스트
        """
        return self.keywords.get(importance, [])

    def get_all_keywords(self) -> Dict[int, List[str]]:
        """
        모든 중요도별 키워드 사전을 반환합니다.

        Returns:
            중요도별 키워드 딕셔너리 (깊은 복사본)
        """
        import copy

        return copy.deepcopy(self.keywords)

    def add_custom_keyword(self, importance: int, keyword: str) -> None:
        """
        커스텀 키워드를 추가합니다.

        Args:
            importance: 중요도 (1-5)
            keyword: 추가할 키워드

        Raises:
            ValueError: importance가 1-5 범위를 벗어난 경우
        """
        if importance not in range(1, 6):
            raise ValueError(f"Importance must be between 1 and 5, got {importance}")

        if keyword not in self.keywords[importance]:
            self.keywords[importance].append(keyword)
            logger.info(f"Added custom keyword '{keyword}' for importance {importance}")
