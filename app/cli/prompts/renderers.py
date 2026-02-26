"""IDE-specific renderers that transform shared behaviors into hook formats.

Each renderer reads from behaviors.py (the single source of truth) and
produces output in the native format for each IDE:
  - Kiro: .kiro.hook JSON with askAgent prompts
  - Cursor: additional_context / followup_message strings
  - Claude Code / generic: markdown rules text

Usage:
    from app.cli.prompts.renderers import render_kiro_auto_save, render_rules_text
"""

from typing import Any, Dict, List

from app.cli.prompts.behaviors import (
    CORE_RULES,
    PIN_CRITERIA,
    PROMPT_VERSION,
    SAVE_CRITERIA,
    SESSION_CONFIG,
)


# ---------------------------------------------------------------------------
# Generic: markdown rules text (used by Cursor additional_context, Claude CLAUDE.md)
# ---------------------------------------------------------------------------


def render_rules_text(project_id: str = "mem-mesh") -> str:
    """Render core rules as numbered markdown list.

    Used in Cursor sessionStart (additional_context) and Claude Code contexts.
    """
    lines: List[str] = []
    for i, rule in enumerate(CORE_RULES, 1):
        desc = rule.description.replace("{project_id}", project_id)
        lines.append(f"{i}. **{rule.title}** — {desc}")
    return "\n".join(lines)


def render_save_criteria_text() -> str:
    """Render save/skip criteria as a concise prompt section."""
    save_list = "\n".join(f"- {c}" for c in SAVE_CRITERIA.save_when)
    skip_list = "\n".join(f"- {c}" for c in SAVE_CRITERIA.skip_when)
    return (
        f"**저장 O (다음 중 하나 해당 시)**:\n{save_list}\n\n"
        f"**저장 X (스킵)**:\n{skip_list}"
    )


# ---------------------------------------------------------------------------
# Kiro renderers: produce .kiro.hook JSON dicts
# ---------------------------------------------------------------------------


def render_kiro_auto_save(project_id: str = "mem-mesh") -> Dict[str, Any]:
    """Generate auto-save-conversations.kiro.hook content.

    Kiro askAgent hook that decides whether to save a conversation.
    """
    save_format = SAVE_CRITERIA.save_format.replace("{project_id}", project_id)
    prompt = (
        f"{SAVE_CRITERIA.idempotency}\n\n"
        f"없으면 아래 기준으로 저장 여부 판단:\n\n"
        f"{render_save_criteria_text()}\n\n"
        f"저장 시: {save_format}\n"
        f"출력: Saved | ID: [id]\n"
        f"스킵 시: 아무것도 출력하지 마세요."
    )
    return {
        "name": "Auto-save Conversations",
        "description": "에이전트 응답 완료 시 중요 대화만 선택적으로 mem-mesh에 저장",
        "version": str(PROMPT_VERSION),
        "when": {"type": "agentStop"},
        "then": {"type": "askAgent", "prompt": prompt},
    }


def render_kiro_auto_create_pin(project_id: str = "mem-mesh") -> Dict[str, Any]:
    """Generate auto-create-pin-on-task.kiro.hook content.

    Kiro askAgent hook that decides whether to create a pin on task start.
    """
    pin_format = PIN_CRITERIA.pin_format.replace("{project_id}", project_id)
    prompt = (
        f"사용자 메시지가 구체적 작업 요청인지 판단하세요.\n\n"
        f"**Pin 생성 O**: {PIN_CRITERIA.create_when}\n"
        f"**Pin 생성 X**: {PIN_CRITERIA.skip_when}\n\n"
        f"생성 시: {pin_format}\n"
        f"출력: Pin [id] | [설명]\n"
        f"아니면: 무시 (아무것도 출력하지 마세요)"
    )
    return {
        "name": "Auto Create Pin on Task Start",
        "description": "명확한 작업 요청 시에만 Pin 생성",
        "version": str(PROMPT_VERSION),
        "when": {"type": "promptSubmit"},
        "then": {"type": "askAgent", "prompt": prompt},
    }


def render_kiro_load_context(project_id: str = "mem-mesh") -> Dict[str, Any]:
    """Generate load-project-context.kiro.hook content.

    Kiro askAgent hook for loading project context on demand.
    """
    resume_call = SESSION_CONFIG.resume_call.replace("{project_id}", project_id)
    prompt = (
        f"{SESSION_CONFIG.resume_description}\n\n"
        f"**실행**: {resume_call}\n\n"
        f"**수집 항목**:\n"
        f"1. 프로젝트의 최근 작업 (task, bug, decision)\n"
        f"2. 진행 중인 작업 (in_progress 상태)\n"
        f"3. 미해결 이슈 (open, blocked 상태)\n"
        f"4. 프로젝트 상태 요약\n"
        f"5. 다음 우선순위 작업 제안\n\n"
        f"**프로젝트 식별**:\n"
        f"- 현재 작업 중인 프로젝트를 자동으로 감지하세요\n"
        f"- 프로젝트 이름이 불명확하면 '{project_id}'를 기본값으로 사용\n\n"
        f"**필터링**: project_id 기준, 최근 30일 내 작업만 포함"
    )
    return {
        "name": "Load Project Context",
        "description": "새 세션 시작 시 프로젝트별 컨텍스트 로드 (동적 필터링)",
        "version": str(PROMPT_VERSION),
        "when": {"type": "userTriggered"},
        "then": {"type": "askAgent", "prompt": prompt},
    }


def render_kiro_hooks(project_id: str = "mem-mesh") -> List[Dict[str, Any]]:
    """Generate all behavioral Kiro hooks (not utility hooks).

    Returns a list of .kiro.hook JSON dicts for:
    - auto-save-conversations
    - auto-create-pin-on-task
    - load-project-context
    """
    return [
        render_kiro_auto_save(project_id),
        render_kiro_auto_create_pin(project_id),
        render_kiro_load_context(project_id),
    ]


# ---------------------------------------------------------------------------
# Cursor renderers
# ---------------------------------------------------------------------------


def render_cursor_context(
    project_id: str = "mem-mesh",
    resume_data: str = "",
) -> str:
    """Build the additional_context string for Cursor sessionStart hook.

    This is injected into the agent's context at the start of a Cursor session.
    """
    rules = render_rules_text(project_id)
    resume_section = (
        f"### 세션 복원 결과\n```json\n{resume_data}\n```\n\n"
        if resume_data
        else ""
    )
    return (
        f"## mem-mesh Memory Integration (Auto-loaded)\n\n"
        f"{resume_section}"
        f"### 작업 규칙\n{rules}"
    )


def render_cursor_followup(project_id: str = "mem-mesh") -> str:
    """Build the followup_message for Cursor stop hook.

    Sent to the agent when meaningful tool use is detected,
    suggesting it save important conversations.
    """
    save_list = ", ".join(SAVE_CRITERIA.save_when)
    skip_list = ", ".join(SAVE_CRITERIA.skip_when)
    return (
        f"방금 완료한 작업이 중요하다면, mem-mesh에 기록해주세요.\n\n"
        f"**저장 기준**: {save_list}\n"
        f"**스킵 기준**: {skip_list}\n\n"
        f"저장 시: 버그 수정은 category=\"bug\", 설계 결정은 category=\"decision\", "
        f"코드 패턴은 category=\"code_snippet\"으로 "
        f'add(project_id="{project_id}")를 호출하세요.\n'
        f"일상적 작업이었다면 무시하세요."
    )


# ---------------------------------------------------------------------------
# Version marker for generated scripts
# ---------------------------------------------------------------------------


VERSION_MARKER = f"# mem-mesh-hooks prompt-version: {PROMPT_VERSION}"


def extract_prompt_version(content: str) -> int:
    """Extract prompt version from a generated script's version marker.

    Returns 0 if no version marker is found.
    """
    for line in content.splitlines():
        if line.startswith("# mem-mesh-hooks prompt-version:"):
            try:
                return int(line.split(":")[-1].strip())
            except ValueError:
                return 0
    return 0
