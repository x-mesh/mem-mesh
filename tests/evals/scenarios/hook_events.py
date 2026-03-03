"""SessionEnd and PreCompact hook event scenarios.

Tests that the new hook event templates:
  - Call the session_end API correctly
  - Include proper summary for PreCompact
  - Are non-blocking (exit 0 on failure)
  - Work in both API and local modes
"""

from __future__ import annotations

from tests.evals.models import (
    ConversationMessage,
    EvalScenario,
    EvalTier,
    ExpectedAction,
)

# ---------------------------------------------------------------------------
# Scenario: SessionEnd hook calls session_end API
# ---------------------------------------------------------------------------

SESSION_END_API_CALL = EvalScenario(
    id="hook_events_01",
    name="SessionEnd hook calls session_end API",
    description=(
        "SessionEnd 훅이 end-by-project API 엔드포인트를 "
        "호출하여 세션을 종료하는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["hook", "session-end", "api"],
    hook_event="SessionEnd",
    conversation=[
        ConversationMessage(
            role="user",
            content="SessionEnd hook API 호출을 검증합니다.",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_content_patterns=[],
)

# ---------------------------------------------------------------------------
# Scenario: PreCompact hook calls session_end with auto-ended summary
# ---------------------------------------------------------------------------

PRECOMPACT_AUTO_ENDED = EvalScenario(
    id="hook_events_02",
    name="PreCompact hook auto-ended summary",
    description=(
        "PreCompact 훅이 session_end API를 "
        "'Auto-ended by PreCompact hook' 요약으로 호출하는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["hook", "precompact", "summary"],
    hook_event="PreCompact",
    conversation=[
        ConversationMessage(
            role="user",
            content="PreCompact hook auto-ended summary를 검증합니다.",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_content_patterns=[],
)

# ---------------------------------------------------------------------------
# Scenario: PreCompact hook exits 0 on API failure (non-blocking)
# ---------------------------------------------------------------------------

PRECOMPACT_NON_BLOCKING = EvalScenario(
    id="hook_events_03",
    name="PreCompact hook non-blocking on failure",
    description=(
        "PreCompact 훅이 API 실패 시 exit 0으로 "
        "비차단 종료하는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["hook", "precompact", "non-blocking"],
    hook_event="PreCompact",
    conversation=[
        ConversationMessage(
            role="user",
            content="PreCompact hook 비차단 종료를 검증합니다.",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_content_patterns=[],
)

# ---------------------------------------------------------------------------
# Scenario: SessionEnd hook in local mode uses Python direct call
# ---------------------------------------------------------------------------

SESSION_END_LOCAL_PYTHON = EvalScenario(
    id="hook_events_04",
    name="SessionEnd hook local mode Python direct",
    description=(
        "SessionEnd 훅이 local mode에서 Python으로 "
        "직접 end_session_by_project를 호출하는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["hook", "session-end", "local"],
    hook_event="SessionEnd",
    conversation=[
        ConversationMessage(
            role="user",
            content="SessionEnd hook local mode Python 호출을 검증합니다.",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_content_patterns=[],
)

ALL_SCENARIOS = [
    SESSION_END_API_CALL,
    PRECOMPACT_AUTO_ENDED,
    PRECOMPACT_NON_BLOCKING,
    SESSION_END_LOCAL_PYTHON,
]
