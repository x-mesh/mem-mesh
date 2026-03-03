"""Cursor hook format verification scenarios.

Tests that Cursor hook templates produce correctly formatted output:
  - sessionStart outputs additional_context JSON
  - stop hook includes followup message
  - sessionEnd script calls session_end API
"""

from __future__ import annotations

from tests.evals.models import (
    ConversationMessage,
    EvalScenario,
    EvalTier,
    ExpectedAction,
)

# ---------------------------------------------------------------------------
# Scenario: Cursor session-start outputs additional_context JSON
# ---------------------------------------------------------------------------

CURSOR_SESSION_START_FORMAT = EvalScenario(
    id="cursor_hooks_01",
    name="Cursor session-start additional_context JSON",
    description=(
        "Cursor session-start hook이 additional_context 키를 포함한 "
        "JSON을 stdout으로 출력하는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["cursor", "hook", "session-start", "format"],
    ide="cursor",
    hook_event="SessionStart",
    conversation=[
        ConversationMessage(
            role="user",
            content="Cursor session-start 출력 포맷을 검증합니다.",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_content_patterns=[],
)

# ---------------------------------------------------------------------------
# Scenario: Cursor stop hook includes followup message
# ---------------------------------------------------------------------------

CURSOR_STOP_FOLLOWUP = EvalScenario(
    id="cursor_hooks_02",
    name="Cursor stop hook followup message",
    description=(
        "Cursor stop hook이 의미 있는 tool use가 있었을 때 "
        "followup_message를 포함한 JSON을 출력하는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["cursor", "hook", "stop", "followup"],
    ide="cursor",
    hook_event="Stop",
    conversation=[
        ConversationMessage(
            role="user",
            content="Cursor stop hook followup 메시지를 검증합니다.",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_content_patterns=[],
)

# ---------------------------------------------------------------------------
# Scenario: Cursor sessionEnd script calls session_end API
# ---------------------------------------------------------------------------

CURSOR_SESSION_END_API = EvalScenario(
    id="cursor_hooks_03",
    name="Cursor sessionEnd calls session_end API",
    description=(
        "Cursor sessionEnd 스크립트가 end-by-project API를 "
        "호출하는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["cursor", "hook", "session-end", "api"],
    ide="cursor",
    hook_event="SessionEnd",
    conversation=[
        ConversationMessage(
            role="user",
            content="Cursor sessionEnd API 호출을 검증합니다.",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_content_patterns=[],
)

ALL_SCENARIOS = [
    CURSOR_SESSION_START_FORMAT,
    CURSOR_STOP_FOLLOWUP,
    CURSOR_SESSION_END_API,
]
