#!/usr/bin/env python3
"""Regression tests for safe/idempotent hook installation."""

import json
import os
import stat
from pathlib import Path

import pytest

from app.cli import install_hooks
from app.cli.hooks.json_ops import (
    _is_mem_mesh_hook,
    _remove_mem_mesh_hooks_from_json,
)
from app.cli.hooks.renderer import (
    _render_local_template,
    _render_template,
    _shell_safe_local_path,
    _shell_safe_url,
)
from app.cli.hooks.templates import (
    LOCAL_STOP_HOOK_TEMPLATE,
    SESSION_END_HOOK_TEMPLATE,
)

_SHELL_DIR = Path(install_hooks.__file__).parent / "hooks" / "shell"


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
    monkeypatch.setattr(install_hooks, "HOOK_TOKEN_FILE", tmp_path / "hook_token")

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
    monkeypatch.setattr(install_hooks, "HOOK_TOKEN_FILE", tmp_path / "hook_token")

    install_hooks._install_claude(
        url="http://localhost:8000", mode="api", path="", profile="standard"
    )
    assert (hooks_dir / "mem-mesh-session-start.sh").exists()

    install_hooks._install_claude(
        url="http://localhost:8000", mode="http", path="", profile="standard"
    )
    for script_name in _HTTP_EVENTS.values():
        assert not (hooks_dir / script_name).exists(), script_name


# ---------------------------------------------------------------------------
# P1 #2 — uninstall removes only mem-mesh entries (never the user's hooks)
# ---------------------------------------------------------------------------


def test_uninstall_claude_preserves_user_hooks(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "model": "claude-x",  # unrelated top-level key must survive
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/usr/local/bin/user-stop.sh",
                                    "timeout": 9,
                                }
                            ]
                        },
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "~/.claude/hooks/mem-mesh-stop-decide.sh",
                                    "timeout": 10,
                                }
                            ]
                        },
                    ],
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "~/.claude/hooks/mem-mesh-session-start.sh",
                                    "timeout": 15,
                                }
                            ]
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(install_hooks, "CLAUDE_SETTINGS", settings_path)
    monkeypatch.setattr(install_hooks, "CLAUDE_HOOKS_DIR", tmp_path / "hooks")

    install_hooks._uninstall_claude()

    data = _read_json(settings_path)
    assert data["model"] == "claude-x"  # untouched
    stop_cmds = [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]]
    assert "/usr/local/bin/user-stop.sh" in stop_cmds  # user hook preserved
    assert all("mem-mesh" not in c for c in stop_cmds)  # mem-mesh gone
    assert "SessionStart" not in data["hooks"]  # mem-mesh-only event dropped
    assert "Stop" in data["hooks"]  # event with user hooks kept


def test_uninstall_cursor_preserves_user_hooks(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "hooks.json"
    settings_path.write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "sessionStart": [
                        {"type": "command", "command": "/opt/user-start.sh"},
                        {"type": "command", "command": "/x/mem-mesh-session-start.sh"},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(install_hooks, "CURSOR_SETTINGS", settings_path)
    monkeypatch.setattr(install_hooks, "CURSOR_HOOKS_DIR", tmp_path / "hooks")

    install_hooks._uninstall_cursor()

    data = _read_json(settings_path)
    cmds = [h["command"] for h in data["hooks"]["sessionStart"]]
    assert "/opt/user-start.sh" in cmds
    assert all("mem-mesh" not in c for c in cmds)


# ---------------------------------------------------------------------------
# P1 #3 — malformed settings are backed up, never silently overwritten
# ---------------------------------------------------------------------------

_PATCH = {
    "hooks": {
        "Stop": [
            {
                "hooks": [
                    {"type": "command", "command": "/x/mem-mesh-stop.sh", "timeout": 5}
                ]
            }
        ]
    }
}


def test_merge_json_settings_malformed_backs_up_and_raises(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    original = "{ this is : not valid json"
    settings_path.write_text(original, encoding="utf-8")

    with pytest.raises(install_hooks.MalformedSettingsError):
        install_hooks._merge_json_settings(settings_path, _PATCH)

    # Original preserved (not overwritten) + backup carries the original bytes.
    assert settings_path.read_text(encoding="utf-8") == original
    backup = settings_path.with_suffix(settings_path.suffix + ".bak")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == original


def test_merge_json_settings_force_overwrites_malformed(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{bad json", encoding="utf-8")

    install_hooks._merge_json_settings(settings_path, _PATCH, force=True)

    data = _read_json(settings_path)
    assert "Stop" in data["hooks"]
    assert settings_path.with_suffix(settings_path.suffix + ".bak").exists()


# ---------------------------------------------------------------------------
# P1 #5 — URL/path are validated and shell-quoted before template injection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ["file:///etc/passwd", "ftp://x", "not a url", "javascript:alert(1)", ""]
)
def test_shell_safe_url_rejects_non_http(bad: str) -> None:
    with pytest.raises(ValueError):
        _shell_safe_url(bad)


def test_shell_safe_url_passthrough_clean() -> None:
    # A clean URL passes through unchanged (shlex.quote is a no-op).
    assert _shell_safe_url("https://h.example.com:8000") == "https://h.example.com:8000"


@pytest.mark.parametrize(
    "evil",
    [
        "https://h.com/$(touch pwned)",
        "https://h.com/`id`",
        "https://h.com;rm -rf /",
        "https://h.com|cat",
        'https://h.com/"x"',
    ],
)
def test_shell_safe_url_rejects_shell_metachars(evil: str) -> None:
    with pytest.raises(ValueError):
        _shell_safe_url(evil)


def test_render_template_rejects_url_injection() -> None:
    # An injection attempt must be rejected outright, never rendered.
    with pytest.raises(ValueError):
        _render_template(
            SESSION_END_HOOK_TEMPLATE,
            "https://h.com/$(id)",
            source_tag="t",
            ide_tag="t",
        )


# ---------------------------------------------------------------------------
# P1 #1 — native HTTP hooks carry a bearer-token auth header
# ---------------------------------------------------------------------------


def test_claude_http_hook_entry_has_auth_header() -> None:
    settings = install_hooks._build_claude_hooks_settings(
        "standard", "http", "http://localhost:8000"
    )
    for event in _HTTP_EVENTS:
        hook = settings["hooks"][event][0]["hooks"][0]
        assert hook["type"] == "http"
        assert hook["headers"]["Authorization"] == "Bearer $MEM_MESH_HOOK_TOKEN"
        assert hook["allowedEnvVars"] == ["MEM_MESH_HOOK_TOKEN"]
    for event in _HTTP_COMMAND_EVENTS:  # command hooks carry no header
        assert "headers" not in settings["hooks"][event][0]["hooks"][0]


def test_ensure_hook_token_generates_0600_and_reuses(
    tmp_path: Path, monkeypatch
) -> None:
    token_file = tmp_path / ".mem-mesh" / "hook_token"
    monkeypatch.setattr(install_hooks, "HOOK_TOKEN_FILE", token_file)
    monkeypatch.delenv("MEM_MESH_HOOK_TOKEN", raising=False)

    first = install_hooks._ensure_hook_token()
    assert first and token_file.exists()
    assert stat.S_IMODE(os.stat(token_file).st_mode) == 0o600
    assert install_hooks._ensure_hook_token() == first  # reused, not regenerated


# ---------------------------------------------------------------------------
# P1 #5 (round 2) — local path injection: reject + template double-quote removal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "evil",
    [
        "/tmp/$(touch pwned)",
        "/tmp/`id`",
        "/tmp/a;rm -rf /",
        "/tmp/a|cat",
        '/tmp/a"b',
        "/tmp/a&b",
    ],
)
def test_shell_safe_local_path_rejects_injection(evil: str) -> None:
    with pytest.raises(ValueError):
        _shell_safe_local_path(evil)


def test_render_local_template_rejects_path_injection() -> None:
    with pytest.raises(ValueError):
        _render_local_template(LOCAL_STOP_HOOK_TEMPLATE, "/tmp/$(touch pwned)")


def test_local_templates_assign_mem_mesh_path_unquoted() -> None:
    """Regression guard: the placeholder must NOT sit inside double quotes, or
    shlex.quote's single quotes become literal and $(...) executes."""
    for sh in _SHELL_DIR.glob("local-*.sh"):
        text = sh.read_text(encoding="utf-8")
        if "__MEM_MESH_PATH__" not in text:
            continue
        assert 'MEM_MESH_PATH="__MEM_MESH_PATH__"' not in text, sh.name
        assert "MEM_MESH_PATH=__MEM_MESH_PATH__" in text, sh.name


def test_rendered_local_path_blocks_expansion(tmp_path: Path) -> None:
    """A clean path renders as a bare/single-quoted assignment (no outer
    double quotes), so even a hypothetical metachar could not expand."""
    proj = tmp_path / "proj root"  # space exercises shlex.quote
    proj.mkdir()
    rendered = _render_local_template(LOCAL_STOP_HOOK_TEMPLATE, str(proj))
    line = next(ln for ln in rendered.splitlines() if ln.startswith("MEM_MESH_PATH="))
    assert not line.startswith('MEM_MESH_PATH="')  # never wrapped in dquotes
    assert "$(" not in line  # nothing expandable survives


# ---------------------------------------------------------------------------
# P2 — split-module parity: json_ops._is_mem_mesh_hook detects http hooks
# ---------------------------------------------------------------------------


def test_is_mem_mesh_hook_detects_http_endpoint() -> None:
    http_hook = {
        "type": "http",
        "url": "http://localhost:8000/api/hooks/claude/session-start",
        "timeout": 15,
    }
    assert _is_mem_mesh_hook(http_hook) is True
    user_http = {"type": "http", "url": "https://example.com/other", "timeout": 5}
    assert _is_mem_mesh_hook(user_http) is False


def test_remove_mem_mesh_hooks_from_json_strips_http_entries(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "http",
                                    "url": "http://h/api/hooks/claude/session-start",
                                    "timeout": 15,
                                }
                            ]
                        },
                        {"hooks": [{"type": "command", "command": "/opt/user.sh"}]},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    _remove_mem_mesh_hooks_from_json(settings)
    data = json.loads(settings.read_text(encoding="utf-8"))
    cmds = [
        h.get("command", h.get("url", ""))
        for e in data["hooks"]["SessionStart"]
        for h in e["hooks"]
    ]
    assert "/opt/user.sh" in cmds  # user hook preserved
    assert all("/api/hooks/claude/" not in c for c in cmds)  # mem-mesh http gone


def test_render_rejects_project_id_injection() -> None:
    """project_id is interpolated into double-quoted RULES_TEXT; a $(...) or
    backtick value would execute, so it must be rejected."""
    with pytest.raises(ValueError):
        _render_template(
            SESSION_END_HOOK_TEMPLATE,
            "http://localhost:8000",
            project_id="$(touch pwned)",
        )
    with pytest.raises(ValueError):
        _render_local_template(LOCAL_STOP_HOOK_TEMPLATE, "/tmp/safe", project_id="`id`")
