"""
Quality Gate for Memory Content
메모리 저장 전 품질 체크 및 콘텐츠 정제
"""

import logging
import re

from ..errors import (
    MemoryContentTooShortError,
    MemoryLowQualityError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Quality gate constants
# ---------------------------------------------------------------------------
_MIN_CONTENT_LENGTH = 100

_LOW_QUALITY_PREFIXES = (
    # Korean
    "좋습니다",
    "네.",
    "네!",
    "네,",
    "알겠습니다",
    "안녕하세요",
    # English
    "OK",
    "Sure",
    "Got it",
    "I understand",
    "Yes,",
    "Yes.",
    "Alright",
    "Okay",
)

_XML_STRIP_PATTERNS = [
    re.compile(r"<EnvironmentContext>.*?</EnvironmentContext>", re.DOTALL),
    re.compile(r"<fileTree>.*?</fileTree>", re.DOTALL),
    re.compile(r"<SPEC>.*?</SPEC>", re.DOTALL),
]


def content_quality_gate(content: str) -> str:
    """
    메모리 저장 전 품질 체크 및 콘텐츠 정제.

    1. XML 시스템 태그 스트리핑 (EnvironmentContext, fileTree, SPEC)
    2. 스트리핑 후 길이 100자 미만이면 MemoryContentTooShortError
    3. 단순 응답 접두사로 시작하면 MemoryLowQualityError

    Args:
        content: 원본 메모리 내용

    Returns:
        정제된 content 문자열

    Raises:
        MemoryContentTooShortError: 길이 부족
        MemoryLowQualityError: 저품질 접두사
    """
    # 1. Remove XML system tags
    cleaned = content
    for pattern in _XML_STRIP_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = cleaned.strip()

    # 2. Length check (after stripping)
    if len(cleaned) < _MIN_CONTENT_LENGTH:
        logger.info(
            "Quality gate rejected: content too short (%d < %d)",
            len(cleaned),
            _MIN_CONTENT_LENGTH,
        )
        raise MemoryContentTooShortError(length=len(cleaned), minimum=_MIN_CONTENT_LENGTH)

    # 3. Check for low-quality prefixes
    for prefix in _LOW_QUALITY_PREFIXES:
        if cleaned.startswith(prefix):
            logger.info(
                "Quality gate rejected: low quality prefix '%s'",
                prefix,
            )
            raise MemoryLowQualityError(prefix=prefix)

    return cleaned
