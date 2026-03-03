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

PROMPT_VERSION: int = 7


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """A single operational rule injected at session start."""

    key: str
    title: str  # 짧은 제목
    description: str  # 설명 (project_id 플레이스홀더: {project_id})


@dataclass(frozen=True)
class SaveCriteria:
    """When to save / skip auto-saving conversations."""

    save_when: List[str]
    skip_when: List[str]
    save_format: str  # MCP 호출 예시
    idempotency: str  # 중복 저장 방지 규칙


@dataclass(frozen=True)
class PinCriteria:
    """When to create / skip pin creation."""

    create_when: str
    skip_when: str
    pin_format: str  # MCP 호출 예시


@dataclass(frozen=True)
class SessionConfig:
    """Session resume / end configuration."""

    resume_call: str
    resume_description: str
    end_triggers: List[str]  # 사용자의 세션 종료 표현 예시


# ---------------------------------------------------------------------------
# Canonical definitions
# ---------------------------------------------------------------------------

CORE_RULES: List[Rule] = [
    Rule(
        key="coding_first",
        title="코딩 응답 우선",
        description=(
            "코드와 답변을 먼저 출력. mem-mesh 호출은 답변 완료 후 수행. "
            "응답 서두에 '메모리를 검색하겠습니다' 같은 안내를 넣지 않는다."
        ),
    ),
    Rule(
        key="pin_tracking",
        title="Pin으로 작업 추적",
        description=(
            '작업 시작 시 pin_add(content, project_id="{project_id}", importance=3), '
            "완료 시 pin_complete. (importance: 3=일반, 4=중요, 5=아키텍처)"
        ),
    ),
    Rule(
        key="selective_save",
        title="영구 메모리는 선별적",
        description=(
            "decision, bug, incident, idea, code_snippet만 add()로 저장. "
            "일상적 작업 상태는 pin으로 충분."
        ),
    ),
    Rule(
        key="context_search",
        title="맥락 검색 활용",
        description=(
            "과거 결정/작업/설계가 언급되면 코드 작성 전에 search()로 기존 맥락 확인."
        ),
    ),
    Rule(
        key="session_end",
        title="세션 종료",
        description=(
            "사용자가 완료를 명시하면 요청 처리 후 "
            'session_end(project_id="{project_id}").'
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
    create_when="코드 수정/구현/버그 수정/리팩토링 등 실제 코드 변경이 필요한 요청",
    skip_when="질문, 설명 요청, 분석 요청, 점검, 리뷰, 단순 확인, hook 자체 논의",
    pin_format=(
        'mcp_mem_mesh_pin_add(content="[1줄 요약]", '
        'project_id="{project_id}", importance=3, tags=[...])'
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
