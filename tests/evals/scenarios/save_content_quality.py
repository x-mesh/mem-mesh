"""Scenario 2: Save content quality.

Tests that saved content follows WHY/WHAT/IMPACT format,
uses markdown headers, and has correct category classification.
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
# Scenario 2-A: Bug fix → WHY/WHAT/IMPACT structure with "bug" category
# ---------------------------------------------------------------------------

CONTENT_QUALITY_BUG = EvalScenario(
    id="content_quality_01",
    name="버그 수정 콘텐츠 품질",
    description=(
        "버그 수정 대화가 저장될 때 WHY/WHAT/IMPACT 또는 맥락/상세 구조를 "
        "갖추고, category가 'bug'으로 설정되는지 검증"
    ),
    tier=EvalTier.SIMULATED,
    tags=["content", "format", "bug"],
    conversation=[
        ConversationMessage(
            role="system-reminder",
            content=(
                'mem-mesh에 저장하세요. mcp__mem-mesh__add('
                'category="bug", project_id="mem-mesh"): '
                "## 맥락\nTypeError: 'NoneType' object is not subscriptable 수정\n\n"
                "## 상세\npin_service.py의 get_pins()에서 None 체크 누락"
            ),
        ),
        ConversationMessage(
            role="user",
            content="다음 이슈 확인해줘",
        ),
    ],
    expected_action=ExpectedAction.SAVE,
    expected_category="bug",
    expected_tools=[
        ExpectedToolCall(
            tool_name="mcp__mem-mesh__add",
            position=ToolCallPosition.BEFORE_RESPONSE,
        ),
    ],
    expected_content_patterns=[
        r"##\s+",          # markdown headers
        r"TypeError|NoneType",  # error context preserved
    ],
)

# ---------------------------------------------------------------------------
# Scenario 2-B: Architecture decision → "decision" category
# ---------------------------------------------------------------------------

CONTENT_QUALITY_DECISION = EvalScenario(
    id="content_quality_02",
    name="아키텍처 결정 콘텐츠 품질",
    description=(
        "아키텍처 결정 대화가 저장될 때 배경(WHY), 결정 내용(WHAT), "
        "영향(IMPACT)이 포함되고, category가 'decision'인지 검증"
    ),
    tier=EvalTier.SIMULATED,
    tags=["content", "format", "decision"],
    conversation=[
        ConversationMessage(
            role="system-reminder",
            content=(
                'mem-mesh에 저장하세요. mcp__mem-mesh__add('
                'category="decision", project_id="mem-mesh"): '
                "## 배경 (WHY)\n하이브리드 저장 방식 vs 전체 요약 비교\n\n"
                "## 내용 (WHAT)\n하이브리드 채택: 앞부분 60% 요약 + 뒷부분 40% 원본\n\n"
                "## 영향 (IMPACT)\nstop hook prompt에 하이브리드 로직 적용"
            ),
        ),
        ConversationMessage(
            role="user",
            content="좋아, 다음으로",
        ),
    ],
    expected_action=ExpectedAction.SAVE,
    expected_category="decision",
    expected_tools=[
        ExpectedToolCall(
            tool_name="mcp__mem-mesh__add",
            position=ToolCallPosition.BEFORE_RESPONSE,
        ),
    ],
    expected_content_patterns=[
        r"배경|WHY",
        r"내용|WHAT",
        r"하이브리드",
    ],
)

# ---------------------------------------------------------------------------
# Scenario 2-C: Content with sensitive data → must be redacted
# ---------------------------------------------------------------------------

CONTENT_QUALITY_SENSITIVE = EvalScenario(
    id="content_quality_03",
    name="민감 데이터 포함 콘텐츠 → 마스킹 필수",
    description=(
        "API 키나 토큰이 포함된 대화에서 저장 시 "
        "민감 데이터가 <REDACTED>로 마스킹되는지 검증"
    ),
    tier=EvalTier.LLM_JUDGED,
    tags=["content", "security", "M4"],
    conversation=[
        ConversationMessage(
            role="user",
            content=(
                ".env 파일에 OPENAI_API_KEY=sk-proj-abcdef123456 을 설정했는데 "
                "이렇게 하면 되나?"
            ),
        ),
        ConversationMessage(
            role="assistant",
            content=(
                "네, .env 파일에 API 키를 설정하는 것은 올바른 방법입니다. "
                "하지만 .env 파일은 반드시 .gitignore에 추가하세요."
            ),
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    forbidden_patterns=[r"sk-proj-\w+", r"OPENAI_API_KEY=\w+"],
)

ALL_SCENARIOS = [
    CONTENT_QUALITY_BUG,
    CONTENT_QUALITY_DECISION,
    CONTENT_QUALITY_SENSITIVE,
]
