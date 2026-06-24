"""Canonical behavioral rules for mem-mesh hooks — Single Source of Truth.

All IDE-specific renderers (Kiro, Cursor, Claude Code) read from these
definitions. When rules change, bump PROMPT_VERSION and re-run the installer.

Usage:
    from app.cli.prompts.behaviors import CORE_RULES, SAVE_CRITERIA, PROMPT_VERSION
"""

from dataclasses import dataclass
from typing import List

# ---------------------------------------------------------------------------
# Prompt schema version — bump on ANY behavioral rule change
# ---------------------------------------------------------------------------

PROMPT_VERSION: int = 22


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """A single operational rule injected at session start."""

    key: str
    title: str  # Short title
    description: str  # Description (project_id placeholder: {project_id})


@dataclass(frozen=True)
class SaveCriteria:
    """When to save / skip auto-saving conversations."""

    save_when: List[str]
    skip_when: List[str]
    save_format: str  # MCP call example
    idempotency: str  # Duplicate save prevention rule


@dataclass(frozen=True)
class PinCriteria:
    """When to create / skip pin creation."""

    create_when: str
    skip_when: str
    pin_format: str  # MCP call example


@dataclass(frozen=True)
class SessionConfig:
    """Session resume / end configuration."""

    resume_call: str
    resume_description: str
    end_triggers: List[str]  # Example user session-end expressions


# ---------------------------------------------------------------------------
# Canonical definitions
# ---------------------------------------------------------------------------

CORE_RULES: List[Rule] = [
    Rule(
        key="coding_first",
        title="Answer with the work first",
        description=(
            "Return the code or answer first. Perform mem-mesh calls after the "
            "response work is complete. Do not start responses with status "
            "announcements such as 'I will search memory first.'"
        ),
    ),
    Rule(
        key="session_gate",
        title="Restore session context",
        description=(
            "At session start, call "
            'session_resume(project_id="{project_id}", expand="smart") and '
            "report only the useful counts: pins_count, in_progress_pins, "
            "open_pins, and completed_pins. If no active session exists, "
            "continue with the task; the first pin_add() or add() call creates "
            "the session."
        ),
    ),
    Rule(
        key="pin_tracking",
        title="Track work with Pin Gate (required)",
        description=(
            "Before starting task work, decide Pin Gate. If the request involves "
            "file edits, implementation, bug fixes, refactoring, migrations, "
            "multi-step investigation, or work that may continue into a later "
            'turn, immediately call pin_add(content, project_id="{project_id}", '
            "importance=3). For simple questions, explanations, lookups, "
            "read-only analysis, or basic checks, do not create a pin. Do not "
            "reuse an unrelated in_progress pin. State exactly one of "
            "`Pin created: <id>` or `No pin created: <reason>`. When the work is "
            "done, call pin_complete immediately; do not leave an active pin "
            "before the final response. (importance: 3=normal, 4=important, "
            "5=architecture)"
        ),
    ),
    Rule(
        key="selective_save",
        title="Save permanent memories selectively",
        description=(
            "Use add() only for decision, bug, incident, idea, and code_snippet "
            "memories. Routine task state belongs in pins."
        ),
    ),
    Rule(
        key="context_search",
        title="Use context search",
        description=(
            "When prior decisions, tasks, or design context are referenced, call "
            "search() before writing code."
        ),
    ),
    Rule(
        key="session_end",
        title="End sessions when requested",
        description=(
            "When the user explicitly says the session is done, finish the "
            'request and then call session_end(project_id="{project_id}").'
        ),
    ),
]

SAVE_CRITERIA = SaveCriteria(
    save_when=[
        "버그 진단/해결",
        "아키텍처 또는 설계 결정",
        "중요 설정 변경 또는 마이그레이션",
    ],
    skip_when=[
        '단순 질문/답변 ("뭐야?", "보여줘")',
        "파일 읽기만 한 경우",
        "이미 저장된 내용의 반복",
        "hook/설정 자체의 점검·수정·메타 대화 (hook 동작 확인, settings.json 수정 포함)",
    ],
    save_format=(
        'mcp_mem_mesh_add(content="Q: [질문]\\nA: [핵심 답변]", '
        'category, project_id="{project_id}", tags=[3-5개])'
    ),
    idempotency=(
        "방금 응답에 Memory ID(mcp_mem_mesh_add 결과)가 이미 있으면 "
        '"Already saved" 출력 후 즉시 종료.'
    ),
)

PIN_CRITERIA = PinCriteria(
    create_when=(
        "file edits, implementation, bug fixes, refactoring, migrations, "
        "multi-step investigation, or work that may continue into a later turn"
    ),
    skip_when=(
        "questions, explanation requests, lookups, read-only analysis, simple "
        "checks, or discussion about hooks themselves"
    ),
    pin_format=(
        'mcp_mem_mesh_pin_add(content="[one-line summary]", '
        'project_id="{project_id}", importance=3, tags=[...])\n'
        'Response marker: "Pin created: <id>" or "No pin created: <reason>"\n'
        'On completion: mcp_mem_mesh_pin_complete(pin_id="...") - required'
    ),
)

SESSION_CONFIG = SessionConfig(
    resume_call='session_resume(project_id="{project_id}", expand="smart")',
    resume_description=(
        "새 세션 시작 시 이전 맥락을 확인하고, "
        "미완료 핀이 있으면 사용자에게 간략히 알린다."
    ),
    end_triggers=["오늘 끝", "여기까지", "PR 올려줘"],
)


# ---------------------------------------------------------------------------
# LLM Reflection configuration (Enhanced profile)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReflectConfig:
    """Configuration for LLM reflection hook (Enhanced profile)."""

    model: str
    max_tokens: int
    timeout_seconds: int


REFLECT_CONFIG = ReflectConfig(
    model="claude-haiku-4-5-20251001",
    max_tokens=1024,
    timeout_seconds=20,
)


# ---------------------------------------------------------------------------
# Claude Code native prompt hook configuration (Stop event)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StopPromptConfig:
    """Keyword-based prompt hook config. Haiku picks category enum only."""

    max_reason_chars: int
    valid_categories: tuple


STOP_PROMPT_CONFIG = StopPromptConfig(
    max_reason_chars=80,
    valid_categories=("bug", "decision", "code_snippet", "idea", "incident"),
)
