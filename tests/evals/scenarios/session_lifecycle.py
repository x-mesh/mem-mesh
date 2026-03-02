"""Scenario 4: Session lifecycle.

Tests that session_resume is called on first message
and session_end is called when the user signals completion.
"""

from __future__ import annotations

from tests.evals.models import (
    ConversationMessage,
    EvalScenario,
    EvalTier,
    ExpectedAction,
    ExpectedToolCall,
    ToolCallPosition,
)

# ---------------------------------------------------------------------------
# Scenario 4-A: First message → session_resume expected
# ---------------------------------------------------------------------------

SESSION_RESUME_FIRST_MSG = EvalScenario(
    id="session_lifecycle_01",
    name="첫 메시지 → session_resume 호출",
    description=(
        "대화의 첫 메시지에서 session_resume(project_id, expand='smart')가 "
        "호출되는지 검증 (M1 규칙)"
    ),
    tier=EvalTier.LLM_JUDGED,
    tags=["session", "resume", "M1"],
    conversation=[
        ConversationMessage(
            role="user",
            content="안녕, 오늘 작업 시작할게",
        ),
    ],
    expected_action=ExpectedAction.SKIP,  # no save, just session_resume
    expected_tools=[
        ExpectedToolCall(
            tool_name="mcp__mem-mesh__session_resume",
            position=ToolCallPosition.BEFORE_RESPONSE,
            args_contains={"expand": "smart"},
        ),
    ],
)

# ---------------------------------------------------------------------------
# Scenario 4-B: User says "오늘 끝" → session_end expected
# ---------------------------------------------------------------------------

SESSION_END_EXPLICIT = EvalScenario(
    id="session_lifecycle_02",
    name="'오늘 끝' → session_end 호출",
    description=(
        "사용자가 '오늘 끝'이라고 말하면 요청 처리 후 "
        "session_end(project_id, summary)가 호출되는지 검증 (M2 규칙)"
    ),
    tier=EvalTier.LLM_JUDGED,
    tags=["session", "end", "M2"],
    conversation=[
        ConversationMessage(
            role="assistant",
            content="버그 수정이 완료되었습니다. 다른 작업이 있으신가요?",
        ),
        ConversationMessage(
            role="user",
            content="오늘 끝! 수고했어",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_tools=[
        ExpectedToolCall(
            tool_name="mcp__mem-mesh__session_end",
            position=ToolCallPosition.AFTER_RESPONSE,
        ),
    ],
)

# ---------------------------------------------------------------------------
# Scenario 4-C: "PR 올려줘" → session_end after PR
# ---------------------------------------------------------------------------

SESSION_END_PR = EvalScenario(
    id="session_lifecycle_03",
    name="'PR 올려줘' → 처리 후 session_end",
    description=(
        "사용자가 'PR 올려줘'라고 말하면 PR 처리 후 "
        "session_end가 호출되는지 검증 (M2 end_triggers)"
    ),
    tier=EvalTier.LLM_JUDGED,
    tags=["session", "end", "M2", "pr"],
    conversation=[
        ConversationMessage(
            role="assistant",
            content="리팩토링 작업이 모두 완료되었습니다.",
        ),
        ConversationMessage(
            role="user",
            content="PR 올려줘",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_tools=[
        ExpectedToolCall(
            tool_name="mcp__mem-mesh__session_end",
            position=ToolCallPosition.AFTER_RESPONSE,
        ),
    ],
)

ALL_SCENARIOS = [SESSION_RESUME_FIRST_MSG, SESSION_END_EXPLICIT, SESSION_END_PR]
