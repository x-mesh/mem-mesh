#!/usr/bin/env python3
"""Regression tests for safe/idempotent hook installation."""

import json
from pathlib import Path

from app.cli import install_hooks


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_merge_json_settings_preserves_existing_user_hooks(tmp_path: Path) -> None:
    settings_path = tmp_path / "hooks.json"
    settings_path.write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "stop": [
                        {
                            "type": "command",
                            "command": "/usr/local/bin/custom-stop.sh",
                            "timeout": 30,
                        },
                        {
                            "type": "command",
                            "command": "/tmp/mem-mesh-stop.sh",
                            "timeout": 5,
                        },
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    patch = install_hooks._build_cursor_hooks_settings(
        tmp_path / "hooks", scope="project"
    )
    install_hooks._merge_json_settings(settings_path, patch)

    data = _read_json(settings_path)
    stop_entries = data["hooks"]["stop"]
    commands = [entry["command"] for entry in stop_entries]

    assert "/usr/local/bin/custom-stop.sh" in commands
    assert "/tmp/mem-mesh-stop.sh" not in commands
    assert str(tmp_path / "hooks" / "mem-mesh-auto-save.sh") in commands


def test_install_cursor_local_is_idempotent_and_no_placeholders(
    tmp_path: Path, monkeypatch
) -> None:
    hooks_dir = tmp_path / "cursor-hooks"
    settings_path = tmp_path / "cursor-hooks.json"
    monkeypatch.setattr(install_hooks, "CURSOR_HOOKS_DIR", hooks_dir)
    monkeypatch.setattr(install_hooks, "CURSOR_SETTINGS", settings_path)

    install_hooks._install_cursor(
        url="https://example.invalid",
        mode="local",
        path=str(tmp_path / "project-root"),
        profile="standard",
    )

    session_start = hooks_dir / "mem-mesh-session-start.sh"
    first_script = session_start.read_text(encoding="utf-8")
    first_settings = settings_path.read_text(encoding="utf-8")

    install_hooks._install_cursor(
        url="https://example.invalid",
        mode="local",
        path=str(tmp_path / "project-root"),
        profile="standard",
    )

    second_script = session_start.read_text(encoding="utf-8")
    second_settings = settings_path.read_text(encoding="utf-8")

    import re

    assert not re.findall(
        r"__[A-Z0-9_]+__", second_script
    ), "Unresolved template placeholders found in rendered script"
    assert first_script == second_script
    assert first_settings == second_settings


def test_sync_cursor_hooks_writes_project_settings_and_is_idempotent(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    cursor_dir = project_root / ".cursor" / "hooks"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    settings_path = project_root / ".cursor" / "hooks.json"
    template_path = project_root / ".cursor" / "hooks.mem-mesh.example.json"
    settings_path.write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "sessionStart": [
                        {
                            "type": "command",
                            "command": str(cursor_dir / "mem-mesh-session-start.sh"),
                            "timeout": 15,
                        }
                    ],
                    "stop": [
                        {
                            "type": "command",
                            "command": "/usr/local/bin/team-stop.sh",
                            "timeout": 25,
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    install_hooks._sync_cursor_hooks(project_root, "mem-mesh")
    first_settings = settings_path.read_text(encoding="utf-8")
    first_template = template_path.read_text(encoding="utf-8")
    first_scripts = {
        name: (cursor_dir / name).read_text(encoding="utf-8")
        for name in (
            "mem-mesh-session-start.sh",
            "mem-mesh-session-end.sh",
            "mem-mesh-auto-save.sh",
            "mem-mesh-before-submit-prompt.sh",
            "mem-mesh-precompact.sh",
            "mem-mesh-subagent-start.sh",
            "mem-mesh-subagent-stop.sh",
        )
    }

    install_hooks._sync_cursor_hooks(project_root, "mem-mesh")
    second_settings = settings_path.read_text(encoding="utf-8")
    second_template = template_path.read_text(encoding="utf-8")
    second_scripts = {
        name: (cursor_dir / name).read_text(encoding="utf-8") for name in first_scripts
    }

    parsed = _read_json(settings_path)
    assert "sessionStart" not in parsed["hooks"]
    stop_commands = [entry["command"] for entry in parsed["hooks"]["stop"]]
    assert "/usr/local/bin/team-stop.sh" in stop_commands
    assert str(cursor_dir / "mem-mesh-auto-save.sh") not in stop_commands

    assert first_settings == second_settings
    assert first_template == second_template
    assert first_scripts == second_scripts

    template = _read_json(template_path)
    assert "beforeSubmitPrompt" in template["hooks"]
    assert "preCompact" in template["hooks"]
    assert "subagentStart" in template["hooks"]
    assert "subagentStop" in template["hooks"]
    template_stop = [entry["command"] for entry in template["hooks"]["stop"]]
    assert str(cursor_dir / "mem-mesh-auto-save.sh") in template_stop


# ---------------------------------------------------------------------------
# Claude Code HTTP hook mode (mode="http")
# ---------------------------------------------------------------------------

# Events that move to a server endpoint in http mode — no shell script written.
_HTTP_EVENTS = {
    "SessionStart": "mem-mesh-session-start.sh",
    "Stop": "mem-mesh-stop-decide.sh",
    "UserPromptSubmit": "mem-mesh-user-prompt-submit.sh",
    "SubagentStop": "mem-mesh-subagent-stop.sh",
    "TaskCompleted": "mem-mesh-task-completed.sh",
}
# Events with no endpoint yet — still a command hook even in http mode.
_HTTP_COMMAND_EVENTS = {
    "SubagentStart": "mem-mesh-subagent-start.sh",
    "SessionEnd": "mem-mesh-session-end.sh",
    "PreCompact": "mem-mesh-precompact.sh",
}


def test_build_claude_hooks_settings_http_mode() -> None:
    """http mode emits http-type entries for covered events, command for rest."""
    settings = install_hooks._build_claude_hooks_settings(
        "standard", "http", "http://localhost:8000/"
    )
    hooks = settings["hooks"]

    for event in _HTTP_EVENTS:
        hook = hooks[event][0]["hooks"][0]
        assert hook["type"] == "http"
        # Trailing slash in the base url must not double up.
        assert hook["url"].startswith("http://localhost:8000/api/hooks/claude/")
        assert "//api" not in hook["url"]
        assert "async" not in hook  # http hooks are non-blocking by nature

    for event in _HTTP_COMMAND_EVENTS:
        hook = hooks[event][0]["hooks"][0]
        assert hook["type"] == "command"
        assert hook["command"].endswith(".sh")


def test_install_claude_http_skips_endpoint_scripts(
    tmp_path: Path, monkeypatch
) -> None:
    """http install writes only the command-only scripts; settings use http type."""
    hooks_dir = tmp_path / "claude-hooks"
    settings_path = tmp_path / "claude-settings.json"
    monkeypatch.setattr(install_hooks, "CLAUDE_HOOKS_DIR", hooks_dir)
    monkeypatch.setattr(install_hooks, "CLAUDE_SETTINGS", settings_path)

    install_hooks._install_claude(
        url="http://localhost:8000", mode="http", path="", profile="standard"
    )

    # Endpoint-covered scripts must NOT be written.
    for script_name in _HTTP_EVENTS.values():
        assert not (hooks_dir / script_name).exists(), script_name
    # Command-only scripts MUST be written.
    for script_name in _HTTP_COMMAND_EVENTS.values():
        assert (hooks_dir / script_name).exists(), script_name

    parsed = _read_json(settings_path)
    assert parsed["hooks"]["SessionStart"][0]["hooks"][0]["type"] == "http"
    assert parsed["hooks"]["PreCompact"][0]["hooks"][0]["type"] == "command"

    # Idempotent re-run.
    first = settings_path.read_text(encoding="utf-8")
    install_hooks._install_claude(
        url="http://localhost:8000", mode="http", path="", profile="standard"
    )
    assert settings_path.read_text(encoding="utf-8") == first


def test_install_claude_api_to_http_removes_stale_scripts(
    tmp_path: Path, monkeypatch
) -> None:
    """Switching api -> http deletes the now-replaced shell scripts."""
    hooks_dir = tmp_path / "claude-hooks"
    settings_path = tmp_path / "claude-settings.json"
    monkeypatch.setattr(install_hooks, "CLAUDE_HOOKS_DIR", hooks_dir)
    monkeypatch.setattr(install_hooks, "CLAUDE_SETTINGS", settings_path)

    install_hooks._install_claude(
        url="http://localhost:8000", mode="api", path="", profile="standard"
    )
    assert (hooks_dir / "mem-mesh-session-start.sh").exists()

    install_hooks._install_claude(
        url="http://localhost:8000", mode="http", path="", profile="standard"
    )
    for script_name in _HTTP_EVENTS.values():
        assert not (hooks_dir / script_name).exists(), script_name
