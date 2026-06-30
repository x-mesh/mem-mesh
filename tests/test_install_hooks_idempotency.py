#!/usr/bin/env python3
"""Regression tests for safe/idempotent hook installation."""

import json
import os
import stat
from pathlib import Path

import pytest

from app.cli import install_hooks
from app.cli.hooks.json_ops import (
    _count_mem_mesh_hook_entries,
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
    LOCAL_SUBAGENT_START_HOOK_TEMPLATE,
    LOCAL_STOP_HOOK_TEMPLATE,
    SESSION_END_HOOK_TEMPLATE,
)

_SHELL_DIR = Path(install_hooks.__file__).parent / "hooks" / "shell"


@pytest.fixture(autouse=True)
def _isolate_materialized_mem_mesh_files(monkeypatch, tmp_path):
    """Tests must not rewrite the developer's real ~/.mem-mesh config."""
    from app.core import config as core_config

    mem_dir = tmp_path / ".mem-mesh"
    monkeypatch.setattr(install_hooks, "API_URL_FILE", mem_dir / "api_url")
    monkeypatch.setattr(install_hooks, "HOOK_TOKEN_FILE", mem_dir / "hook_token")
    monkeypatch.setattr(core_config, "HOOK_TOKEN_FILE", mem_dir / "hook_token")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _mem_mesh_tool_names() -> list[str]:
    from app.mcp_common.schemas import get_all_tool_schemas

    return [schema["name"] for schema in get_all_tool_schemas()]


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
        "standard", "http", "http://localhost:8000/", token="tok-http"
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
    token_file = tmp_path / "hook_token"
    monkeypatch.setattr(install_hooks, "CLAUDE_HOOKS_DIR", hooks_dir)
    monkeypatch.setattr(install_hooks, "CLAUDE_SETTINGS", settings_path)
    monkeypatch.setattr(install_hooks, "HOOK_TOKEN_FILE", token_file)
    # Pin the materialized token file to tmp + seed a value so the baked HTTP-hook
    # header is deterministic and a real ~/.mem-mesh token cannot leak in.
    monkeypatch.setattr("app.core.config.HOOK_TOKEN_FILE", token_file)
    monkeypatch.setattr(
        "app.core.config._data_dir_hook_token_file",
        lambda: tmp_path / "data" / "hook_token",
    )
    monkeypatch.delenv("MEM_MESH_HOOK_TOKEN", raising=False)
    token_file.write_text("seeded-http-tok", encoding="utf-8")

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
    session_hook = parsed["hooks"]["SessionStart"][0]["hooks"][0]
    assert session_hook["type"] == "http"
    # The literal token is baked into the header — no env reference, no empty Bearer.
    assert session_hook["headers"]["Authorization"] == "Bearer seeded-http-tok"
    assert "allowedEnvVars" not in session_hook
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


def test_claude_http_hook_entry_has_literal_auth_header() -> None:
    """The native HTTP hook header carries the literal hook token baked in at
    install time, not a ``$MEM_MESH_HOOK_TOKEN`` env reference, and no
    ``allowedEnvVars``."""
    settings = install_hooks._build_claude_hooks_settings(
        "standard", "http", "http://localhost:8000", token="real-tok-123"
    )
    for event in _HTTP_EVENTS:
        hook = settings["hooks"][event][0]["hooks"][0]
        assert hook["type"] == "http"
        assert hook["headers"]["Authorization"] == "Bearer real-tok-123"
        assert "${" not in hook["headers"]["Authorization"]
        assert "$MEM_MESH_HOOK_TOKEN" not in hook["headers"]["Authorization"]
        assert "allowedEnvVars" not in hook
    for event in _HTTP_COMMAND_EVENTS:  # command hooks carry no header
        assert "headers" not in settings["hooks"][event][0]["hooks"][0]


def test_claude_http_hook_omits_header_without_token() -> None:
    """No resolved token -> the header is omitted entirely rather than baking an
    empty ``Bearer `` (which would silently fail auth)."""
    settings = install_hooks._build_claude_hooks_settings(
        "standard", "http", "http://localhost:8000", token=None
    )
    for event in _HTTP_EVENTS:
        hook = settings["hooks"][event][0]["hooks"][0]
        assert hook["type"] == "http"
        assert "headers" not in hook
        assert "allowedEnvVars" not in hook


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


def test_ensure_hook_token_materializes_env(tmp_path: Path, monkeypatch) -> None:
    token_file = tmp_path / ".mem-mesh" / "hook_token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("stale-file-token\n", encoding="utf-8")
    monkeypatch.setattr(install_hooks, "HOOK_TOKEN_FILE", token_file)
    monkeypatch.setenv("MEM_MESH_HOOK_TOKEN", "env-token-123")

    token = install_hooks._ensure_hook_token()

    assert token == "env-token-123"
    assert token_file.read_text(encoding="utf-8").strip() == "env-token-123"
    assert stat.S_IMODE(os.stat(token_file).st_mode) == 0o600


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


def test_render_local_subagent_start_output_mode(tmp_path: Path) -> None:
    rendered = _render_local_template(
        LOCAL_SUBAGENT_START_HOOK_TEMPLATE,
        str(tmp_path),
        hook_output_mode="compact",
    )

    assert 'HOOK_OUTPUT_MODE="${MEM_MESH_HOOK_OUTPUT_MODE:-compact}"' in rendered
    assert "jq -Rrsr '.[0:1200]'" in rendered


def test_render_local_template_rejects_bad_output_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="hook_output_mode"):
        _render_local_template(
            LOCAL_SUBAGENT_START_HOOK_TEMPLATE,
            str(tmp_path),
            hook_output_mode="verbose",
        )


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


def test_install_codex_api_writes_command_hooks_and_mcp_config(
    tmp_path: Path, monkeypatch
) -> None:
    token_file = tmp_path / ".mem-mesh" / "hook_token"
    monkeypatch.setattr(install_hooks, "HOOK_TOKEN_FILE", token_file)
    monkeypatch.setattr("app.core.config.HOOK_TOKEN_FILE", token_file)
    monkeypatch.setattr(
        "app.core.config._data_dir_hook_token_file",
        lambda: tmp_path / "data" / "hook_token",
    )
    monkeypatch.delenv("MEM_MESH_HOOK_TOKEN", raising=False)

    install_hooks._install_codex(
        url="https://mem.example.com",
        mode="api",
        path="",
        profile="standard",
        base_dir=tmp_path,
    )

    codex_dir = tmp_path / ".codex"
    hooks_dir = codex_dir / "hooks"
    hooks_path = codex_dir / "hooks.json"
    config_path = codex_dir / "config.toml"

    assert (hooks_dir / "mem-mesh-session-start.sh").exists()
    assert (hooks_dir / "mem-mesh-stop-decide.sh").exists()
    assert (hooks_dir / "mem-mesh-precompact.sh").exists()
    session_script = (hooks_dir / "mem-mesh-session-start.sh").read_text(
        encoding="utf-8"
    )
    prompt_script = (hooks_dir / "mem-mesh-user-prompt-submit.sh").read_text(
        encoding="utf-8"
    )
    precompact_script = (hooks_dir / "mem-mesh-precompact.sh").read_text(
        encoding="utf-8"
    )
    subagent_start_script = (hooks_dir / "mem-mesh-subagent-start.sh").read_text(
        encoding="utf-8"
    )
    assert 'HOOK_OUTPUT_MODE="${MEM_MESH_HOOK_OUTPUT_MODE:-compact}"' in session_script
    assert 'HOOK_OUTPUT_MODE="${MEM_MESH_HOOK_OUTPUT_MODE:-compact}"' in prompt_script
    assert (
        'HOOK_OUTPUT_MODE="${MEM_MESH_HOOK_OUTPUT_MODE:-compact}"' in precompact_script
    )
    assert (
        'HOOK_OUTPUT_MODE="${MEM_MESH_HOOK_OUTPUT_MODE:-compact}"'
        in subagent_start_script
    )

    hooks = _read_json(hooks_path)["hooks"]
    all_handlers = [
        hook
        for entries in hooks.values()
        for entry in entries
        for hook in entry["hooks"]
    ]
    assert all(handler["type"] == "command" for handler in all_handlers)
    assert all("async" not in handler for handler in all_handlers)
    assert not any(handler.get("type") == "http" for handler in all_handlers)
    assert "PostToolUse" in hooks
    assert (
        hooks["PostToolUse"][0]["matcher"]
        == "Edit|Write|MultiEdit|NotebookEdit|apply_patch"
    )

    config_text = config_path.read_text(encoding="utf-8")
    assert "[mcp_servers.mem-mesh]" in config_text
    assert 'url = "https://mem.example.com/mcp/sse"' in config_text
    # Generated config stamps a literal bearer header: no named env indirection.
    assert "bearer_token_env_var" not in config_text
    # Codex rejects env blocks for streamable_http/url transports; client
    # identity is carried by hook payloads and MCP clientInfo/User-Agent.
    assert 'MEM_MESH_CLIENT = "codex"' not in config_text
    for tool_name in _mem_mesh_tool_names():
        assert f"[mcp_servers.mem-mesh.tools.{tool_name}]" in config_text
    assert config_text.count('approval_mode = "approve"') == len(_mem_mesh_tool_names())

    first_hooks = hooks_path.read_text(encoding="utf-8")
    first_config = config_path.read_text(encoding="utf-8")
    install_hooks._install_codex(
        url="https://mem.example.com",
        mode="api",
        path="",
        profile="standard",
        base_dir=tmp_path,
    )
    assert hooks_path.read_text(encoding="utf-8") == first_hooks
    assert config_path.read_text(encoding="utf-8") == first_config


def test_uvx_mem_mesh_hooks_install_codex_writes_active_hooks(
    tmp_path: Path, monkeypatch
) -> None:
    """`uvx mem-mesh hooks install` should repair Codex hooks.json, not only MCP."""
    import app.cli.main as main_mod
    from app.cli.hooks import status as hook_status

    monkeypatch.setattr(hook_status, "server_enforces_auth", lambda _url: False)

    codex_dir = tmp_path / ".codex"
    hooks_file = codex_dir / "hooks.json"
    hooks_file.parent.mkdir(parents=True)
    hooks_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUse": [
                        {
                            "matcher": "Skill",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        'node "$HOME/.codex/xm/hooks/'
                                        'trace-session.mjs" post'
                                    ),
                                }
                            ],
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    main_mod.main(
        [
            "hooks",
            "install",
            "--target",
            "codex",
            "--url",
            "https://mem.example.com",
            "--scope",
            "project",
            "--dir",
            str(tmp_path),
        ]
    )

    hooks_dir = codex_dir / "hooks"
    data = _read_json(hooks_file)
    post_tool_commands = [
        hook["command"]
        for entry in data["hooks"]["PostToolUse"]
        for hook in entry["hooks"]
    ]

    assert _count_mem_mesh_hook_entries(hooks_file) == 7
    assert 'node "$HOME/.codex/xm/hooks/trace-session.mjs" post' in post_tool_commands
    assert any(
        command.endswith("mem-mesh-post-tool-use.sh") for command in post_tool_commands
    )
    assert (hooks_dir / "mem-mesh-session-start.sh").exists()
    assert (hooks_dir / "mem-mesh-post-tool-use.sh").exists()

    post_tool_script = (hooks_dir / "mem-mesh-post-tool-use.sh").read_text(
        encoding="utf-8"
    )
    assert '_MM_CLIENT="codex"' in post_tool_script
    assert '--arg source "codex-hook"' in post_tool_script
    assert '--arg client "codex"' in post_tool_script

    config_text = (codex_dir / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.mem-mesh]" in config_text
    assert 'url = "https://mem.example.com/mcp/sse"' in config_text


def test_install_codex_local_uses_stdio_mcp_and_no_post_tool_hook(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    project.mkdir()

    install_hooks._install_codex(
        url="http://localhost:8000",
        mode="local",
        path=str(project),
        profile="standard",
        base_dir=tmp_path,
    )

    hooks = _read_json(tmp_path / ".codex" / "hooks.json")["hooks"]
    hooks_dir = tmp_path / ".codex" / "hooks"
    output_scripts = [
        "mem-mesh-session-start.sh",
        "mem-mesh-precompact.sh",
        "mem-mesh-user-prompt-submit.sh",
        "mem-mesh-subagent-start.sh",
    ]
    for name in output_scripts:
        script = (hooks_dir / name).read_text(encoding="utf-8")
        assert 'HOOK_OUTPUT_MODE="${MEM_MESH_HOOK_OUTPUT_MODE:-compact}"' in script

    assert "PostToolUse" not in hooks
    stop_command = hooks["Stop"][0]["hooks"][0]["command"]
    assert stop_command.endswith("mem-mesh-stop.sh")

    config_text = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "command =" in config_text
    assert 'args = ["-m", "app.mcp_stdio"]' in config_text
    assert f'cwd = "{project}"' in config_text
    assert 'MEM_MESH_CLIENT = "codex"' in config_text
    assert "[mcp_servers.mem-mesh.tools.add]" in config_text
    assert "[mcp_servers.mem-mesh.tools.session_resume]" in config_text


def test_uninstall_codex_preserves_user_hooks_and_removes_mcp(
    tmp_path: Path, monkeypatch
) -> None:
    codex_dir = tmp_path / ".codex"
    hooks_dir = codex_dir / "hooks"
    hooks_dir.mkdir(parents=True)
    hooks_file = codex_dir / "hooks.json"
    config_path = codex_dir / "config.toml"
    (hooks_dir / "mem-mesh-stop-decide.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    hooks_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {"hooks": [{"type": "command", "command": "/opt/user.sh"}]},
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": str(
                                        hooks_dir / "mem-mesh-stop-decide.sh"
                                    ),
                                }
                            ]
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    config_path.write_text(
        "\n".join(
            [
                'model = "gpt-5.5"',
                "",
                "[mcp_servers.mem-mesh]",
                'url = "http://localhost:8000/mcp/sse"',
                "",
                "[mcp_servers.other]",
                'command = "other"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(install_hooks, "CODEX_HOOKS_DIR", hooks_dir)
    monkeypatch.setattr(install_hooks, "CODEX_HOOKS_FILE", hooks_file)
    monkeypatch.setattr(install_hooks, "CODEX_CONFIG", config_path)

    install_hooks._uninstall_codex()

    data = _read_json(hooks_file)
    cmds = [h["command"] for entry in data["hooks"]["Stop"] for h in entry["hooks"]]
    assert "/opt/user.sh" in cmds
    assert all("mem-mesh" not in cmd for cmd in cmds)
    assert not (hooks_dir / "mem-mesh-stop-decide.sh").exists()

    config_text = config_path.read_text(encoding="utf-8")
    assert 'model = "gpt-5.5"' in config_text
    assert "[mcp_servers.mem-mesh]" not in config_text
    assert "[mcp_servers.other]" in config_text


def test_mcp_config_configures_codex_toml(tmp_path: Path) -> None:
    from app.cli import mcp_config

    config_path = tmp_path / ".codex" / "config.toml"
    tool = {
        "name": "Codex",
        "key": "codex",
        "config_path": config_path,
        "installed": True,
        "has_config": False,
    }
    entry = mcp_config.generate_mcp_entry(
        mode="http", url="https://mem.example.com", tool_key="codex"
    )

    ok, msg = mcp_config.configure_tool(tool, entry, do_backup=True)

    assert ok is True
    assert msg == "added"
    text = config_path.read_text(encoding="utf-8")
    assert "[mcp_servers.mem-mesh]" in text
    assert 'url = "https://mem.example.com/mcp/sse"' in text
    assert 'MEM_MESH_CLIENT = "codex"' not in text
    for tool_name in _mem_mesh_tool_names():
        assert f"[mcp_servers.mem-mesh.tools.{tool_name}]" in text
    assert text.count('approval_mode = "approve"') == len(_mem_mesh_tool_names())

    verified, verify_msg = mcp_config.verify_tool_config(tool)
    assert verified is True
    assert verify_msg == "configured (Codex config.toml)"

    removed, remove_msg = mcp_config.remove_tool_config(tool)
    assert removed is True
    assert remove_msg == "removed"
    assert "[mcp_servers.mem-mesh]" not in config_path.read_text(encoding="utf-8")


def test_mcp_config_codex_bakes_literal_bearer_header(tmp_path: Path) -> None:
    """An auth-enabled Codex MCP entry carries the literal bearer token in an
    ``[mcp_servers.mem-mesh.http_headers]`` table. Codex has no inline bearer
    field, but http_headers holds the static literal."""
    from app.cli import mcp_config

    config_path = tmp_path / ".codex" / "config.toml"
    tool = {
        "name": "Codex",
        "key": "codex",
        "config_path": config_path,
        "installed": True,
        "has_config": False,
    }
    entry = mcp_config.generate_mcp_entry(
        mode="http",
        url="https://mem.example.com",
        tool_key="codex",
        with_auth=True,
        token="codex-tok-456",
    )

    ok, _ = mcp_config.configure_tool(tool, entry, do_backup=False)
    assert ok is True

    text = config_path.read_text(encoding="utf-8")
    assert "[mcp_servers.mem-mesh.http_headers]" in text
    assert 'Authorization = "Bearer codex-tok-456"' in text
    assert "bearer_token_env_var" not in text
    assert "${" not in text
    assert "[mcp_servers.mem-mesh.tools.add]" in text
    assert 'approval_mode = "approve"' in text


def test_mcp_config_claude_desktop_uses_mcp_remote_proxy() -> None:
    """Claude Desktop's claude_desktop_config.json cannot read a native
    url/type:"http" entry — it only launches stdio servers. The http-mode entry
    must therefore be an ``mcp-remote`` stdio proxy (npx) with the literal bearer
    token passed as a ``--header`` arg, NOT a url/headers block (a bare http entry
    silently fails to load in Claude Desktop)."""
    from app.cli import mcp_config

    entry = mcp_config.generate_mcp_entry(
        mode="http",
        url="https://remote.example",
        tool_key="claude-desktop",
        with_auth=True,
        token="desktop-tok-789",
    )

    assert entry["command"] == "npx"
    assert "mcp-remote" in entry["args"]
    assert "https://remote.example/mcp/sse" in entry["args"]
    assert "--header" in entry["args"]
    assert "Authorization: Bearer desktop-tok-789" in entry["args"]
    # Must NOT be a native http entry.
    assert "url" not in entry
    assert "type" not in entry
    assert "headers" not in entry


def test_mcp_config_json_entries_auto_approve_all_schema_tools() -> None:
    from app.cli import mcp_config

    entry = mcp_config.generate_mcp_entry(
        mode="http", url="https://remote.example", tool_key="claude-code"
    )

    assert entry["env"] == {"MEM_MESH_CLIENT": "claude_code"}
    assert entry["autoApprove"] == _mem_mesh_tool_names()


def test_ensure_api_url_writes_materialized_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    """_ensure_api_url mirrors the effective URL into the ~/.mem-mesh fallback."""
    api_file = tmp_path / ".mem-mesh" / "api_url"
    monkeypatch.setattr(install_hooks, "API_URL_FILE", api_file)

    # Trailing slash is normalized away so the file matches resolve_api_url().
    install_hooks._ensure_api_url("http://localhost:8000/")
    assert api_file.read_text(encoding="utf-8").strip() == "http://localhost:8000"
    # World-readable (not a secret) — token file stays 0600, this one 0644.
    assert stat.S_IMODE(api_file.stat().st_mode) == 0o644


def test_ensure_api_url_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    """Re-running with the same URL leaves the file (and its mtime) untouched."""
    api_file = tmp_path / ".mem-mesh" / "api_url"
    monkeypatch.setattr(install_hooks, "API_URL_FILE", api_file)

    install_hooks._ensure_api_url("http://localhost:8000")
    first_mtime = api_file.stat().st_mtime_ns
    install_hooks._ensure_api_url("http://localhost:8000")  # no-op
    assert api_file.stat().st_mtime_ns == first_mtime
    # A changed URL rewrites it.
    install_hooks._ensure_api_url("http://localhost:9999")
    assert api_file.read_text(encoding="utf-8").strip() == "http://localhost:9999"


def test_write_hook_token_explicit(tmp_path: Path, monkeypatch) -> None:
    """_write_hook_token stores a caller-supplied token at 0600, idempotently."""
    tok_file = tmp_path / ".mem-mesh" / "hook_token"
    monkeypatch.setattr(install_hooks, "HOOK_TOKEN_FILE", tok_file)
    monkeypatch.setattr("app.core.config.HOOK_TOKEN_FILE", tok_file, raising=False)

    install_hooks._write_hook_token("  remote-token-abc  ")  # trimmed
    assert tok_file.read_text(encoding="utf-8").strip() == "remote-token-abc"
    assert stat.S_IMODE(tok_file.stat().st_mode) == 0o600

    first = tok_file.stat().st_mtime_ns
    install_hooks._write_hook_token("remote-token-abc")  # unchanged → no rewrite
    assert tok_file.stat().st_mtime_ns == first
    install_hooks._write_hook_token("")  # blank → no-op, value preserved
    assert tok_file.read_text(encoding="utf-8").strip() == "remote-token-abc"


def test_run_mcp_setup_honors_explicit_url_over_env(monkeypatch, capsys) -> None:
    """Regression: an explicit url is no longer shadowed by MEM_MESH_API_URL env."""
    from app.cli import mcp_config

    # env points elsewhere; the passed url must still win.
    monkeypatch.setenv("MEM_MESH_API_URL", "http://localhost:8000")
    monkeypatch.setattr(mcp_config, "detect_tools", lambda: [])  # short-circuit

    result = mcp_config.run_mcp_setup(url="https://remote.example", yes=True)
    out = capsys.readouterr().out
    assert "https://remote.example" in out
    assert "localhost:8000" not in out
    assert result["status"] == "no_tools"
