"""Canonical behavioral rules for mem-mesh hooks — Single Source of Truth.

All IDE-specific renderers (Kiro, Cursor, Claude Code) read from these
definitions. When rules change, bump PROMPT_VERSION and re-run the installer.

Usage:
    from app.cli.prompts.behaviors import CORE_RULES, SAVE_CRITERIA, PROMPT_VERSION
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import List

# ---------------------------------------------------------------------------
# Prompt schema version — bump on ANY behavioral rule change.
# Guarded by PROMPT_CONTENT_HASH (bottom of file): test_prompt_rules.py fails
# when the rule content drifts without a conscious bump. See
# compute_content_hash().
# ---------------------------------------------------------------------------

PROMPT_VERSION: int = 30


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """A single operational rule injected at session start."""

    key: str
    title: str  # Short title
    description: str  # Description (project_id placeholder: {project_id})


@dataclass(frozen=True)
class SaveCriteria:
    """When to save / skip auto-saving conversations."""

    save_when: List[str]
    skip_when: List[str]
    save_format: str  # MCP call example
    idempotency: str  # Duplicate save prevention rule


@dataclass(frozen=True)
class PinCriteria:
    """When to create / skip pin creation."""

    create_when: str
    skip_when: str
    pin_format: str  # MCP call example


@dataclass(frozen=True)
class SessionConfig:
    """Session resume / end configuration."""

    resume_call: str
    resume_description: str
    end_triggers: List[str]  # Example user session-end expressions


# ---------------------------------------------------------------------------
# Canonical definitions
# ---------------------------------------------------------------------------

CORE_RULES: List[Rule] = [
    Rule(
        key="coding_first",
        title="Answer with the work first",
        description=(
            "Return the code or answer first. Perform mem-mesh calls after the "
            "response work is complete. Do not start responses with status "
            "announcements such as 'I will search memory first.'"
        ),
    ),
    Rule(
        key="session_gate",
        title="Report injected session context",
        description=(
            "Session context — the active session and pin counts (pins_count, "
            "in_progress_pins, open_pins, completed_pins) — is auto-injected at "
            "session start by the SessionStart hook, which already resumed it "
            "server-side. Report those counts directly from the injected "
            "context and briefly surface any open or in_progress pin. Do NOT "
            "call session_resume just to fetch them. Call "
            'session_resume(project_id="{project_id}", expand="smart") only as '
            "a fallback when the injected context is absent (hook offline). If "
            "no active session exists, continue with the task; the first "
            "pin_add() or add() call creates the session."
        ),
    ),
    Rule(
        key="pin_tracking",
        title="Track work with Pin Gate (required)",
        description=(
            "Before starting task work, decide Pin Gate. If the request involves "
            "file edits, implementation, bug fixes, refactoring, migrations, "
            "multi-step investigation, or work that may continue into a later "
            'turn, immediately call pin_add(content, project_id="{project_id}", '
            "importance=3). For simple questions, explanations, lookups, "
            "read-only analysis, or basic checks, do not create a pin. Do not "
            "reuse an unrelated in_progress pin. State exactly one of "
            "`Pin created: <id>` or `No pin created: <reason>`. When the work is "
            "done, call pin_complete immediately; do not leave an active pin "
            "before the final response. (importance: 3=normal, 4=important, "
            "5=architecture)"
        ),
    ),
    Rule(
        key="selective_save",
        title="Save permanent memories selectively",
        description=(
            "Use add() only for decision, bug, incident, idea, and code_snippet "
            "memories. Routine task state belongs in pins."
        ),
    ),
    Rule(
        key="context_search",
        title="Use context search",
        description=(
            "When prior decisions, tasks, or design context are referenced, call "
            "search() before writing code. For past team context, consider "
            'search(scope="all") to include the team hub.'
        ),
    ),
    Rule(
        key="session_end",
        title="End sessions when requested",
        description=(
            "When the user explicitly says the session is done, finish the "
            'request and then call session_end(project_id="{project_id}").'
        ),
    ),
    Rule(
        key="anchors_collection",
        title="Attach git anchors to code-tied memories",
        description=(
            "When saving a memory whose validity depends on the code state "
            "(decision, bug, code_snippet about specific files), run "
            "`git rev-parse HEAD` and pass anchors={commit_hash, file_paths, "
            "branch} to add() or pin_promote(). Optionally include "
            "anchors.file_hashes ({relative_path: 'algo:hexdigest', e.g. "
            "'sha256:...' from `shasum -a 256`}) so staleness can later be "
            "verified per file instead of per commit. The server has no git "
            "access — the client is the only party that can anchor a memory. "
            "Skip when not in a git repository or the memory is "
            "code-independent."
        ),
    ),
    Rule(
        key="anchor_verification",
        title="Report anchor staleness you can verify",
        description=(
            "When an injected memory line carries an unverified-anchor warning "
            "(aged anchor), verify it locally when convenient: if "
            "anchors.file_hashes is present, re-hash those files — matching "
            "hashes mean fresh even when the commit is old; otherwise check "
            "the anchored file_paths still exist and the commit is reachable "
            "(`git cat-file -e <commit_hash>`). Then call "
            'report_anchor_status(memory_id, "fresh"|"stale"). A stale verdict '
            "removes the memory from future auto-injection; fresh clears the "
            "warning. Only do this for memories relevant to the current work — "
            "do not sweep."
        ),
    ),
    Rule(
        key="doc_proposals_apply",
        title="Apply approved doc proposals locally",
        description=(
            'If doc_proposals(project_id="{project_id}", status="approved") '
            "returns entries, the user has approved promoting memory into "
            "version-controlled docs. Verify the target file still matches "
            "original_hash, apply proposed_content with your local edit tool, "
            "then call doc_proposal_applied(proposal_id). The server never "
            "writes files — the agent in the repository is the only applier. "
            "Check at session start or when the user asks about pending "
            "promotions; skip silently when there are none."
        ),
    ),
]

SAVE_CRITERIA = SaveCriteria(
    save_when=[
        "버그 진단/해결",
        "아키텍처 또는 설계 결정",
        "중요 설정 변경 또는 마이그레이션",
    ],
    skip_when=[
        '단순 질문/답변 ("뭐야?", "보여줘")',
        "파일 읽기만 한 경우",
        "이미 저장된 내용의 반복",
        "hook/설정 자체의 점검·수정·메타 대화 (hook 동작 확인, settings.json 수정 포함)",
    ],
    save_format=(
        'mcp_mem_mesh_add(content="Q: [질문]\\nA: [핵심 답변]", '
        'category, project_id="{project_id}", tags=[3-5개])'
    ),
    idempotency=(
        "방금 응답에 Memory ID(mcp_mem_mesh_add 결과)가 이미 있으면 "
        '"Already saved" 출력 후 즉시 종료.'
    ),
)

PIN_CRITERIA = PinCriteria(
    create_when=(
        "file edits, implementation, bug fixes, refactoring, migrations, "
        "multi-step investigation, or work that may continue into a later turn"
    ),
    skip_when=(
        "questions, explanation requests, lookups, read-only analysis, simple "
        "checks, or discussion about hooks themselves"
    ),
    pin_format=(
        'mcp_mem_mesh_pin_add(content="[one-line summary]", '
        'project_id="{project_id}", importance=3, tags=[...])\n'
        'Response marker: "Pin created: <id>" or "No pin created: <reason>"\n'
        'On completion: mcp_mem_mesh_pin_complete(pin_id="...") - required'
    ),
)

SESSION_CONFIG = SessionConfig(
    resume_call='session_resume(project_id="{project_id}", expand="smart")',
    resume_description=(
        "새 세션 시작 시 이전 맥락을 확인하고, "
        "미완료 핀이 있으면 사용자에게 간략히 알린다."
    ),
    end_triggers=["오늘 끝", "여기까지", "PR 올려줘"],
)


# ---------------------------------------------------------------------------
# LLM Reflection configuration (Enhanced profile)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReflectConfig:
    """Configuration for LLM reflection hook (Enhanced profile)."""

    model: str
    max_tokens: int
    timeout_seconds: int


REFLECT_CONFIG = ReflectConfig(
    model="claude-haiku-4-5-20251001",
    max_tokens=1024,
    timeout_seconds=20,
)


# ---------------------------------------------------------------------------
# Claude Code native prompt hook configuration (Stop event)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StopPromptConfig:
    """Keyword-based prompt hook config. Haiku picks category enum only."""

    max_reason_chars: int
    valid_categories: tuple


STOP_PROMPT_CONFIG = StopPromptConfig(
    max_reason_chars=80,
    valid_categories=("bug", "decision", "code_snippet", "idea", "incident"),
)


# ---------------------------------------------------------------------------
# Content fingerprint — drift guard
# ---------------------------------------------------------------------------
# Fingerprint of the canonical prompt-text definitions (the content rendered
# into every hook prompt). It is independent of PROMPT_VERSION, so the two are
# separate signals: the hash detects *that* the rules changed; PROMPT_VERSION
# declares *which* revision clients should re-sync to. test_prompt_rules.py
# asserts they stay in sync — when the hash drifts you must consciously bump
# PROMPT_VERSION (intended change) or revert (accidental edit).


def compute_content_hash() -> str:
    """Stable fingerprint of the canonical prompt-text definitions.

    Covers CORE_RULES + SAVE_CRITERIA + PIN_CRITERIA + SESSION_CONFIG. Excludes
    PROMPT_VERSION so a version bump alone never changes the hash.
    """
    payload = {
        "core_rules": [asdict(r) for r in CORE_RULES],
        "save_criteria": asdict(SAVE_CRITERIA),
        "pin_criteria": asdict(PIN_CRITERIA),
        "session_config": asdict(SESSION_CONFIG),
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


# Pinned fingerprint of the definitions above. Regenerate after an intended
# rule change with:
#   python -c "from app.cli.prompts.behaviors import compute_content_hash as h; print(h())"
PROMPT_CONTENT_HASH: str = "32565250757a13e7"
