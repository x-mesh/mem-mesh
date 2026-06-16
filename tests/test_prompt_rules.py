"""Prompt rule renderer contracts."""

from pathlib import Path

from app.cli.install_hooks import _sync_claude_rules
from app.cli.prompts.behaviors import PROMPT_VERSION
from app.cli.prompts.renderers import render_claude_project_rules, render_rules_text


def test_rules_text_includes_pin_gate_contract() -> None:
    text = render_rules_text("demo-project")

    assert "Pin Gate" in text
    assert "Pin created: <id>" in text
    assert "No pin created: <reason>" in text
    assert 'project_id="demo-project"' in text


def test_claude_project_rules_render_managed_block() -> None:
    text = render_claude_project_rules("demo-project")

    assert f"<!-- mem-mesh-hooks:BEGIN v{PROMPT_VERSION} -->" in text
    assert f"<!-- mem-mesh-hooks:END v{PROMPT_VERSION} -->" in text
    assert "mem-mesh hooks sync-project --target claude" in text
    assert 'session_resume(project_id="demo-project", expand="smart")' in text
    assert "pin_complete" in text


def test_sync_claude_rules_preserves_existing_content(tmp_path: Path) -> None:
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# Existing Rules\n\nKeep this section.\n", encoding="utf-8")

    _sync_claude_rules(tmp_path, "demo-project")
    first = claude_md.read_text(encoding="utf-8")

    assert "# Existing Rules" in first
    assert "Keep this section." in first
    assert first.count("mem-mesh-hooks:BEGIN") == 1
    assert "demo-project" in first

    _sync_claude_rules(tmp_path, "other-project")
    second = claude_md.read_text(encoding="utf-8")

    assert "# Existing Rules" in second
    assert "Keep this section." in second
    assert second.count("mem-mesh-hooks:BEGIN") == 1
    assert "other-project" in second
    assert "demo-project" not in second
