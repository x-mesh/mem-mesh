"""Snapshot tests for hook template rendering — golden file comparison."""

from pathlib import Path

import pytest

from app.cli.hooks.renderer import _render_template
from app.cli.hooks.templates import (
    CURSOR_SESSION_START_TEMPLATE,
    CURSOR_STOP_TEMPLATE,
    ENHANCED_STOP_HOOK_TEMPLATE,
    KIRO_STOP_HOOK_TEMPLATE,
    SESSION_START_HOOK_TEMPLATE,
    STOP_DECIDE_HOOK_TEMPLATE,
    SUBAGENT_START_HOOK_TEMPLATE,
    SUBAGENT_STOP_HOOK_TEMPLATE,
    TASK_COMPLETED_HOOK_TEMPLATE,
    USER_PROMPT_SUBMIT_HOOK_TEMPLATE,
)

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
SNAPSHOT_URL = "https://meme.24x365.online"


def _check_snapshot(request, name: str, rendered: str) -> None:
    """Compare rendered output against golden file, or update if --update-snapshots."""
    snapshot_path = SNAPSHOTS_DIR / name
    if request.config.getoption("--update-snapshots"):
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(rendered, encoding="utf-8")
        pytest.skip("snapshot updated")
    else:
        assert snapshot_path.exists(), f"Snapshot not found: {snapshot_path}. Run with --update-snapshots"
        expected = snapshot_path.read_text(encoding="utf-8")
        assert rendered == expected, (
            f"Snapshot mismatch for {name}! Run with --update-snapshots to update."
        )


def test_claude_session_start_snapshot(request):
    rendered = _render_template(
        SESSION_START_HOOK_TEMPLATE, SNAPSHOT_URL,
        source_tag="claude-code-hook", ide_tag="claude", project_id="mem-mesh",
    )
    _check_snapshot(request, "claude_session_start.sh", rendered)


def test_claude_stop_decide_snapshot(request):
    rendered = _render_template(
        STOP_DECIDE_HOOK_TEMPLATE, SNAPSHOT_URL,
        source_tag="claude-code-hook", ide_tag="claude", project_id="mem-mesh",
    )
    _check_snapshot(request, "claude_stop_decide.sh", rendered)


def test_claude_stop_enhanced_snapshot(request):
    rendered = _render_template(
        ENHANCED_STOP_HOOK_TEMPLATE, SNAPSHOT_URL,
        source_tag="claude-code-hook", ide_tag="claude", project_id="mem-mesh",
    )
    _check_snapshot(request, "claude_stop_enhanced.sh", rendered)


def test_kiro_stop_snapshot(request):
    rendered = _render_template(
        KIRO_STOP_HOOK_TEMPLATE, SNAPSHOT_URL,
        source_tag="kiro-hook", ide_tag="kiro", client_tag="kiro", project_id="mem-mesh",
    )
    _check_snapshot(request, "kiro_stop.sh", rendered)


def test_cursor_session_start_snapshot(request):
    rendered = _render_template(
        CURSOR_SESSION_START_TEMPLATE, SNAPSHOT_URL,
        source_tag="cursor-hook", ide_tag="cursor", project_id="mem-mesh",
    )
    _check_snapshot(request, "cursor_session_start.sh", rendered)


def test_cursor_stop_snapshot(request):
    rendered = _render_template(
        CURSOR_STOP_TEMPLATE, SNAPSHOT_URL,
        source_tag="cursor-hook", ide_tag="cursor", project_id="mem-mesh",
    )
    _check_snapshot(request, "cursor_stop.sh", rendered)


def test_user_prompt_submit_snapshot(request):
    rendered = _render_template(
        USER_PROMPT_SUBMIT_HOOK_TEMPLATE, SNAPSHOT_URL,
        source_tag="claude-code-hook", ide_tag="claude", project_id="mem-mesh",
    )
    _check_snapshot(request, "claude_user_prompt_submit.sh", rendered)


def test_subagent_start_snapshot(request):
    rendered = _render_template(
        SUBAGENT_START_HOOK_TEMPLATE, SNAPSHOT_URL,
        source_tag="claude-code-hook", ide_tag="claude", project_id="mem-mesh",
    )
    _check_snapshot(request, "claude_subagent_start.sh", rendered)


def test_subagent_stop_snapshot(request):
    rendered = _render_template(
        SUBAGENT_STOP_HOOK_TEMPLATE, SNAPSHOT_URL,
        source_tag="claude-code-hook", ide_tag="claude", project_id="mem-mesh",
    )
    _check_snapshot(request, "claude_subagent_stop.sh", rendered)


def test_task_completed_snapshot(request):
    rendered = _render_template(
        TASK_COMPLETED_HOOK_TEMPLATE, SNAPSHOT_URL,
        source_tag="claude-code-hook", ide_tag="claude", project_id="mem-mesh",
    )
    _check_snapshot(request, "claude_task_completed.sh", rendered)
