"""Scenario 3: Skip criteria accuracy.

Tests that trivial conversations (simple Q&A, file reads, meta-talk)
are correctly identified and NOT saved.
"""

from __future__ import annotations

from tests.evals.models import (
    ConversationMessage,
    EvalScenario,
    EvalTier,
    ExpectedAction,
)

# ---------------------------------------------------------------------------
# Scenario 3-A: Simple Q&A → SKIP
# ---------------------------------------------------------------------------

SKIP_SIMPLE_QA = EvalScenario(
    id="skip_criteria_01",
    name="단순 질문/답변 → 스킵",
    description="'이 파일 뭐야?' 같은 단순 질문은 저장하지 않는지 검증",
    tier=EvalTier.SIMULATED,
    tags=["skip", "trivial", "qa"],
    conversation=[
        ConversationMessage(
            role="user",
            content="이 파일 뭐야?",
        ),
        ConversationMessage(
            role="assistant",
            content=(
                "이 파일은 `app/core/version.py`로, 프로젝트 버전 정보를 관리하는 "
                "단일 소스 파일입니다.\n\n```python\nVERSION = '1.1.0'\n```\n\n"
                "현재 버전은 1.1.0입니다."
            ),
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_tools=[],
)

# ---------------------------------------------------------------------------
# Scenario 3-B: File read only → SKIP
# ---------------------------------------------------------------------------

SKIP_FILE_READ = EvalScenario(
    id="skip_criteria_02",
    name="파일 읽기만 → 스킵",
    description="파일 내용을 읽어서 보여주기만 한 경우 저장하지 않는지 검증",
    tier=EvalTier.SIMULATED,
    tags=["skip", "trivial", "file-read"],
    conversation=[
        ConversationMessage(
            role="user",
            content="pyproject.toml 보여줘",
        ),
        ConversationMessage(
            role="assistant",
            content=(
                "```toml\n[project]\nname = \"mem-mesh\"\nversion = \"1.1.0\"\n"
                "description = \"Centralized memory system for AI development tools\"\n"
                "```\n\n위 내용이 현재 pyproject.toml의 주요 설정입니다."
            ),
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_tools=[],
)

# ---------------------------------------------------------------------------
# Scenario 3-C: Hook/meta discussion → SKIP
# ---------------------------------------------------------------------------

SKIP_META_TALK = EvalScenario(
    id="skip_criteria_03",
    name="Hook/설정 메타 대화 → 스킵",
    description=(
        "hook 동작 확인, settings.json 수정 같은 메타 대화는 "
        "저장하지 않는지 검증"
    ),
    tier=EvalTier.SIMULATED,
    tags=["skip", "meta", "hook"],
    conversation=[
        ConversationMessage(
            role="user",
            content="stop hook이 제대로 작동하는지 확인해봐",
        ),
        ConversationMessage(
            role="assistant",
            content=(
                "settings.json의 hooks 설정을 확인했습니다.\n\n"
                "```json\n\"hooks\": {\n  \"Stop\": [{\n    \"type\": \"prompt\",\n"
                "    \"prompt\": \"...\"\n  }]\n}\n```\n\n"
                "Stop hook이 prompt 타입으로 올바르게 설정되어 있습니다."
            ),
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_tools=[],
)

# ---------------------------------------------------------------------------
# Scenario 3-D: Already saved content repeated → SKIP
# ---------------------------------------------------------------------------

SKIP_ALREADY_SAVED = EvalScenario(
    id="skip_criteria_04",
    name="이미 저장된 내용 반복 → 스킵",
    description="이전에 저장한 내용과 동일한 대화가 반복될 때 중복 저장하지 않는지 검증",
    tier=EvalTier.SIMULATED,
    tags=["skip", "idempotency"],
    conversation=[
        ConversationMessage(
            role="assistant",
            content=(
                "mcp__mem-mesh__add를 호출하여 저장했습니다. "
                "Memory ID: abc-123-def\n\n"
                "ZeroDivisionError 버그 수정 내용을 저장했습니다."
            ),
        ),
        ConversationMessage(
            role="user",
            content="잘됐다. 다음은?",
        ),
    ],
    expected_action=ExpectedAction.SKIP,
    expected_tools=[],
)

ALL_SCENARIOS = [SKIP_SIMPLE_QA, SKIP_FILE_READ, SKIP_META_TALK, SKIP_ALREADY_SAVED]
