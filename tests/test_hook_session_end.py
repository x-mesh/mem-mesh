"""Tests for SessionEnd and PreCompact hook templates and installation."""

import json
import re

import pytest

from app.cli.hooks.renderer import _load_template, _render_template
from app.cli.hooks.installer import _build_claude_hooks_settings, _build_cursor_hooks_settings
from app.cli.hooks.constants import HOOK_PROFILES


class TestSessionEndTemplate:
    """Verify session-end.sh template content."""

    def test_template_loads(self) -> None:
        content = _load_template("session-end.sh")
        assert len(content) > 50
        assert "#!/bin/bash" in content

    def test_template_has_version_marker(self) -> None:
        content = _load_template("session-end.sh")
        assert "__VERSION_MARKER__" in content

    def test_template_has_api_url_placeholder(self) -> None:
        content = _load_template("session-end.sh")
        assert "__DEFAULT_URL__" in content

    def test_template_calls_end_by_project(self) -> None:
        content = _load_template("session-end.sh")
        assert "end-by-project" in content

    def test_template_exits_zero_on_failure(self) -> None:
        content = _load_template("session-end.sh")
        assert "exit 0" in content
        assert "|| true" in content

    def test_rendered_has_no_placeholders(self) -> None:
        content = _render_template(
            _load_template("session-end.sh"),
            "https://example.com",
            source_tag="test",
            ide_tag="test",
        )
        unresolved = re.findall(r"__[A-Z0-9_]+__", content)
        assert not unresolved, f"Unresolved placeholders: {unresolved}"


class TestPreCompactTemplate:
    """Verify precompact.sh template content."""

    def test_template_loads(self) -> None:
        content = _load_template("precompact.sh")
        assert len(content) > 50
        assert "#!/bin/bash" in content

    def test_template_has_auto_ended_summary(self) -> None:
        content = _load_template("precompact.sh")
        assert "Auto-ended" in content

    def test_template_calls_end_by_project(self) -> None:
        content = _load_template("precompact.sh")
        assert "end-by-project" in content

    def test_template_exits_zero_on_failure(self) -> None:
        content = _load_template("precompact.sh")
        assert "exit 0" in content
        assert "|| true" in content

    def test_rendered_has_no_placeholders(self) -> None:
        content = _render_template(
            _load_template("precompact.sh"),
            "https://example.com",
            source_tag="test",
            ide_tag="test",
        )
        unresolved = re.findall(r"__[A-Z0-9_]+__", content)
        assert not unresolved, f"Unresolved placeholders: {unresolved}"


class TestLocalSessionEndTemplate:
    """Verify local-session-end.sh template content."""

    def test_template_loads(self) -> None:
        content = _load_template("local-session-end.sh")
        assert "#!/bin/bash" in content
        assert "__MEM_MESH_PATH__" in content

    def test_template_uses_python_direct(self) -> None:
        content = _load_template("local-session-end.sh")
        assert "python3" in content
        assert "end_session_by_project" in content


class TestLocalPreCompactTemplate:
    """Verify local-precompact.sh template content."""

    def test_template_loads(self) -> None:
        content = _load_template("local-precompact.sh")
        assert "#!/bin/bash" in content
        assert "__MEM_MESH_PATH__" in content

    def test_template_has_auto_ended_summary(self) -> None:
        content = _load_template("local-precompact.sh")
        assert "Auto-ended by PreCompact hook" in content


class TestHookProfilesIncludeNewHooks:
    """Verify HOOK_PROFILES include session-end and precompact."""

    @pytest.mark.parametrize("profile", ["standard", "enhanced", "minimal"])
    def test_profile_has_session_end(self, profile: str) -> None:
        hooks = HOOK_PROFILES[profile]["hooks"]
        assert "session-end" in hooks

    @pytest.mark.parametrize("profile", ["standard", "enhanced", "minimal"])
    def test_profile_has_precompact(self, profile: str) -> None:
        hooks = HOOK_PROFILES[profile]["hooks"]
        assert "precompact" in hooks


class TestClaudeHooksSettings:
    """Verify _build_claude_hooks_settings includes new events."""

    @pytest.mark.parametrize("profile", ["standard", "enhanced", "minimal"])
    def test_settings_has_session_end(self, profile: str) -> None:
        settings = _build_claude_hooks_settings(profile)
        assert "SessionEnd" in settings["hooks"]
        hooks = settings["hooks"]["SessionEnd"]
        assert len(hooks) == 1
        assert "mem-mesh-session-end.sh" in hooks[0]["hooks"][0]["command"]

    @pytest.mark.parametrize("profile", ["standard", "enhanced", "minimal"])
    def test_settings_has_precompact(self, profile: str) -> None:
        settings = _build_claude_hooks_settings(profile)
        assert "PreCompact" in settings["hooks"]
        hooks = settings["hooks"]["PreCompact"]
        assert len(hooks) == 1
        assert "mem-mesh-precompact.sh" in hooks[0]["hooks"][0]["command"]


class TestCursorHooksSettings:
    """Verify Cursor hooks settings include mapped events."""

    def test_global_settings_has_session_end(self, tmp_path) -> None:
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        settings = _build_cursor_hooks_settings(hooks_dir, scope="global")
        assert "sessionEnd" in settings["hooks"]
        assert "beforeSubmitPrompt" in settings["hooks"]
        assert "preCompact" in settings["hooks"]
        assert "subagentStart" in settings["hooks"]
        assert "subagentStop" in settings["hooks"]

    def test_project_settings_has_session_end(self, tmp_path) -> None:
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        settings = _build_cursor_hooks_settings(hooks_dir, scope="project")
        assert "sessionEnd" in settings["hooks"]
        assert "beforeSubmitPrompt" in settings["hooks"]
        assert "preCompact" in settings["hooks"]
        assert "subagentStart" in settings["hooks"]
        assert "subagentStop" in settings["hooks"]
