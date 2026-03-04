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
    REFLECT_CONFIG,
    SAVE_CRITERIA,
    SESSION_CONFIG,
    STOP_PROMPT_CONFIG,
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
        f"### 세션 복원 결과\n```json\n{resume_data}\n```\n\n" if resume_data else ""
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
        f'저장 시: 버그 수정은 category="bug", 설계 결정은 category="decision", '
        f'코드 패턴은 category="code_snippet"으로 '
        f'add(project_id="{project_id}")를 호출하세요.\n'
        f"일상적 작업이었다면 무시하세요."
    )


# ---------------------------------------------------------------------------
# Version marker for generated scripts
# ---------------------------------------------------------------------------


VERSION_MARKER = f"# mem-mesh-hooks prompt-version: {PROMPT_VERSION}"


def render_claude_stop_prompt() -> str:
    """Render the prompt for Claude Code's native ``type: "prompt"`` Stop hook.

    Keyword-based approach: Haiku picks a category enum token only.
    No free-form text in reason — guaranteed JSON-safe output.
    Claude Code replaces ``$ARGUMENTS`` with stop-hook input at runtime.
    """
    categories = ", ".join(STOP_PROMPT_CONFIG.valid_categories)
    save_list = "\n".join(f"- {c}" for c in SAVE_CRITERIA.save_when)
    skip_list = "\n".join(f"- {c}" for c in SAVE_CRITERIA.skip_when)

    return (
        "대화의 마지막 응답을 분석하여 mem-mesh 저장 여부를 판단하세요.\n\n"
        "$ARGUMENTS\n\n"
        "## 판단 순서 (위에서 아래로, 첫 매치 시 즉시 응답)\n\n"
        '1. stop_hook_active가 true → {"ok": true}\n'
        "2. 이 턴에서 이미 mcp__mem-mesh__add가 호출됨 "
        '→ {"ok": true}\n'
        f"3. 스킵 기준 해당 → {'{'}\"ok\": true{'}'}\n"
        f"4. 저장 기준 해당 → {'{'}\"ok\": false, \"reason\": "
        f"\"mcp__mem-mesh__add(category=CATEGORY) 요약+원본 저장\"{'}'}  \n"
        f"   CATEGORY는 다음 중 하나: {categories}\n"
        f'5. 기본값 → {{"ok": true}}\n\n'
        f"## 저장 기준 (하나라도 해당 시 저장)\n{save_list}\n\n"
        f"## 스킵 기준 (저장 기준보다 우선)\n{skip_list}\n\n"
        "## 저장 형식\n"
        "Opus가 mcp__mem-mesh__add 호출 시 content에 다음을 포함:\n"
        "- 1~3줄 요약 (## 요약)\n"
        "- 원본 대화 핵심 부분 (## 원본)\n\n"
        "## JSON 출력 규칙\n"
        "- 유효한 JSON 한 줄만 출력\n"
        "- reason에는 mcp__mem-mesh__add(category=X) 요약+원본 저장 형식만 허용\n"
        f"- reason 최대 {STOP_PROMPT_CONFIG.max_reason_chars}자\n"
        "- 코드블록, 설명 텍스트, 줄바꿈 금지"
    )


def render_enhanced_stop_prompt() -> str:
    """Render the prompt for the Enhanced profile's Haiku API stop hook.

    Haiku outputs plain-text ``SAVE|category|summary`` or ``SKIP``.
    Python wraps the result with json.dumps() for JSON safety.
    """
    categories = ", ".join(STOP_PROMPT_CONFIG.valid_categories)
    save_list = "\n".join(f"- {c}" for c in SAVE_CRITERIA.save_when)
    skip_list = "\n".join(f"- {c}" for c in SAVE_CRITERIA.skip_when)

    return (
        "Analyze the conversation and decide whether to save it to mem-mesh.\n\n"
        f"## Save criteria (save if ANY match)\n{save_list}\n\n"
        f"## Skip criteria (skip takes priority)\n{skip_list}\n\n"
        "## Output format (EXACTLY one line, no markdown)\n"
        f"Save: SAVE|CATEGORY|one-line summary (50 chars max)\n"
        f"  CATEGORY: {categories}\n"
        "Skip: SKIP\n\n"
        "Examples:\n"
        "  SAVE|bug|Fixed ZeroDivisionError in search tests\n"
        "  SAVE|decision|Chose hybrid approach for stop hook\n"
        "  SKIP"
    )


def render_reflect_prompt() -> str:
    """Render the LLM reflection prompt for the Enhanced profile.

    This prompt is sent to Haiku to analyze conversation content and extract
    structured insights (decisions, patterns, problems, open items).
    Single source of truth for both API and Local reflect hooks.
    """
    return (
        "You are an AI memory analyst. Analyze the following conversation excerpt "
        "and extract structured insights.\n\n"
        "## Instructions\n"
        "Extract the following categories from the conversation:\n"
        "1. **Decisions**: Architecture choices, technology selections, design patterns chosen\n"
        "2. **Patterns**: Reusable code patterns, conventions, or best practices discovered\n"
        "3. **Problems**: Bugs found, errors diagnosed, issues identified\n"
        "4. **Open Items**: Unresolved questions, TODOs, future work mentioned\n\n"
        "## Output Format\n"
        "Respond in markdown with these exact section headers:\n"
        "### Decisions\n"
        "### Patterns\n"
        "### Problems\n"
        "### Open Items\n\n"
        "Use bullet points under each section. If a section has no items, write '- None'.\n"
        "Be concise — each bullet should be 1-2 sentences max.\n"
        "Write in the same language as the conversation (Korean or English)."
    )


def render_reflect_config_json() -> str:
    """Return REFLECT_CONFIG values as a JSON-friendly dict string for templates."""
    return (
        f'{{"model": "{REFLECT_CONFIG.model}", '
        f'"max_tokens": {REFLECT_CONFIG.max_tokens}, '
        f'"timeout": {REFLECT_CONFIG.timeout_seconds}}}'
    )


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
