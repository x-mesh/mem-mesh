"""
Quality Gate for Memory Content
메모리 저장 전 품질 체크 및 콘텐츠 정제
"""

import logging
import re
from typing import Optional

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
        raise MemoryContentTooShortError(
            length=len(cleaned), minimum=_MIN_CONTENT_LENGTH
        )

    # 3. Check for low-quality prefixes
    for prefix in _LOW_QUALITY_PREFIXES:
        if cleaned.startswith(prefix):
            logger.info(
                "Quality gate rejected: low quality prefix '%s'",
                prefix,
            )
            raise MemoryLowQualityError(prefix=prefix)

    return cleaned


# ---------------------------------------------------------------------------
# Derivability pre-check (R17)
#
# A *soft* signal, unlike ``content_quality_gate``: conversation transcripts and
# pasted git output are low-value as long-term memory, but rejecting them would
# lose real content. Instead these pure/synchronous rule checks (no LLM — see
# CLAUDE.md L1/L5) let the caller store the memory and route it to the async
# ``improve`` worker to be distilled.
# ---------------------------------------------------------------------------

# The stop-hook Q&A pairing format is ``Q: <prompt>\n\nA: <reply>`` (see
# route_modules/hooks.py). Match a "Q:" opener followed by a blank-line "A:".
_QA_DUMP_RE = re.compile(r"^\s*Q:\s.*?\n\s*\n\s*A:\s", re.DOTALL)

# Speaker turn markers at line start (a transcript, not a distilled note).
_TURN_MARKER_RE = re.compile(
    r"^\s*(?:User|Human|Assistant|AI)\s*:\s",
    re.MULTILINE | re.IGNORECASE,
)

# Unambiguous git-diff markers.
_GIT_DIFF_RE = re.compile(r"^diff --git ", re.MULTILINE)
_GIT_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", re.MULTILINE)

# ``git log --oneline`` rows: short/long hash + space + subject.
_GIT_LOG_LINE_RE = re.compile(r"^[0-9a-f]{7,40}\s+\S", re.MULTILINE)


def is_conversation_dump(content: str) -> bool:
    """Whether ``content`` looks like a raw Q/A or multi-turn transcript.

    True when it opens with the hook ``Q: …\\n\\nA: …`` pairing format, or when
    it carries two or more speaker turn markers (``User:`` / ``Assistant:`` …).
    A normal note or code block — which does neither — is not flagged.
    """
    if not content:
        return False
    if _QA_DUMP_RE.match(content):
        return True
    # Two or more distinct speaker turns → a transcript.
    return len(_TURN_MARKER_RE.findall(content)) >= 2


def is_derivable_from_git(content: str, category: str = "") -> bool:
    """Whether ``content`` is reconstructable from git history (diff/log paste).

    True for unambiguous ``diff --git`` / ``@@ … @@`` hunk markers in any
    category, or three-plus ``git log --oneline`` rows. The commit-log
    heuristic can false-match hex-heavy code, so it is skipped for
    ``code_snippet`` where a legitimate code block is the expected content.
    """
    if not content:
        return False
    if _GIT_DIFF_RE.search(content) or _GIT_HUNK_RE.search(content):
        return True
    if category == "code_snippet":
        return False
    return len(_GIT_LOG_LINE_RE.findall(content)) >= 3


def derivability_hint(content: str, category: str = "") -> Optional[str]:
    """Classify write-time derivable content for the improve queue.

    Returns a short hint kind — ``"conversation_dump"`` or
    ``"derivable_from_git"`` — when the content is a raw transcript or pasted
    git output, else ``None``. Pure and synchronous (no LLM); the caller stores
    the memory regardless and uses the hint to route it to the async improve
    worker.
    """
    if is_conversation_dump(content):
        return "conversation_dump"
    if is_derivable_from_git(content, category):
        return "derivable_from_git"
    return None
