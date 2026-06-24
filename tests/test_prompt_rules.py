"""Prompt rule renderer contracts."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

import app.cli.install_hooks as install_hooks
import app.cli.main as cli_main
from app.cli.install_hooks import _sync_claude_rules
from app.cli.prompts.behaviors import PROMPT_VERSION
from app.cli.prompts.renderers import render_claude_project_rules, render_rules_text

HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")


def assert_no_hangul(text: str) -> None:
    assert HANGUL_RE.search(text) is None


def test_rules_text_includes_pin_gate_contract() -> None:
    text = render_rules_text("demo-project")

    assert "Pin Gate" in text
    assert "Pin created: <id>" in text
    assert "No pin created: <reason>" in text
    assert 'project_id="demo-project"' in text
    assert_no_hangul(text)


def test_claude_project_rules_render_managed_block() -> None:
    text = render_claude_project_rules("demo-project")

    assert f"<!-- mem-mesh-hooks:BEGIN v{PROMPT_VERSION} -->" in text
    assert f"<!-- mem-mesh-hooks:END v{PROMPT_VERSION} -->" in text
    assert "mem-mesh hooks sync-project --target claude" in text
    assert 'session_resume(project_id="demo-project", expand="smart")' in text
    assert "pin_complete" in text
    assert_no_hangul(text)


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


def test_mem_mesh_hooks_rules_prints_plain_rules(capsys) -> None:
    cli_main.main(["hooks", "rules", "--project-id", "demo-project"])

    assert capsys.readouterr().out == render_rules_text("demo-project") + "\n"


def test_mem_mesh_hooks_rules_prints_claude_block(capsys) -> None:
    cli_main.main(
        ["hooks", "rules", "--project-id", "demo-project", "--format", "claude"]
    )

    assert capsys.readouterr().out == render_claude_project_rules("demo-project") + "\n"


def test_standalone_hooks_rules_prints_plain_rules(capsys) -> None:
    install_hooks.main(["rules", "--project-id", "demo-project"])

    assert capsys.readouterr().out == render_rules_text("demo-project") + "\n"


def test_local_cli_hooks_rules_omits_version_banner() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "local_cli.py",
            "hooks",
            "rules",
            "--project-id",
            "demo-project",
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout == render_rules_text("demo-project") + "\n"


def test_dashboard_hook_rules_render_matches_cli_plain() -> None:
    from app.web.dashboard.routes import _render_hook_rules

    payload = _render_hook_rules("DemoProject", "plain")

    assert payload["source"] == "mem-mesh-hooks"
    assert payload["prompt_version"] == PROMPT_VERSION
    assert payload["project_id"] == "demo-project"
    assert payload["content"] == render_rules_text("demo-project")


def test_dashboard_hook_rules_render_matches_cli_claude() -> None:
    from app.web.dashboard.routes import _render_hook_rules

    payload = _render_hook_rules("demo-project", "claude")

    assert payload["format"] == "claude"
    assert payload["content"] == render_claude_project_rules("demo-project")


def test_dashboard_hook_rules_render_rejects_unknown_format() -> None:
    from app.web.dashboard.routes import _render_hook_rules

    with pytest.raises(ValueError, match="format"):
        _render_hook_rules("demo-project", "cursor")
