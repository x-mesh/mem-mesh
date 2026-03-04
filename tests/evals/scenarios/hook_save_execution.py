"""Scenario 1: Stop hook → save execution.

Tests that when system-reminder contains a save instruction,
mcp__mem-mesh__add is called BEFORE the assistant response.
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
# Scenario 1-A: system-reminder contains "mem-mesh에 저장하세요" → SAVE
# ---------------------------------------------------------------------------

HOOK_SAVE_BASIC = EvalScenario(
    id="hook_save_01",
    name="Stop hook → mcp__mem-mesh__add 실행",
    description=(
        "system-reminder에 'mem-mesh에 저장하세요' + mcp__mem-mesh__add 지시가 있을 때, "
        "AI가 사용자 메시지 처리 전에 저장을 먼저 실행하는지 검증"
    ),
    tier=EvalTier.SIMULATED,
    tags=["hook", "save", "M5"],
    conversation=[
        ConversationMessage(
            role="system-reminder",
            content=(
                'Stop hook feedback: Prompt hook condition was met: '
                'mem-mesh에 저장하세요. mcp__mem-mesh__add('
                'category="bug", project_id="mem-mesh"): '
                "## 맥락\nZeroDivisionError 버그를 수정했습니다.\n\n"
                "## 상세\ntests/test_real_data_search.py에서 빈 DB일 때 "
                "avg_score 계산에서 ZeroDivisionError 발생. guard 조건 추가로 수정."
            ),
        ),
        ConversationMessage(
            role="user",
            content="다음 작업으로 넘어가자",
        ),
    ],
    expected_action=ExpectedAction.SAVE,
    expected_category="bug",
    expected_tools=[
        ExpectedToolCall(
            tool_name="mcp__mem-mesh__add",
            position=ToolCallPosition.BEFORE_RESPONSE,
            args_contains={"category": "bug"},
        ),
    ],
    expected_content_patterns=[r"ZeroDivision", r"버그|bug"],
)

# ---------------------------------------------------------------------------
# Scenario 1-B: system-reminder has save instruction but AI already saved → SKIP
# ---------------------------------------------------------------------------

HOOK_SAVE_ALREADY_SAVED = EvalScenario(
    id="hook_save_02",
    name="Stop hook → 이미 저장됨 (loop guard)",
    description=(
        "system-reminder에 저장 지시가 있지만, 직전 응답에 이미 Memory ID가 "
        "포함되어 있는 경우 중복 저장하지 않는지 검증"
    ),
    tier=EvalTier.SIMULATED,
    tags=["hook", "skip", "loop-guard"],
    conversation=[
        ConversationMessage(
            role="system-reminder",
            content=(
                'Stop hook feedback: mem-mesh에 저장하세요. '
                'mcp__mem-mesh__add(category="decision", project_id="mem-mesh"): '
                "## 맥락\n하이브리드 저장 방식 채택"
            ),
        ),
        ConversationMessage(
            role="assistant",
            content=(
                "mcp__mem-mesh__add를 호출하여 저장했습니다. "
                "Memory ID: f77e6163-430c-49b4-b0ed-0dd6ec3ab72f\n\n"
                "다른 작업 있으신가요?"
            ),
        ),
        ConversationMessage(
            role="user",
            content="네, 다음 작업 진행해줘",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_tools=[],
    forbidden_patterns=[r"mcp__mem-mesh__add"],
)

# ---------------------------------------------------------------------------
# Scenario 1-C: No system-reminder save instruction → normal flow
# ---------------------------------------------------------------------------

HOOK_SAVE_NO_INSTRUCTION = EvalScenario(
    id="hook_save_03",
    name="system-reminder에 저장 지시 없음 → 일반 흐름",
    description=(
        "system-reminder에 저장 지시가 없는 일반 대화에서 "
        "불필요하게 mcp__mem-mesh__add를 호출하지 않는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["hook", "skip", "normal"],
    conversation=[
        ConversationMessage(
            role="user",
            content="이 파일 뭐하는 건지 설명해줘",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_tools=[],
)

ALL_SCENARIOS = [HOOK_SAVE_BASIC, HOOK_SAVE_ALREADY_SAVED, HOOK_SAVE_NO_INSTRUCTION]
