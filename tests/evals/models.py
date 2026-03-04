"""Data models for DX eval framework.

Defines the core types used across all three tiers:
  - EvalScenario: test input (conversation + expectations)
  - EvalResult: raw output from evaluation
  - GradeResult: grader verdict with individual checks
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ExpectedAction(str, Enum):
    """What the AI should do in response to a scenario."""

    SAVE = "save"
    SKIP = "skip"


class ToolCallPosition(str, Enum):
    """When a tool call should appear relative to the response."""

    BEFORE_RESPONSE = "before_response"
    AFTER_RESPONSE = "after_response"
    ANY = "any"


class EvalTier(str, Enum):
    """Which evaluation tier a scenario belongs to."""

    DETERMINISTIC = "deterministic"
    SIMULATED = "simulated"
    LLM_JUDGED = "llm_judged"


# ---------------------------------------------------------------------------
# Scenario: test input
# ---------------------------------------------------------------------------


class ConversationMessage(BaseModel):
    """A single message in a conversation."""

    role: str  # "system-reminder", "user", "assistant"
    content: str


class ExpectedToolCall(BaseModel):
    """An expected tool invocation."""

    tool_name: str  # e.g., "mcp__mem-mesh__add"
    position: ToolCallPosition = ToolCallPosition.ANY
    args_contains: Optional[Dict[str, str]] = None  # partial match on args


class EvalScenario(BaseModel):
    """A single evaluation scenario."""

    id: str = Field(..., description="Unique scenario ID, e.g., 'hook_save_01'")
    name: str = Field(..., description="Human-readable scenario name")
    description: str = Field(..., description="What this scenario tests")
    tier: EvalTier
    tags: List[str] = Field(default_factory=list)

    # Input
    conversation: List[ConversationMessage] = Field(
        ..., description="Conversation messages forming the test context"
    )

    # Expectations
    expected_action: ExpectedAction
    expected_category: Optional[str] = None  # "bug", "decision", etc.
    expected_tools: List[ExpectedToolCall] = Field(default_factory=list)
    expected_content_patterns: List[str] = Field(
        default_factory=list, description="Regex patterns expected in saved content"
    )
    forbidden_patterns: List[str] = Field(
        default_factory=list, description="Regex patterns that must NOT appear"
    )

    # IDE / hook event metadata (optional)
    ide: Optional[str] = None  # "claude" | "kiro" | "cursor"
    hook_event: Optional[str] = None  # "SessionStart" | "Stop" | "SessionEnd" | "PreCompact"


# ---------------------------------------------------------------------------
# Result: raw evaluation output
# ---------------------------------------------------------------------------


class ToolCall(BaseModel):
    """A recorded tool invocation."""

    tool_name: str
    args: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    position_index: int = 0  # order in the response


class EvalResult(BaseModel):
    """Raw output from running an evaluation scenario."""

    scenario_id: str
    actual_action: str  # "save" or "skip"
    actual_category: Optional[str] = None
    tool_calls: List[ToolCall] = Field(default_factory=list)
    raw_response: Optional[str] = None
    saved_content: Optional[str] = None
    elapsed_seconds: float = 0.0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Grade: verdicts
# ---------------------------------------------------------------------------


class CheckResult(BaseModel):
    """Result of a single grading check."""

    check_name: str
    passed: bool
    message: str
    weight: float = 1.0


class GradeResult(BaseModel):
    """Aggregated grading result for one scenario."""

    scenario_id: str
    scenario_name: str
    passed: bool
    score: float = Field(..., ge=0.0, le=1.0)
    checks: List[CheckResult] = Field(default_factory=list)
    details: str = ""
    graded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_checks(
        cls,
        scenario_id: str,
        scenario_name: str,
        checks: List[CheckResult],
    ) -> GradeResult:
        """Build a GradeResult from individual check results."""
        total_weight = sum(c.weight for c in checks) or 1.0
        weighted_score = sum(c.weight for c in checks if c.passed) / total_weight
        all_passed = all(c.passed for c in checks)
        details = "; ".join(
            f"{'PASS' if c.passed else 'FAIL'} {c.check_name}: {c.message}"
            for c in checks
        )
        return cls(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            passed=all_passed,
            score=round(weighted_score, 3),
            checks=checks,
            details=details,
        )
