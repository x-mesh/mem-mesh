"""Tier 1 — Deterministic tests.

Tests grader logic, prompt structure, and scenario definitions.
No LLM calls — runs in CI on every push.

Run:
    python -m pytest tests/evals/test_eval_deterministic.py -v
"""

from __future__ import annotations

import re

import pytest

from app.cli.prompts.behaviors import SAVE_CRITERIA, STOP_PROMPT_CONFIG
from app.cli.prompts.renderers import render_claude_stop_prompt
from tests.evals.conftest import collect_scenarios, simulate_hook_analyze
from tests.evals.graders import (
    grade_action_correct,
    grade_category_correct,
    grade_content_format,
    grade_expected_patterns,
    grade_no_sensitive_data,
    grade_scenario,
    grade_tool_call_order,
)
from tests.evals.models import (
    CheckResult,
    EvalResult,
    EvalScenario,
    EvalTier,
    ExpectedAction,
    GradeResult,
    ToolCall,
)


# ---------------------------------------------------------------------------
# Grader unit tests
# ---------------------------------------------------------------------------


class TestGradeActionCorrect:
    """Test grade_action_correct grader."""

    def test_save_matches_save(self) -> None:
        scenario = _make_scenario(expected_action=ExpectedAction.SAVE)
        result = EvalResult(scenario_id="test", actual_action="save")
        check = grade_action_correct(scenario, result)
        assert check.passed

    def test_skip_matches_skip(self) -> None:
        scenario = _make_scenario(expected_action=ExpectedAction.SKIP)
        result = EvalResult(scenario_id="test", actual_action="skip")
        check = grade_action_correct(scenario, result)
        assert check.passed

    def test_mismatch_fails(self) -> None:
        scenario = _make_scenario(expected_action=ExpectedAction.SAVE)
        result = EvalResult(scenario_id="test", actual_action="skip")
        check = grade_action_correct(scenario, result)
        assert not check.passed


class TestGradeToolCallOrder:
    """Test grade_tool_call_order grader."""

    def test_save_with_expected_tool(self) -> None:
        from tests.evals.models import ExpectedToolCall, ToolCallPosition

        scenario = _make_scenario(
            expected_action=ExpectedAction.SAVE,
            expected_tools=[
                ExpectedToolCall(
                    tool_name="mcp__mem-mesh__add",
                    position=ToolCallPosition.BEFORE_RESPONSE,
                ),
            ],
        )
        result = EvalResult(
            scenario_id="test",
            actual_action="save",
            tool_calls=[
                ToolCall(tool_name="mcp__mem-mesh__add", position_index=0),
            ],
        )
        check = grade_tool_call_order(scenario, result)
        assert check.passed

    def test_save_missing_tool_fails(self) -> None:
        from tests.evals.models import ExpectedToolCall

        scenario = _make_scenario(
            expected_action=ExpectedAction.SAVE,
            expected_tools=[
                ExpectedToolCall(tool_name="mcp__mem-mesh__add"),
            ],
        )
        result = EvalResult(
            scenario_id="test",
            actual_action="save",
            tool_calls=[],
        )
        check = grade_tool_call_order(scenario, result)
        assert not check.passed

    def test_skip_with_save_tool_fails(self) -> None:
        scenario = _make_scenario(expected_action=ExpectedAction.SKIP)
        result = EvalResult(
            scenario_id="test",
            actual_action="skip",
            tool_calls=[
                ToolCall(tool_name="mcp__mem-mesh__add", position_index=0),
            ],
        )
        check = grade_tool_call_order(scenario, result)
        assert not check.passed

    def test_skip_no_save_tools_passes(self) -> None:
        scenario = _make_scenario(expected_action=ExpectedAction.SKIP)
        result = EvalResult(
            scenario_id="test",
            actual_action="skip",
            tool_calls=[],
        )
        check = grade_tool_call_order(scenario, result)
        assert check.passed


class TestGradeContentFormat:
    """Test grade_content_format grader."""

    def test_why_what_impact_passes(self) -> None:
        scenario = _make_scenario(expected_action=ExpectedAction.SAVE)
        result = EvalResult(
            scenario_id="test",
            actual_action="save",
            saved_content=(
                "## 배경 (WHY)\n하이브리드 방식 비교\n\n"
                "## 내용 (WHAT)\n- 앞부분 요약 + 뒷부분 원본\n\n"
                "## 영향 (IMPACT)\nstop hook에 적용"
            ),
        )
        check = grade_content_format(scenario, result)
        assert check.passed

    def test_context_detail_passes(self) -> None:
        scenario = _make_scenario(expected_action=ExpectedAction.SAVE)
        result = EvalResult(
            scenario_id="test",
            actual_action="save",
            saved_content=(
                "## 맥락\n버그 수정 배경\n\n"
                "## 상세\n- guard 조건 추가\n- 테스트 통과"
            ),
        )
        check = grade_content_format(scenario, result)
        assert check.passed

    def test_no_structure_fails(self) -> None:
        scenario = _make_scenario(expected_action=ExpectedAction.SAVE)
        result = EvalResult(
            scenario_id="test",
            actual_action="save",
            saved_content="Just plain text without any structure",
        )
        check = grade_content_format(scenario, result)
        assert not check.passed

    def test_skip_scenario_always_passes(self) -> None:
        scenario = _make_scenario(expected_action=ExpectedAction.SKIP)
        result = EvalResult(scenario_id="test", actual_action="skip")
        check = grade_content_format(scenario, result)
        assert check.passed


class TestGradeCategoryCorrect:
    """Test grade_category_correct grader."""

    def test_matching_category(self) -> None:
        scenario = _make_scenario(expected_category="bug")
        result = EvalResult(
            scenario_id="test", actual_action="save", actual_category="bug"
        )
        check = grade_category_correct(scenario, result)
        assert check.passed

    def test_wrong_category(self) -> None:
        scenario = _make_scenario(expected_category="bug")
        result = EvalResult(
            scenario_id="test", actual_action="save", actual_category="decision"
        )
        check = grade_category_correct(scenario, result)
        assert not check.passed

    def test_no_expected_category_passes(self) -> None:
        scenario = _make_scenario(expected_category=None)
        result = EvalResult(
            scenario_id="test", actual_action="save", actual_category="decision"
        )
        check = grade_category_correct(scenario, result)
        assert check.passed


class TestGradeNoSensitiveData:
    """Test grade_no_sensitive_data grader."""

    def test_clean_content_passes(self) -> None:
        scenario = _make_scenario()
        result = EvalResult(
            scenario_id="test",
            actual_action="save",
            saved_content="## 버그 수정\n- guard 조건 추가",
        )
        check = grade_no_sensitive_data(scenario, result)
        assert check.passed

    def test_api_key_detected(self) -> None:
        scenario = _make_scenario()
        result = EvalResult(
            scenario_id="test",
            actual_action="save",
            saved_content="API key: sk-live-abcdefghij1234567890abcdefghij",
        )
        check = grade_no_sensitive_data(scenario, result)
        assert not check.passed

    def test_aws_key_detected(self) -> None:
        scenario = _make_scenario()
        result = EvalResult(
            scenario_id="test",
            actual_action="save",
            saved_content="AWS key: AKIAIOSFODNN7EXAMPLE",
        )
        check = grade_no_sensitive_data(scenario, result)
        assert not check.passed

    def test_private_key_detected(self) -> None:
        scenario = _make_scenario()
        result = EvalResult(
            scenario_id="test",
            actual_action="save",
            saved_content="Key:\n-----BEGIN RSA PRIVATE KEY-----\nMIIE...",
        )
        check = grade_no_sensitive_data(scenario, result)
        assert not check.passed


class TestGradeExpectedPatterns:
    """Test grade_expected_patterns grader."""

    def test_expected_pattern_found(self) -> None:
        scenario = _make_scenario(
            expected_content_patterns=[r"ZeroDivision"],
        )
        result = EvalResult(
            scenario_id="test",
            actual_action="save",
            saved_content="Fixed ZeroDivisionError",
        )
        check = grade_expected_patterns(scenario, result)
        assert check.passed

    def test_forbidden_pattern_detected(self) -> None:
        scenario = _make_scenario(
            forbidden_patterns=[r"sk-proj-\w+"],
        )
        result = EvalResult(
            scenario_id="test",
            actual_action="save",
            saved_content="Key: sk-proj-abc123def456",
        )
        check = grade_expected_patterns(scenario, result)
        assert not check.passed


class TestGradeScenarioComposite:
    """Test the composite grade_scenario function."""

    def test_fully_passing_scenario(self) -> None:
        from tests.evals.models import ExpectedToolCall

        scenario = _make_scenario(
            expected_action=ExpectedAction.SAVE,
            expected_category="bug",
            expected_tools=[ExpectedToolCall(tool_name="mcp__mem-mesh__add")],
        )
        result = EvalResult(
            scenario_id="test",
            actual_action="save",
            actual_category="bug",
            tool_calls=[ToolCall(tool_name="mcp__mem-mesh__add", position_index=0)],
            saved_content="## 맥락\n버그 수정\n\n## 상세\n- guard 추가",
        )
        grade = grade_scenario(scenario, result)
        assert grade.passed
        assert grade.score == 1.0

    def test_mixed_results(self) -> None:
        scenario = _make_scenario(
            expected_action=ExpectedAction.SAVE,
            expected_category="bug",
        )
        result = EvalResult(
            scenario_id="test",
            actual_action="save",
            actual_category="decision",  # wrong category
            saved_content="## 맥락\n내용\n\n## 상세\n- 항목",
        )
        grade = grade_scenario(scenario, result)
        assert not grade.passed  # category mismatch
        assert 0.0 < grade.score < 1.0


# ---------------------------------------------------------------------------
# Prompt structure tests
# ---------------------------------------------------------------------------


class TestPromptStructure:
    """Test that the stop hook prompt has required sections."""

    def test_prompt_has_save_criteria(self) -> None:
        prompt = render_claude_stop_prompt()
        for criterion in SAVE_CRITERIA.save_when:
            assert criterion in prompt, f"Missing save criterion: {criterion}"

    def test_prompt_has_skip_criteria(self) -> None:
        prompt = render_claude_stop_prompt()
        for criterion in SAVE_CRITERIA.skip_when:
            assert criterion in prompt, f"Missing skip criterion: {criterion}"

    def test_prompt_has_mcp_call(self) -> None:
        prompt = render_claude_stop_prompt()
        assert "mcp__mem-mesh__add" in prompt

    def test_prompt_has_reason_rules(self) -> None:
        prompt = render_claude_stop_prompt()
        assert "reason" in prompt
        assert "1~3줄 요약" in prompt or "요약" in prompt


# ---------------------------------------------------------------------------
# Scenario integrity tests
# ---------------------------------------------------------------------------


class TestScenarioIntegrity:
    """Validate scenario definitions are well-formed."""

    def test_all_scenarios_have_unique_ids(self) -> None:
        scenarios = collect_scenarios()
        ids = [s.id for s in scenarios]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {ids}"

    def test_all_scenarios_have_conversation(self) -> None:
        for s in collect_scenarios():
            assert len(s.conversation) > 0, f"{s.id} has no conversation messages"

    def test_save_scenarios_have_expected_tools(self) -> None:
        for s in collect_scenarios():
            if s.expected_action == ExpectedAction.SAVE and s.tier != EvalTier.DETERMINISTIC:
                # WS scenarios are special (tested differently)
                if "websocket" not in s.tags:
                    assert len(s.expected_tools) > 0, (
                        f"{s.id}: SAVE scenario should have expected_tools"
                    )

    def test_scenario_ids_follow_convention(self) -> None:
        pattern = re.compile(r"^[a-z_]+_\d{2}$")
        for s in collect_scenarios():
            assert pattern.match(s.id), f"ID '{s.id}' doesn't match pattern 'name_XX'"


# ---------------------------------------------------------------------------
# GradeResult model tests
# ---------------------------------------------------------------------------


class TestGradeResultModel:
    """Test GradeResult.from_checks aggregation."""

    def test_all_pass(self) -> None:
        checks = [
            CheckResult(check_name="a", passed=True, message="ok", weight=1.0),
            CheckResult(check_name="b", passed=True, message="ok", weight=2.0),
        ]
        grade = GradeResult.from_checks("s1", "test", checks)
        assert grade.passed
        assert grade.score == 1.0

    def test_partial_pass(self) -> None:
        checks = [
            CheckResult(check_name="a", passed=True, message="ok", weight=1.0),
            CheckResult(check_name="b", passed=False, message="fail", weight=1.0),
        ]
        grade = GradeResult.from_checks("s1", "test", checks)
        assert not grade.passed
        assert grade.score == 0.5

    def test_all_fail(self) -> None:
        checks = [
            CheckResult(check_name="a", passed=False, message="fail", weight=1.0),
        ]
        grade = GradeResult.from_checks("s1", "test", checks)
        assert not grade.passed
        assert grade.score == 0.0

    def test_weighted_scoring(self) -> None:
        checks = [
            CheckResult(check_name="a", passed=True, message="ok", weight=3.0),
            CheckResult(check_name="b", passed=False, message="fail", weight=1.0),
        ]
        grade = GradeResult.from_checks("s1", "test", checks)
        assert not grade.passed
        assert grade.score == 0.75  # 3/(3+1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scenario(
    expected_action: ExpectedAction = ExpectedAction.SKIP,
    expected_category: str | None = None,
    expected_tools: list | None = None,
    expected_content_patterns: list | None = None,
    forbidden_patterns: list | None = None,
) -> EvalScenario:
    """Create a minimal test scenario."""
    from tests.evals.models import ConversationMessage

    return EvalScenario(
        id="test",
        name="Test scenario",
        description="Test",
        tier=EvalTier.DETERMINISTIC,
        conversation=[ConversationMessage(role="user", content="test")],
        expected_action=expected_action,
        expected_category=expected_category,
        expected_tools=expected_tools or [],
        expected_content_patterns=expected_content_patterns or [],
        forbidden_patterns=forbidden_patterns or [],
    )
