"""Fixed-evidence Reconciler judge evaluation tests."""

from pathlib import Path

import pytest

from scripts.evaluate_reconciler_judge import JudgeCase, JudgeSuite, evaluate_cases


def test_fixed_judge_suite_covers_distinct_decisions():
    path = Path(__file__).parent / "fixtures" / "reconciler_judge_cases.json"
    suite = JudgeSuite.model_validate_json(path.read_text())

    assert len(suite.cases) == 6
    assert {action for case in suite.cases for action in case.expected_actions} >= {
        "merge",
        "needs_review",
        "no_op",
        "supersede",
        "noise_suppression",
    }


@pytest.mark.asyncio
async def test_judge_report_checks_action_terms_sources_and_snapshot_hashes():
    case = JudgeCase(
        id="complementary",
        evidence=[
            {"memory_id": "m1", "input_hash": "h1", "content": "Stable rule"},
            {"memory_id": "m2", "input_hash": "h2", "content": "Nightly rule"},
        ],
        expected_actions=["merge"],
        required_terms=["stable", "nightly"],
        required_source_ids=["m1", "m2"],
    )

    class Judge:
        async def reconcile_group(self, evidence):
            return {
                "action": "merge",
                "representative_memory_id": "m1",
                "body": "Stable and nightly rules are distinct.",
                "claims": [
                    {
                        "text": "Stable and nightly rules are distinct.",
                        "source_refs": [
                            {
                                "memory_id": item["memory_id"],
                                "input_hash": item["input_hash"],
                            }
                            for item in evidence
                        ],
                    }
                ],
            }

    report = await evaluate_cases(Judge(), [case])

    assert report["passed"] == 1
    assert report["cases"][0]["failures"] == []

    class InvalidJudge(Judge):
        async def reconcile_group(self, evidence):
            payload = await super().reconcile_group(evidence)
            payload["claims"][0]["source_refs"][0]["input_hash"] = "wrong"
            return payload

    rejected = await evaluate_cases(InvalidJudge(), [case])
    assert rejected["passed"] == 0
    assert rejected["cases"][0]["failures"] == [
        "judge or schema error: ReconcilerValidationError"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason, passed", [("contradiction", 1), ("scope_mismatch", 0), (None, 0)]
)
async def test_judge_report_requires_expected_review_classification(reason, passed):
    case = JudgeCase(
        id="conflict",
        evidence=[
            {
                "memory_id": "m1",
                "input_hash": "h1",
                "content": "Unresolved source claims.",
            }
        ],
        expected_actions=["needs_review"],
        expected_review_reason="contradiction",
    )

    class Judge:
        async def reconcile_group(self, evidence):
            return {"action": "needs_review", "review_reason": reason}

    report = await evaluate_cases(Judge(), [case])
    assert report["passed"] == passed
    assert report["cases"][0]["review_reason"] == reason


def test_judge_case_rejects_oversized_evidence():
    from pydantic import ValidationError

    from app.core.services.memory_reconciler import MAX_EVIDENCE_CHARS

    with pytest.raises(ValidationError):
        JudgeCase(
            id="large",
            evidence=[
                {
                    "memory_id": "m1",
                    "input_hash": "h1",
                    "content": "x" * (MAX_EVIDENCE_CHARS + 1),
                }
            ],
            expected_actions=["no_op"],
        )


@pytest.mark.asyncio
async def test_judge_report_rejects_uncited_required_conclusion():
    case = JudgeCase(
        id="uncited",
        evidence=[
            {
                "memory_id": "m1",
                "input_hash": "h1",
                "content": "Stable releases require review.",
            }
        ],
        expected_actions=["merge"],
        required_terms=["stable"],
        required_source_ids=["m1"],
    )

    class Judge:
        async def reconcile_group(self, evidence):
            return {
                "action": "merge",
                "representative_memory_id": "m1",
                "body": "Stable releases require review.",
                "claims": [
                    {
                        "text": "Other fact",
                        "source_refs": [{"memory_id": "m1", "input_hash": "h1"}],
                    }
                ],
            }

    report = await evaluate_cases(Judge(), [case])
    assert report["passed"] == 0
    assert "uncited term: stable" in report["cases"][0]["failures"]


def test_judge_case_rejects_combined_evidence_budget_overflow():
    from pydantic import ValidationError

    from app.core.services.memory_reconciler import MAX_EVIDENCE_CHARS
    from scripts.evaluate_reconciler_judge import Evidence

    evidence = [
        Evidence(
            memory_id=str(index),
            input_hash="hash",
            content="x" * (MAX_EVIDENCE_CHARS // 2),
        )
        for index in range(2)
    ]
    assert all(len(item.content) <= MAX_EVIDENCE_CHARS for item in evidence)
    with pytest.raises(ValidationError, match="case evidence exceeds"):
        JudgeCase(id="combined", evidence=evidence, expected_actions=["no_op"])
