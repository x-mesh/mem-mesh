"""Shared fixtures for DX eval tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.cli.prompts.behaviors import SAVE_CRITERIA, STOP_PROMPT_CONFIG
from tests.evals.models import EvalResult, EvalScenario, EvalTier, GradeResult

# ---------------------------------------------------------------------------
# Result persistence
# ---------------------------------------------------------------------------

RESULTS_DIR = Path(__file__).parent / "results"


def save_grade_results(results: List[GradeResult], filename: str) -> Path:
    """Save grade results to JSON for later analysis."""
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / filename
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "results": [r.model_dump(mode="json") for r in results],
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return path


# ---------------------------------------------------------------------------
# Scenario collection
# ---------------------------------------------------------------------------


def collect_scenarios(*tiers: EvalTier) -> List[EvalScenario]:
    """Collect all scenarios from scenario modules, optionally filtered by tier."""
    from tests.evals.scenarios.hook_save_execution import (
        ALL_SCENARIOS as HOOK_SCENARIOS,
    )
    from tests.evals.scenarios.save_content_quality import (
        ALL_SCENARIOS as CONTENT_SCENARIOS,
    )
    from tests.evals.scenarios.session_lifecycle import (
        ALL_SCENARIOS as SESSION_SCENARIOS,
    )
    from tests.evals.scenarios.skip_criteria import ALL_SCENARIOS as SKIP_SCENARIOS
    from tests.evals.scenarios.websocket_notification import (
        ALL_SCENARIOS as WS_SCENARIOS,
    )

    from tests.evals.scenarios.kiro_hooks import ALL_SCENARIOS as KIRO_SCENARIOS
    from tests.evals.scenarios.cursor_hooks import ALL_SCENARIOS as CURSOR_SCENARIOS
    from tests.evals.scenarios.hook_events import ALL_SCENARIOS as HOOK_EVENT_SCENARIOS

    all_scenarios = (
        HOOK_SCENARIOS
        + CONTENT_SCENARIOS
        + SKIP_SCENARIOS
        + SESSION_SCENARIOS
        + WS_SCENARIOS
        + KIRO_SCENARIOS
        + CURSOR_SCENARIOS
        + HOOK_EVENT_SCENARIOS
    )

    if tiers:
        return [s for s in all_scenarios if s.tier in tiers]
    return all_scenarios


# ---------------------------------------------------------------------------
# Hook analysis simulation (reused from test_hook_ab_comparison.py)
# ---------------------------------------------------------------------------


def simulate_hook_analyze(scenario: EvalScenario) -> EvalResult:
    """Simulate the stop hook's save/skip analysis deterministically.

    Applies SAVE_CRITERIA rules to the conversation to determine
    whether the hook would produce a save or skip action.
    """
    # Gather all message content
    messages = scenario.conversation
    full_text = "\n".join(m.content for m in messages)

    # Check system-reminder for explicit save instruction
    system_reminders = [m for m in messages if m.role == "system-reminder"]
    has_save_instruction = any(
        "mem-mesh에 저장하세요" in m.content or "mcp__mem-mesh__add" in m.content
        for m in system_reminders
    )

    # Check loop guard: already saved in this turn
    assistant_msgs = [m for m in messages if m.role == "assistant"]
    already_saved = any("mcp__mem-mesh__add" in m.content for m in assistant_msgs)

    if already_saved:
        return EvalResult(
            scenario_id=scenario.id,
            actual_action="skip",
            raw_response="Loop guard: already saved",
        )

    if has_save_instruction:
        # Extract category from system-reminder
        category = _extract_category(system_reminders[0].content)
        content = _extract_content(system_reminders[0].content)
        from tests.evals.models import ToolCall

        return EvalResult(
            scenario_id=scenario.id,
            actual_action="save",
            actual_category=category,
            saved_content=content,
            tool_calls=[
                ToolCall(
                    tool_name="mcp__mem-mesh__add",
                    args={"category": category, "project_id": "mem-mesh"},
                    position_index=0,
                ),
            ],
        )

    # Apply save/skip criteria
    save_signals = _detect_save_signals(full_text)
    skip_signals = _detect_skip_signals(full_text)

    if not save_signals or (skip_signals and not save_signals):
        return EvalResult(
            scenario_id=scenario.id,
            actual_action="skip",
            raw_response=f"Skip signals: {skip_signals}",
        )

    # Determine category
    category = "decision"
    if any("버그" in s for s in save_signals):
        category = "bug"
    elif any("패턴" in s for s in save_signals):
        category = "code_snippet"

    # Hybrid content
    ratio = STOP_PROMPT_CONFIG.hybrid_front_ratio
    split_point = int(len(full_text) * ratio)
    front = full_text[:split_point]
    back = full_text[split_point:]

    front_lines = front.strip().split("\n")
    max_lines = STOP_PROMPT_CONFIG.max_summary_lines
    summary_lines = front_lines[:max_lines] if len(front_lines) > max_lines else front_lines
    front_summary = "\n".join(f"  {line.strip()}" for line in summary_lines if line.strip())
    back_raw = back[: STOP_PROMPT_CONFIG.back_max_chars]
    hybrid_content = f"## 맥락\n{front_summary}\n\n## 상세\n{back_raw}"

    from tests.evals.models import ToolCall

    return EvalResult(
        scenario_id=scenario.id,
        actual_action="save",
        actual_category=category,
        saved_content=hybrid_content,
        tool_calls=[
            ToolCall(
                tool_name="mcp__mem-mesh__add",
                args={"category": category, "project_id": "mem-mesh"},
                position_index=0,
            ),
        ],
    )


def _extract_category(text: str) -> str:
    """Extract category from system-reminder text."""
    import re

    match = re.search(r'category=["\'](\w+)["\']', text)
    return match.group(1) if match else "decision"


def _extract_content(text: str) -> str:
    """Extract content body from system-reminder text."""
    # Content typically starts after the mcp call description
    parts = text.split("): ", 1)
    return parts[1].strip() if len(parts) > 1 else text


def _detect_save_signals(text: str) -> List[str]:
    """Detect save-worthy signals using SAVE_CRITERIA keywords."""
    signals: List[str] = []
    keyword_map: Dict[str, List[str]] = {
        "버그 진단/해결": ["버그", "bug", "fix", "ZeroDivision", "Error", "수정"],
        "아키텍처 또는 설계 결정": ["아키텍처", "설계", "결정", "채택", "하이브리드"],
        "재사용 가능한 코드 패턴": ["패턴", "pattern", "template", "재사용"],
        "중요 설정 변경 또는 마이그레이션": ["설정 변경", "마이그레이션", "migration"],
    }
    for criterion in SAVE_CRITERIA.save_when:
        for kw in keyword_map.get(criterion, []):
            if kw.lower() in text.lower():
                signals.append(criterion)
                break
    return signals


def _detect_skip_signals(text: str) -> List[str]:
    """Detect skip signals using SAVE_CRITERIA keywords."""
    signals: List[str] = []
    keyword_map: Dict[str, List[str]] = {
        '단순 질문/답변 ("뭐야?", "보여줘")': ["뭐야", "보여줘", "이 파일은", "이 파일 뭐"],
        "파일 읽기만 한 경우": ["현재 버전은", "위 내용이 현재"],
        "이미 저장된 내용의 반복": ["이미 저장", "Memory ID:"],
        "hook/설정 자체의 점검·수정·메타 대화 (hook 동작 확인, settings.json 수정 포함)": [
            "hook", "settings.json", "설정을 확인",
        ],
    }
    for criterion in SAVE_CRITERIA.skip_when:
        for kw in keyword_map.get(criterion, []):
            if kw in text:
                signals.append(criterion)
                break
    return signals


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def all_scenarios() -> List[EvalScenario]:
    """All registered scenarios across all categories."""
    return collect_scenarios()


@pytest.fixture
def deterministic_scenarios() -> List[EvalScenario]:
    """Tier 1 scenarios only."""
    return collect_scenarios(EvalTier.DETERMINISTIC)


@pytest.fixture
def simulated_scenarios() -> List[EvalScenario]:
    """Tier 2 scenarios only."""
    return collect_scenarios(EvalTier.SIMULATED)


@pytest.fixture
def llm_judged_scenarios() -> List[EvalScenario]:
    """Tier 3 scenarios only."""
    return collect_scenarios(EvalTier.LLM_JUDGED)
