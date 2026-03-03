"""Deterministic graders for DX eval.

Each grader takes an EvalScenario + EvalResult and returns a CheckResult.
These are used in Tier 1 (deterministic) and Tier 2 (simulated) tests.
"""

from __future__ import annotations

import re
from typing import List, Set

from .models import (
    CheckResult,
    EvalResult,
    EvalScenario,
    ExpectedAction,
    GradeResult,
    ToolCallPosition,
)

# ---------------------------------------------------------------------------
# Sensitive data patterns
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"(?:sk|pk|api)[_-](?:live|test|prod)[_-]\w{20,}", re.IGNORECASE),
    re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}"),
    re.compile(r"xox[bpas]-\w{10,}"),  # Slack tokens
    re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----"),
    re.compile(r"(?:password|passwd|secret)\s*[:=]\s*['\"][^'\"]{8,}['\"]", re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key
]


# ---------------------------------------------------------------------------
# Individual graders
# ---------------------------------------------------------------------------


def grade_tool_call_order(
    scenario: EvalScenario,
    result: EvalResult,
) -> CheckResult:
    """Check that expected tool calls exist and are in the right position.

    For SAVE scenarios: expected tools (e.g., mcp__mem-mesh__add) must be present.
    For SKIP scenarios: save tools must NOT be present.
    """
    if scenario.expected_action == ExpectedAction.SAVE:
        actual_tool_names = {tc.tool_name for tc in result.tool_calls}
        missing: List[str] = []
        position_errors: List[str] = []

        for expected in scenario.expected_tools:
            if expected.tool_name not in actual_tool_names:
                missing.append(expected.tool_name)
                continue

            # Check position if specified
            if expected.position != ToolCallPosition.ANY:
                matching_calls = [
                    tc for tc in result.tool_calls
                    if tc.tool_name == expected.tool_name
                ]
                if matching_calls and expected.position == ToolCallPosition.BEFORE_RESPONSE:
                    # In a save scenario, the tool should be called early
                    first_call = matching_calls[0]
                    if first_call.position_index > 0:
                        position_errors.append(
                            f"{expected.tool_name} at index {first_call.position_index}, "
                            f"expected before response"
                        )

        if missing:
            return CheckResult(
                check_name="tool_call_order",
                passed=False,
                message=f"Missing tool calls: {missing}",
                weight=2.0,
            )
        if position_errors:
            return CheckResult(
                check_name="tool_call_order",
                passed=False,
                message=f"Position errors: {position_errors}",
                weight=1.5,
            )
        return CheckResult(
            check_name="tool_call_order",
            passed=True,
            message="All expected tools called in correct order",
            weight=2.0,
        )
    else:
        # SKIP scenario: save tools must NOT be present
        save_tools = {"mcp__mem-mesh__add", "mcp__mem-mesh__pin_promote"}
        actual_tool_names = {tc.tool_name for tc in result.tool_calls}
        unwanted = actual_tool_names & save_tools
        if unwanted:
            return CheckResult(
                check_name="tool_call_order",
                passed=False,
                message=f"Unexpected save tools called: {unwanted}",
                weight=2.0,
            )
        return CheckResult(
            check_name="tool_call_order",
            passed=True,
            message="Correctly skipped save tools",
            weight=2.0,
        )


def grade_content_format(
    scenario: EvalScenario,
    result: EvalResult,
) -> CheckResult:
    """Check that saved content follows WHY/WHAT/IMPACT or 맥락/상세 structure."""
    if scenario.expected_action == ExpectedAction.SKIP:
        return CheckResult(
            check_name="content_format",
            passed=True,
            message="Skip scenario — no content to check",
            weight=1.0,
        )

    content = result.saved_content or ""
    if not content:
        return CheckResult(
            check_name="content_format",
            passed=False,
            message="No saved content found",
            weight=1.5,
        )

    # Check for structured format: either WHY/WHAT/IMPACT or 맥락/상세 or ## headers
    format_patterns = [
        (r"##\s+.*배경|##\s+.*WHY", "WHY/배경 section"),
        (r"##\s+.*내용|##\s+.*WHAT", "WHAT/내용 section"),
        (r"##\s+.*영향|##\s+.*IMPACT", "IMPACT/영향 section"),
        (r"##\s+맥락", "맥락 section"),
        (r"##\s+상세", "상세 section"),
    ]

    found_sections: List[str] = []
    for pattern, name in format_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            found_sections.append(name)

    has_headers = bool(re.search(r"^##\s+", content, re.MULTILINE))
    has_lists = bool(re.search(r"^[-*]\s+", content, re.MULTILINE))

    if len(found_sections) >= 2:
        return CheckResult(
            check_name="content_format",
            passed=True,
            message=f"Found structured sections: {found_sections}",
            weight=1.5,
        )
    elif has_headers and has_lists:
        return CheckResult(
            check_name="content_format",
            passed=True,
            message="Has markdown headers and lists (acceptable format)",
            weight=1.5,
        )
    else:
        return CheckResult(
            check_name="content_format",
            passed=False,
            message=f"Missing structured format. Found: headers={has_headers}, lists={has_lists}, sections={found_sections}",
            weight=1.5,
        )


def grade_category_correct(
    scenario: EvalScenario,
    result: EvalResult,
) -> CheckResult:
    """Check that the save category matches the expected one."""
    if scenario.expected_category is None:
        return CheckResult(
            check_name="category_correct",
            passed=True,
            message="No expected category specified",
            weight=1.0,
        )

    if result.actual_category == scenario.expected_category:
        return CheckResult(
            check_name="category_correct",
            passed=True,
            message=f"Category matches: {result.actual_category}",
            weight=1.5,
        )
    else:
        return CheckResult(
            check_name="category_correct",
            passed=False,
            message=f"Expected '{scenario.expected_category}', got '{result.actual_category}'",
            weight=1.5,
        )


def grade_no_sensitive_data(
    scenario: EvalScenario,
    result: EvalResult,
) -> CheckResult:
    """Scan saved content for API keys, tokens, passwords, and PII."""
    content = result.saved_content or result.raw_response or ""
    if not content:
        return CheckResult(
            check_name="no_sensitive_data",
            passed=True,
            message="No content to scan",
            weight=2.0,
        )

    found: List[str] = []
    for pattern in _SENSITIVE_PATTERNS:
        matches = pattern.findall(content)
        if matches:
            # Redact the actual value in the message
            found.append(f"{pattern.pattern[:30]}... ({len(matches)} match(es))")

    if found:
        return CheckResult(
            check_name="no_sensitive_data",
            passed=False,
            message=f"Sensitive data detected: {found}",
            weight=2.0,
        )
    return CheckResult(
        check_name="no_sensitive_data",
        passed=True,
        message="No sensitive data patterns found",
        weight=2.0,
    )


def grade_expected_patterns(
    scenario: EvalScenario,
    result: EvalResult,
) -> CheckResult:
    """Check that expected content patterns are present and forbidden patterns are absent."""
    content = result.saved_content or result.raw_response or ""

    missing_expected: List[str] = []
    for pattern_str in scenario.expected_content_patterns:
        if not re.search(pattern_str, content, re.IGNORECASE):
            missing_expected.append(pattern_str)

    found_forbidden: List[str] = []
    for pattern_str in scenario.forbidden_patterns:
        if re.search(pattern_str, content, re.IGNORECASE):
            found_forbidden.append(pattern_str)

    issues: List[str] = []
    if missing_expected:
        issues.append(f"missing expected: {missing_expected}")
    if found_forbidden:
        issues.append(f"found forbidden: {found_forbidden}")

    if issues:
        return CheckResult(
            check_name="expected_patterns",
            passed=False,
            message="; ".join(issues),
            weight=1.0,
        )
    return CheckResult(
        check_name="expected_patterns",
        passed=True,
        message="All pattern checks passed",
        weight=1.0,
    )


def grade_action_correct(
    scenario: EvalScenario,
    result: EvalResult,
) -> CheckResult:
    """Check that the action (save/skip) matches expectation."""
    expected = scenario.expected_action.value
    actual = result.actual_action

    if actual == expected:
        return CheckResult(
            check_name="action_correct",
            passed=True,
            message=f"Action matches: {actual}",
            weight=2.0,
        )
    return CheckResult(
        check_name="action_correct",
        passed=False,
        message=f"Expected '{expected}', got '{actual}'",
        weight=2.0,
    )


# ---------------------------------------------------------------------------
# IDE hook format grader
# ---------------------------------------------------------------------------


def grade_ide_hook_format(
    scenario: EvalScenario,
    result: EvalResult,
) -> CheckResult:
    """IDE-specific hook output format verification.

    Checks based on scenario.ide and scenario.hook_event:
    - kiro: JSON array format, mem-mesh: prefix, rules text
    - cursor: additional_context JSON, followup message, sessionEnd API
    - hook_event: SessionEnd/PreCompact template content
    """
    ide = scenario.ide
    hook_event = scenario.hook_event

    if not ide and not hook_event:
        return CheckResult(
            check_name="ide_hook_format",
            passed=True,
            message="No IDE/hook_event specified — skipped",
            weight=0.0,
        )

    from app.cli.hooks.renderer import _load_template

    if hook_event == "SessionEnd":
        template = _load_template("session-end.sh")
        issues: List[str] = []
        if "end-by-project" not in template:
            issues.append("missing end-by-project API call")
        if "exit 0" not in template:
            issues.append("missing exit 0 (non-blocking)")
        if issues:
            return CheckResult(
                check_name="ide_hook_format",
                passed=False,
                message=f"SessionEnd template issues: {issues}",
                weight=1.5,
            )
        return CheckResult(
            check_name="ide_hook_format",
            passed=True,
            message="SessionEnd template has correct format",
            weight=1.5,
        )

    if hook_event == "PreCompact":
        template = _load_template("precompact.sh")
        issues = []
        if "end-by-project" not in template:
            issues.append("missing end-by-project API call")
        if "Auto-ended" not in template:
            issues.append("missing Auto-ended summary")
        if "|| true" not in template:
            issues.append("missing || true (non-blocking)")
        if issues:
            return CheckResult(
                check_name="ide_hook_format",
                passed=False,
                message=f"PreCompact template issues: {issues}",
                weight=1.5,
            )
        return CheckResult(
            check_name="ide_hook_format",
            passed=True,
            message="PreCompact template has correct format",
            weight=1.5,
        )

    if ide == "kiro":
        template = _load_template("kiro-stop.sh")
        issues = []
        if "jq" not in template:
            issues.append("missing jq for JSON handling")
        if "KIRO_RESULT" not in template:
            issues.append("missing KIRO_RESULT env var")
        if issues:
            return CheckResult(
                check_name="ide_hook_format",
                passed=False,
                message=f"Kiro template issues: {issues}",
                weight=1.5,
            )
        return CheckResult(
            check_name="ide_hook_format",
            passed=True,
            message="Kiro template has correct format",
            weight=1.5,
        )

    if ide == "cursor":
        if hook_event == "SessionStart":
            template = _load_template("cursor-session-start.sh")
            if "additional_context" not in template:
                return CheckResult(
                    check_name="ide_hook_format",
                    passed=False,
                    message="Cursor session-start missing additional_context",
                    weight=1.5,
                )
        elif hook_event == "Stop":
            template = _load_template("cursor-stop.sh")
            if "followup_message" not in template:
                return CheckResult(
                    check_name="ide_hook_format",
                    passed=False,
                    message="Cursor stop missing followup_message",
                    weight=1.5,
                )
        return CheckResult(
            check_name="ide_hook_format",
            passed=True,
            message=f"Cursor {hook_event} template has correct format",
            weight=1.5,
        )

    return CheckResult(
        check_name="ide_hook_format",
        passed=True,
        message=f"IDE format check passed for {ide}/{hook_event}",
        weight=1.0,
    )


# ---------------------------------------------------------------------------
# Composite grader
# ---------------------------------------------------------------------------


def grade_scenario(
    scenario: EvalScenario,
    result: EvalResult,
) -> GradeResult:
    """Run all applicable graders on a scenario/result pair."""
    checks: List[CheckResult] = [
        grade_action_correct(scenario, result),
        grade_tool_call_order(scenario, result),
        grade_content_format(scenario, result),
        grade_category_correct(scenario, result),
        grade_no_sensitive_data(scenario, result),
        grade_expected_patterns(scenario, result),
        grade_ide_hook_format(scenario, result),
    ]
    return GradeResult.from_checks(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        checks=checks,
    )
