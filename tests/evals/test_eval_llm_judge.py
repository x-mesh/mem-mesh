"""Tier 3 — LLM-Judged tests.

Uses `claude` CLI subprocess to evaluate AI behavior compliance.
Requires RUN_EVALS=1 environment variable to run (skipped by default).

Run:
    RUN_EVALS=1 python -m pytest tests/evals/test_eval_llm_judge.py -v --timeout=300
"""

from __future__ import annotations

import os
from typing import List

import pytest

from tests.evals.conftest import (
    collect_scenarios,
    save_grade_results,
    simulate_hook_analyze,
)
from tests.evals.judge import judge_scenario
from tests.evals.models import EvalTier, GradeResult

# Skip all tests unless RUN_EVALS=1 is set
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_EVALS") != "1",
    reason="LLM eval tests require RUN_EVALS=1 (incurs API cost)",
)


# ---------------------------------------------------------------------------
# Individual LLM-judged scenarios
# ---------------------------------------------------------------------------


class TestLLMJudgedScenarios:
    """Run LLM judge on Tier 3 scenarios."""

    @pytest.mark.eval
    def test_sensitive_data_handling(self) -> None:
        """M4: 민감 데이터가 저장되지 않는지 LLM이 검증."""
        from tests.evals.scenarios.save_content_quality import (
            CONTENT_QUALITY_SENSITIVE,
        )

        result = simulate_hook_analyze(CONTENT_QUALITY_SENSITIVE)
        grade = judge_scenario(CONTENT_QUALITY_SENSITIVE, result)
        assert grade.passed, f"LLM judge failed: {grade.details}"

    @pytest.mark.eval
    def test_session_resume_on_first_message(self) -> None:
        """M1: 첫 메시지에서 session_resume 호출."""
        from tests.evals.scenarios.session_lifecycle import SESSION_RESUME_FIRST_MSG

        result = simulate_hook_analyze(SESSION_RESUME_FIRST_MSG)
        grade = judge_scenario(SESSION_RESUME_FIRST_MSG, result)
        assert grade.passed, f"LLM judge failed: {grade.details}"

    @pytest.mark.eval
    def test_session_end_on_explicit_close(self) -> None:
        """M2: '오늘 끝' → session_end 호출."""
        from tests.evals.scenarios.session_lifecycle import SESSION_END_EXPLICIT

        result = simulate_hook_analyze(SESSION_END_EXPLICIT)
        grade = judge_scenario(SESSION_END_EXPLICIT, result)
        assert grade.passed, f"LLM judge failed: {grade.details}"

    @pytest.mark.eval
    def test_session_end_on_pr_request(self) -> None:
        """M2: 'PR 올려줘' → session_end 호출."""
        from tests.evals.scenarios.session_lifecycle import SESSION_END_PR

        result = simulate_hook_analyze(SESSION_END_PR)
        grade = judge_scenario(SESSION_END_PR, result)
        assert grade.passed, f"LLM judge failed: {grade.details}"


# ---------------------------------------------------------------------------
# Aggregate: run all LLM-judged scenarios
# ---------------------------------------------------------------------------


class TestLLMJudgedAggregate:
    """Run all Tier 3 scenarios through LLM judge."""

    @pytest.mark.eval
    def test_all_llm_judged_scenarios(self) -> None:
        """All LLM-judged scenarios should pass."""
        scenarios = collect_scenarios(EvalTier.LLM_JUDGED)
        results: List[GradeResult] = []

        for scenario in scenarios:
            eval_result = simulate_hook_analyze(scenario)
            grade = judge_scenario(scenario, eval_result, model="haiku")
            results.append(grade)

        # Save results
        save_grade_results(results, "llm_judge_results.json")

        # Report
        passed = sum(1 for r in results if r.passed)
        total = len(results)

        for r in results:
            status = "PASS" if r.passed else "FAIL"
            print(f"  [{status}] {r.scenario_id}: {r.scenario_name}")
            for check in r.checks:
                print(f"    {check.message[:200]}")

        print(f"\n  Total: {passed}/{total} passed")

        # Tier 3 is advisory — warn but don't hard-fail
        if passed < total:
            pytest.xfail(
                f"{total - passed} scenarios failed LLM judge. "
                f"See tests/evals/results/llm_judge_results.json"
            )
