"""Tier 2 — Simulated tests.

Runs scenarios through the deterministic hook analysis pipeline
and grades results. No LLM calls — runs in CI on every push.

Run:
    python -m pytest tests/evals/test_eval_simulated.py -v
"""

from __future__ import annotations

from typing import List

import pytest

from tests.evals.conftest import (
    collect_scenarios,
    save_grade_results,
    simulate_hook_analyze,
)
from tests.evals.graders import grade_scenario
from tests.evals.models import EvalScenario, EvalTier, GradeResult


# ---------------------------------------------------------------------------
# Scenario 1: Stop hook → save execution
# ---------------------------------------------------------------------------


class TestHookSaveExecution:
    """Verify stop hook save/skip behavior via simulation."""

    def test_hook_save_basic(self) -> None:
        """system-reminder에 저장 지시 → save 실행."""
        from tests.evals.scenarios.hook_save_execution import HOOK_SAVE_BASIC

        result = simulate_hook_analyze(HOOK_SAVE_BASIC)
        grade = grade_scenario(HOOK_SAVE_BASIC, result)
        assert grade.passed, f"Failed: {grade.details}"

    def test_hook_save_already_saved(self) -> None:
        """이미 저장된 경우 → skip (loop guard)."""
        from tests.evals.scenarios.hook_save_execution import HOOK_SAVE_ALREADY_SAVED

        result = simulate_hook_analyze(HOOK_SAVE_ALREADY_SAVED)
        grade = grade_scenario(HOOK_SAVE_ALREADY_SAVED, result)
        assert grade.passed, f"Failed: {grade.details}"

    def test_hook_save_no_instruction(self) -> None:
        """저장 지시 없음 → skip."""
        from tests.evals.scenarios.hook_save_execution import HOOK_SAVE_NO_INSTRUCTION

        result = simulate_hook_analyze(HOOK_SAVE_NO_INSTRUCTION)
        grade = grade_scenario(HOOK_SAVE_NO_INSTRUCTION, result)
        assert grade.passed, f"Failed: {grade.details}"


# ---------------------------------------------------------------------------
# Scenario 2: Save content quality
# ---------------------------------------------------------------------------


class TestSaveContentQuality:
    """Verify saved content structure and categorization."""

    def test_bug_content_quality(self) -> None:
        """버그 수정 → bug 카테고리 + 구조화된 콘텐츠."""
        from tests.evals.scenarios.save_content_quality import CONTENT_QUALITY_BUG

        result = simulate_hook_analyze(CONTENT_QUALITY_BUG)
        grade = grade_scenario(CONTENT_QUALITY_BUG, result)
        assert grade.passed, f"Failed: {grade.details}"

    def test_decision_content_quality(self) -> None:
        """아키텍처 결정 → decision 카테고리 + WHY/WHAT/IMPACT."""
        from tests.evals.scenarios.save_content_quality import CONTENT_QUALITY_DECISION

        result = simulate_hook_analyze(CONTENT_QUALITY_DECISION)
        grade = grade_scenario(CONTENT_QUALITY_DECISION, result)
        assert grade.passed, f"Failed: {grade.details}"


# ---------------------------------------------------------------------------
# Scenario 3: Skip criteria accuracy
# ---------------------------------------------------------------------------


class TestSkipCriteria:
    """Verify that trivial conversations are correctly skipped."""

    def test_skip_simple_qa(self) -> None:
        """단순 Q&A → skip."""
        from tests.evals.scenarios.skip_criteria import SKIP_SIMPLE_QA

        result = simulate_hook_analyze(SKIP_SIMPLE_QA)
        grade = grade_scenario(SKIP_SIMPLE_QA, result)
        assert grade.passed, f"Failed: {grade.details}"

    def test_skip_file_read(self) -> None:
        """파일 읽기만 → skip."""
        from tests.evals.scenarios.skip_criteria import SKIP_FILE_READ

        result = simulate_hook_analyze(SKIP_FILE_READ)
        grade = grade_scenario(SKIP_FILE_READ, result)
        assert grade.passed, f"Failed: {grade.details}"

    def test_skip_meta_talk(self) -> None:
        """Hook/설정 메타 대화 → skip."""
        from tests.evals.scenarios.skip_criteria import SKIP_META_TALK

        result = simulate_hook_analyze(SKIP_META_TALK)
        grade = grade_scenario(SKIP_META_TALK, result)
        assert grade.passed, f"Failed: {grade.details}"

    def test_skip_already_saved(self) -> None:
        """이미 저장된 내용 → skip."""
        from tests.evals.scenarios.skip_criteria import SKIP_ALREADY_SAVED

        result = simulate_hook_analyze(SKIP_ALREADY_SAVED)
        grade = grade_scenario(SKIP_ALREADY_SAVED, result)
        assert grade.passed, f"Failed: {grade.details}"


# ---------------------------------------------------------------------------
# Aggregate: run all simulated scenarios and save results
# ---------------------------------------------------------------------------


class TestSimulatedAggregate:
    """Run all Tier 2 scenarios and produce an aggregate report."""

    def test_all_simulated_scenarios(self) -> None:
        """All simulated scenarios should pass with score >= 0.8."""
        scenarios = collect_scenarios(EvalTier.SIMULATED)
        results: List[GradeResult] = []

        for scenario in scenarios:
            eval_result = simulate_hook_analyze(scenario)
            grade = grade_scenario(scenario, eval_result)
            results.append(grade)

        # Save results for analysis
        save_grade_results(results, "simulated_results.json")

        # Report
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        avg_score = sum(r.score for r in results) / total if total else 0

        # Print summary
        for r in results:
            status = "PASS" if r.passed else "FAIL"
            print(f"  [{status}] {r.scenario_id}: {r.scenario_name} (score={r.score})")

        print(f"\n  Total: {passed}/{total} passed, avg score={avg_score:.2f}")

        assert passed == total, (
            f"{total - passed} scenarios failed. "
            f"See tests/evals/results/simulated_results.json for details."
        )
