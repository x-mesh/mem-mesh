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

# ---------------------------------------------------------------------------
# Scenario: Cursor beforeSubmitPrompt hook format
# ---------------------------------------------------------------------------

CURSOR_BEFORE_SUBMIT_FORMAT = EvalScenario(
    id="cursor_hooks_04",
    name="Cursor beforeSubmitPrompt additionalContext JSON",
    description=(
        "Cursor beforeSubmitPrompt hook이 additionalContext를 포함한 "
        "hookSpecificOutput JSON을 출력하는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["cursor", "hook", "before-submit-prompt", "format"],
    ide="cursor",
    hook_event="beforeSubmitPrompt",
    conversation=[
        ConversationMessage(
            role="user",
            content="Cursor beforeSubmitPrompt 출력 포맷을 검증합니다.",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_content_patterns=[],
)

# ---------------------------------------------------------------------------
# Scenario: Cursor preCompact hook format
# ---------------------------------------------------------------------------

CURSOR_PRECOMPACT_FORMAT = EvalScenario(
    id="cursor_hooks_05",
    name="Cursor preCompact additionalContext JSON",
    description=(
        "Cursor preCompact hook이 additionalContext를 포함한 "
        "hookSpecificOutput JSON을 출력하는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["cursor", "hook", "precompact", "format"],
    ide="cursor",
    hook_event="preCompact",
    conversation=[
        ConversationMessage(
            role="user",
            content="Cursor preCompact 출력 포맷을 검증합니다.",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_content_patterns=[],
)

# ---------------------------------------------------------------------------
# Scenario: Cursor subagentStart hook format
# ---------------------------------------------------------------------------

CURSOR_SUBAGENT_START_FORMAT = EvalScenario(
    id="cursor_hooks_06",
    name="Cursor subagentStart additionalContext JSON",
    description=(
        "Cursor subagentStart hook이 additionalContext를 포함한 "
        "hookSpecificOutput JSON을 출력하는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["cursor", "hook", "subagent-start", "format"],
    ide="cursor",
    hook_event="subagentStart",
    conversation=[
        ConversationMessage(
            role="user",
            content="Cursor subagentStart 출력 포맷을 검증합니다.",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_content_patterns=[],
)

# ---------------------------------------------------------------------------
# Scenario: Cursor subagentStop hook script presence
# ---------------------------------------------------------------------------

CURSOR_SUBAGENT_STOP_SCRIPT = EvalScenario(
    id="cursor_hooks_07",
    name="Cursor subagentStop script executable",
    description="Cursor subagentStop 훅 스크립트가 설치/실행 가능한지 검증",
    tier=EvalTier.DETERMINISTIC,
    tags=["cursor", "hook", "subagent-stop", "script"],
    ide="cursor",
    hook_event="subagentStop",
    conversation=[
        ConversationMessage(
            role="user",
            content="Cursor subagentStop 설치 상태를 검증합니다.",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_content_patterns=[],
)

ALL_SCENARIOS = [
    CURSOR_SESSION_START_FORMAT,
    CURSOR_STOP_FOLLOWUP,
    CURSOR_SESSION_END_API,
    CURSOR_BEFORE_SUBMIT_FORMAT,
    CURSOR_PRECOMPACT_FORMAT,
    CURSOR_SUBAGENT_START_FORMAT,
    CURSOR_SUBAGENT_STOP_SCRIPT,
]
