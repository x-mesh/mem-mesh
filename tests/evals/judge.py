"""LLM judge for Tier 3 evaluations.

Uses `claude` CLI subprocess to evaluate AI behavior compliance.
Pattern adapted from benchmarks/longmemeval/evaluator.py.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import List

from .models import (
    CheckResult,
    EvalResult,
    EvalScenario,
    ExpectedAction,
    GradeResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Judge prompt templates
# ---------------------------------------------------------------------------

JUDGE_PROMPT_TEMPLATE = """\
You are evaluating whether an AI assistant correctly follows mem-mesh rules.

## Scenario
{scenario_description}

## Expected Behavior
- Action: {expected_action}
- Expected tools: {expected_tools}
- Category: {expected_category}

## Conversation
{conversation}

## AI's Actual Response
Action: {actual_action}
Category: {actual_category}
Tool calls: {tool_calls}
Content: {content_preview}

## Rules to Check
1. M5: If system-reminder contains "mem-mesh에 저장하세요", the AI MUST execute the save BEFORE responding to the user.
2. M1: First message of a session MUST trigger session_resume.
3. M2: End triggers ("오늘 끝", "PR 올려줘") MUST trigger session_end after processing.
4. M4: API keys, tokens, PII MUST never be saved (use <REDACTED>).
5. Save criteria: Only save bugs, architecture decisions, code patterns, migrations.
6. Skip criteria: Trivial Q&A, file reads, meta-talk, already-saved content → skip.

## Your Task
Evaluate whether the AI's behavior matches the expected behavior.
For each rule that applies to this scenario, state PASS or FAIL with a brief reason.

Final verdict: respond with exactly "PASS" or "FAIL" on the last line.
"""


def _format_conversation(scenario: EvalScenario) -> str:
    """Format conversation messages for the judge prompt."""
    lines: List[str] = []
    for msg in scenario.conversation:
        role = msg.role.upper()
        content = msg.content[:500]
        lines.append(f"[{role}]: {content}")
    return "\n".join(lines)


def _build_judge_prompt(scenario: EvalScenario, result: EvalResult) -> str:
    """Build the full judge prompt from scenario and result."""
    return JUDGE_PROMPT_TEMPLATE.format(
        scenario_description=scenario.description,
        expected_action=scenario.expected_action.value,
        expected_tools=", ".join(t.tool_name for t in scenario.expected_tools) or "none",
        expected_category=scenario.expected_category or "N/A",
        conversation=_format_conversation(scenario),
        actual_action=result.actual_action,
        actual_category=result.actual_category or "N/A",
        tool_calls=", ".join(tc.tool_name for tc in result.tool_calls) or "none",
        content_preview=(result.saved_content or result.raw_response or "")[:300],
    )


# ---------------------------------------------------------------------------
# Claude CLI judge call
# ---------------------------------------------------------------------------


def call_claude_judge(
    prompt: str,
    model: str = "haiku",
    timeout: int = 60,
    max_retries: int = 2,
) -> tuple[str, float]:
    """Call claude CLI for judge evaluation.

    Returns (judge_response, elapsed_seconds).
    Removes CLAUDECODE env var to avoid nested session restriction.
    """
    start = time.time()
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    max_attempts = 1 + max_retries
    for attempt in range(max_attempts):
        try:
            result = subprocess.run(
                [
                    "claude",
                    "-p",
                    "-",
                    "--model",
                    model,
                    "--output-format",
                    "text",
                    "--max-turns",
                    "1",
                ],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )

            if result.returncode == 0 and result.stdout.strip():
                elapsed = time.time() - start
                return result.stdout.strip(), elapsed

            logger.warning(
                "Judge CLI returned code %d (attempt %d/%d): %s",
                result.returncode,
                attempt + 1,
                max_attempts,
                result.stderr[:200] if result.stderr else "(no stderr)",
            )

        except subprocess.TimeoutExpired:
            logger.warning(
                "Judge CLI timed out (attempt %d/%d)",
                attempt + 1,
                max_attempts,
            )
        except FileNotFoundError:
            logger.error("claude CLI not found in PATH")
            elapsed = time.time() - start
            return "ERROR: claude CLI not found", elapsed

        # Exponential backoff before retry
        if attempt < max_attempts - 1:
            backoff = 2 ** (attempt + 1)
            logger.info("Backing off %ds before retry...", backoff)
            time.sleep(backoff)

    elapsed = time.time() - start
    return "FAIL: judge call failed after retries", elapsed


# ---------------------------------------------------------------------------
# Judge evaluation
# ---------------------------------------------------------------------------


def judge_scenario(
    scenario: EvalScenario,
    result: EvalResult,
    model: str = "haiku",
) -> GradeResult:
    """Run LLM judge on a scenario/result pair.

    Returns a GradeResult with the judge's verdict.
    """
    prompt = _build_judge_prompt(scenario, result)
    response, elapsed = call_claude_judge(prompt, model=model)

    # Parse verdict from last line
    lines = response.strip().split("\n")
    last_line = lines[-1].strip().upper() if lines else ""
    passed = "PASS" in last_line

    checks = [
        CheckResult(
            check_name="llm_judge",
            passed=passed,
            message=response[:500],
            weight=3.0,
        ),
    ]

    result_obj = GradeResult.from_checks(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        checks=checks,
    )
    return result_obj
