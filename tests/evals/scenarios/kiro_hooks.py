"""Kiro hook format verification scenarios.

Tests that Kiro hook templates produce correctly formatted output:
  - JSON array format for hook entries
  - mem-mesh rules presence
  - Hook name prefix convention
"""

from __future__ import annotations

from tests.evals.models import (
    ConversationMessage,
    EvalScenario,
    EvalTier,
    ExpectedAction,
)

# ---------------------------------------------------------------------------
# Scenario: Kiro stop hook produces keyword-matched category output
# ---------------------------------------------------------------------------

KIRO_HOOKS_JSON_FORMAT = EvalScenario(
    id="kiro_hooks_01",
    name="Kiro stop hook JSON array format",
    description=(
        "Kiro stop hook이 agentResponse 이벤트에서 "
        "키워드 매칭 후 JSON 형식으로 mem-mesh API에 저장하는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["kiro", "hook", "format"],
    ide="kiro",
    hook_event="Stop",
    conversation=[
        ConversationMessage(
            role="user",
            content="Kiro stop hook의 출력 포맷을 검증합니다.",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_content_patterns=[],
)

# ---------------------------------------------------------------------------
# Scenario: Kiro rules text includes mem-mesh rules
# ---------------------------------------------------------------------------

KIRO_HOOKS_RULES_TEXT = EvalScenario(
    id="kiro_hooks_02",
    name="Kiro rules text includes mem-mesh rules",
    description=(
        "Kiro hooks.json에 등록된 규칙 텍스트에 "
        "mem-mesh 관련 규칙이 포함되어 있는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["kiro", "hook", "rules"],
    ide="kiro",
    conversation=[
        ConversationMessage(
            role="user",
            content="Kiro 규칙 텍스트에 mem-mesh 규칙이 있는지 검증합니다.",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_content_patterns=[],
)

# ---------------------------------------------------------------------------
# Scenario: Kiro hook name uses mem-mesh: prefix
# ---------------------------------------------------------------------------

KIRO_HOOKS_NAME_PREFIX = EvalScenario(
    id="kiro_hooks_03",
    name="Kiro hook name uses mem-mesh: prefix",
    description=(
        "Kiro hooks.json에 등록된 hook name이 "
        "'mem-mesh:' prefix를 사용하는지 검증"
    ),
    tier=EvalTier.DETERMINISTIC,
    tags=["kiro", "hook", "naming"],
    ide="kiro",
    conversation=[
        ConversationMessage(
            role="user",
            content="Kiro hook name prefix를 검증합니다.",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_content_patterns=[],
)

ALL_SCENARIOS = [KIRO_HOOKS_JSON_FORMAT, KIRO_HOOKS_RULES_TEXT, KIRO_HOOKS_NAME_PREFIX]
