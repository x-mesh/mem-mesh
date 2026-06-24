"""Tests for the onboarding installer flow."""

import json

import pytest

from app.cli import onboarding
from app.cli.hooks.status import ApiProbe


@pytest.fixture(autouse=True)
def _isolate_materialized_mem_mesh_files(monkeypatch, tmp_path):
    """Onboarding materializes ~/.mem-mesh files; keep tests in tmp_path."""
    from app.cli import install_hooks
    from app.core import config as core_config

    mem_dir = tmp_path / ".mem-mesh"
    monkeypatch.setattr(install_hooks, "API_URL_FILE", mem_dir / "api_url")
    monkeypatch.setattr(install_hooks, "HOOK_TOKEN_FILE", mem_dir / "hook_token")
    monkeypatch.setattr(core_config, "HOOK_TOKEN_FILE", mem_dir / "hook_token")


def _unreachable_probe(url, timeout=5):
    return ApiProbe("unreachable", None, "unreachable: test")


def _reachable_probe(url, timeout=5):
    return ApiProbe("ok", 200, "reachable")


def test_resolve_hook_targets_auto_uses_detected_only(monkeypatch) -> None:
    monkeypatch.setattr(onboarding, "_detect_targets", lambda: ["claude", "codex"])

    targets, label = onboarding._resolve_hook_targets("auto", yes=True)

    assert targets == ["claude", "codex"]
    assert label == "Claude Code, Codex"


def test_resolve_hook_targets_auto_falls_back_to_claude(monkeypatch) -> None:
    monkeypatch.setattr(onboarding, "_detect_targets", lambda: [])

    targets, label = onboarding._resolve_hook_targets("auto", yes=True)

    assert targets == ["claude"]
    assert "fallback" in label


def test_onboarding_yes_uses_uvx_and_skips_hooks_when_server_missing(
    monkeypatch,
) -> None:
    calls = {"install": 0, "mcp_mode": None, "warmed": 0}

    monkeypatch.setattr(onboarding, "probe_api", _unreachable_probe)
    monkeypatch.setattr(onboarding, "_has_uvx", lambda: True)
    monkeypatch.setattr(
        onboarding,
        "_warm_uvx_cache",
        lambda: calls.__setitem__("warmed", calls["warmed"] + 1) or True,
    )
    monkeypatch.setattr(onboarding, "_detect_targets", lambda: ["codex"])

    from app.cli import install_hooks, mcp_config

    monkeypatch.setattr(
        install_hooks,
        "cmd_install",
        lambda *args, **kwargs: calls.__setitem__("install", calls["install"] + 1),
    )
    monkeypatch.setattr(
        mcp_config,
        "run_mcp_setup",
        lambda **kwargs: calls.__setitem__("mcp_mode", kwargs.get("preferred_mode")),
    )

    onboarding.cmd_onboarding(
        url="http://localhost:9999",
        target="auto",
        profile="standard",
        yes=True,
        force=False,
    )

    assert calls["warmed"] == 1
    assert calls["install"] == 0
    assert calls["mcp_mode"] == "uvx"


def _stub_steps_for_uvx(monkeypatch) -> None:
    """Stub external effects so onboarding runs offline with no side effects."""
    monkeypatch.setattr(onboarding, "probe_api", _unreachable_probe)
    monkeypatch.setattr(onboarding, "_has_uvx", lambda: True)
    monkeypatch.setattr(onboarding, "_warm_uvx_cache", lambda: True)
    monkeypatch.setattr(onboarding, "_detect_targets", lambda: ["codex"])

    # Deterministic "no token" baseline; token-specific tests override after.
    monkeypatch.setattr(
        onboarding, "_client_effective_hook_token", lambda: (None, "none")
    )

    from app.cli import install_hooks, mcp_config

    monkeypatch.setattr(install_hooks, "cmd_install", lambda *a, **k: None)
    monkeypatch.setattr(
        mcp_config,
        "run_mcp_setup",
        lambda **k: {
            "status": "configured",
            "mode": k.get("preferred_mode"),
            "detected_tools": ["codex"],
        },
    )


def test_onboarding_json_emits_structured_result(monkeypatch, capsys) -> None:
    _stub_steps_for_uvx(monkeypatch)
    # --json implies non-interactive: input() must never be called.
    monkeypatch.setattr(
        "builtins.input",
        lambda *a, **k: pytest.fail("input() called in json mode"),
    )

    with pytest.raises(SystemExit) as exc:
        onboarding.cmd_onboarding(target="auto", profile="standard", json_mode=True)
    assert exc.value.code == 0

    data = json.loads(capsys.readouterr().out)
    assert data["tool"] == "mem-mesh"
    assert data["command"] == "onboarding"
    assert data["ok"] is True
    assert data["interactive"] is False
    assert set(data["steps"]) == {"server", "hooks", "mcp"}
    assert data["steps"]["server"]["mcp_mode"] == "uvx"
    assert data["steps"]["hooks"]["status"] == "skipped"
    assert data["steps"]["mcp"]["status"] == "configured"
    assert data["hook_token"]["status"] == "none"  # neutralized in stub
    assert data["next_actions"]  # non-empty hints
    assert data["errors"] == []


def test_onboarding_json_reports_hook_token_from_file(monkeypatch, capsys) -> None:
    _stub_steps_for_uvx(monkeypatch)

    monkeypatch.setattr(
        onboarding, "_client_effective_hook_token", lambda: ("file-token", "file")
    )

    with pytest.raises(SystemExit):
        onboarding.cmd_onboarding(json_mode=True)

    data = json.loads(capsys.readouterr().out)
    assert data["hook_token"] == {"status": "file"}
    # The materialized token is baked into every tool config as a literal bearer
    # header at install time, so a "file" status is fully configured.
    assert not any("setup-token" in a for a in data["next_actions"])


def test_onboarding_json_reports_hook_failure(monkeypatch, capsys) -> None:
    # Server reachable → hooks attempted; force failure to exercise error path.
    monkeypatch.setattr(
        onboarding,
        "probe_api",
        lambda url, timeout=5: ApiProbe("ok", 200, "reachable"),
    )
    monkeypatch.setattr(onboarding, "_detect_targets", lambda: ["claude"])

    from app.cli import install_hooks, mcp_config

    def _boom(*a, **k):
        raise RuntimeError("hook boom")

    monkeypatch.setattr(install_hooks, "cmd_install", _boom)
    monkeypatch.setattr(mcp_config, "run_mcp_setup", lambda **k: {"status": "skipped"})

    with pytest.raises(SystemExit) as exc:
        onboarding.cmd_onboarding(target="auto", json_mode=True)
    assert exc.value.code == 1

    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False
    assert data["steps"]["hooks"]["status"] == "failed"
    assert "hook boom" in data["steps"]["hooks"]["error"]
    assert any("hook boom" in e for e in data["errors"])


@pytest.mark.parametrize(
    ("token", "source"),
    [("file-token", "file"), ("env-token", "env")],
)
def test_onboarding_yes_rejected_token_skips_hooks_without_prompt(
    monkeypatch, capsys, token, source
) -> None:
    calls = {"install": 0, "auth_tokens": []}

    monkeypatch.setattr(onboarding, "probe_api", _reachable_probe)
    monkeypatch.setattr(onboarding, "_detect_targets", lambda: ["codex"])
    monkeypatch.setattr(
        onboarding, "_client_effective_hook_token", lambda: (token, source)
    )
    monkeypatch.setattr(
        onboarding,
        "_auth_probe",
        lambda url, probe_token: calls["auth_tokens"].append(probe_token) or 401,
    )
    monkeypatch.setattr(
        "builtins.input", lambda *a, **k: pytest.fail("input() called under --yes")
    )

    from app.cli import install_hooks, mcp_config

    monkeypatch.setattr(
        install_hooks,
        "cmd_install",
        lambda *a, **k: calls.__setitem__("install", calls["install"] + 1),
    )
    monkeypatch.setattr(mcp_config, "run_mcp_setup", lambda **k: {"status": "skipped"})

    with pytest.raises(SystemExit) as exc:
        onboarding.cmd_onboarding(
            url="http://localhost:8000",
            target="auto",
            yes=True,
            json_mode=True,
        )

    assert exc.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert calls["auth_tokens"] == [token]
    assert calls["install"] == 0
    assert data["steps"]["hooks"]["status"] == "skipped"


def test_onboarding_yes_env_token_materializes_and_configures_auth(
    monkeypatch, tmp_path
) -> None:
    calls = {"install": 0, "mcp": None, "auth_tokens": []}
    token_file = tmp_path / ".mem-mesh" / "hook_token"

    monkeypatch.setattr(onboarding, "probe_api", _reachable_probe)
    monkeypatch.setattr(onboarding, "_detect_targets", lambda: ["codex"])
    monkeypatch.setattr(
        onboarding, "_client_effective_hook_token", lambda: ("env-token", "env")
    )
    monkeypatch.setattr(
        onboarding,
        "_auth_probe",
        lambda url, token: calls["auth_tokens"].append(token) or 200,
    )
    monkeypatch.setattr(
        "builtins.input", lambda *a, **k: pytest.fail("input() called under --yes")
    )

    from app.cli import install_hooks, mcp_config

    monkeypatch.setattr(
        install_hooks,
        "cmd_install",
        lambda *a, **k: calls.__setitem__("install", calls["install"] + 1),
    )
    monkeypatch.setattr(
        mcp_config,
        "run_mcp_setup",
        lambda **k: calls.__setitem__("mcp", k) or {"status": "configured"},
    )

    onboarding.cmd_onboarding(
        url="http://localhost:8000",
        target="auto",
        yes=True,
    )

    assert calls["auth_tokens"] == ["env-token"]
    assert calls["mcp"]["with_auth"] is True
    assert calls["mcp"]["token"] == "env-token"
    assert calls["install"] == 1
    assert token_file.read_text(encoding="utf-8").strip() == "env-token"


def test_client_effective_hook_token_prefers_env(monkeypatch, tmp_path) -> None:
    from app.core import config as core_config

    token_file = tmp_path / "hook_token"
    token_file.write_text("file-token\n", encoding="utf-8")
    monkeypatch.setattr(core_config, "HOOK_TOKEN_FILE", token_file)
    monkeypatch.setenv("MEM_MESH_HOOK_TOKEN", "env-token")

    assert onboarding._client_effective_hook_token() == ("env-token", "env")


def test_client_effective_hook_token_uses_file(monkeypatch, tmp_path) -> None:
    from app.core import config as core_config

    token_file = tmp_path / "hook_token"
    token_file.write_text("file-token\n", encoding="utf-8")
    monkeypatch.setattr(core_config, "HOOK_TOKEN_FILE", token_file)
    monkeypatch.delenv("MEM_MESH_HOOK_TOKEN", raising=False)

    assert onboarding._client_effective_hook_token() == ("file-token", "file")


def test_client_effective_hook_token_none(monkeypatch, tmp_path) -> None:
    from app.core import config as core_config

    monkeypatch.setattr(core_config, "HOOK_TOKEN_FILE", tmp_path / "missing")
    monkeypatch.delenv("MEM_MESH_HOOK_TOKEN", raising=False)

    assert onboarding._client_effective_hook_token() == (None, "none")


class _FakeStream:
    """Minimal stdin/stdout stand-in for isatty-based routing tests."""

    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty

    def write(self, *_args) -> int:
        return 0

    def flush(self) -> None:
        pass


def test_main_bare_runs_onboarding_noninteractive(monkeypatch) -> None:
    import app.cli.main as main_mod

    captured: dict = {}
    monkeypatch.setattr(
        "app.cli.onboarding.cmd_onboarding", lambda **k: captured.update(k)
    )
    monkeypatch.setattr(main_mod.sys, "stdin", _FakeStream(False))
    monkeypatch.setattr(main_mod.sys, "stdout", _FakeStream(False))

    main_mod.main([])

    assert captured.get("yes") is True  # non-TTY → auto non-interactive
    assert captured.get("json_mode") is False
    assert captured.get("target") == "auto"


def test_main_bare_tty_is_interactive(monkeypatch) -> None:
    import app.cli.main as main_mod

    captured: dict = {}
    monkeypatch.setattr(
        "app.cli.onboarding.cmd_onboarding", lambda **k: captured.update(k)
    )
    monkeypatch.setattr(main_mod.sys, "stdin", _FakeStream(True))
    monkeypatch.setattr(main_mod.sys, "stdout", _FakeStream(True))

    main_mod.main([])

    assert captured.get("yes") is False  # TTY → interactive wizard


def test_main_json_flag_routes_noninteractive(monkeypatch) -> None:
    import app.cli.main as main_mod

    captured: dict = {}
    monkeypatch.setattr(
        "app.cli.onboarding.cmd_onboarding", lambda **k: captured.update(k)
    )
    # Even on a TTY, --json forces non-interactive json onboarding.
    monkeypatch.setattr(main_mod.sys, "stdin", _FakeStream(True))
    monkeypatch.setattr(main_mod.sys, "stdout", _FakeStream(True))

    main_mod.main(["--json"])

    assert captured.get("json_mode") is True
    assert captured.get("yes") is True


# ── interactive URL/token helpers (the install wizard) ──


def test_prompt_token_enter_keeps_current_masked(monkeypatch) -> None:
    """Enter keeps the current token; it is shown masked, never in full."""
    captured = {}

    def fake_input(prompt=""):
        captured["prompt"] = prompt
        return ""

    monkeypatch.setattr("builtins.input", fake_input)
    out = onboarding._prompt_token("5-jWabcdefghTESTq7JY")
    assert out == "5-jWabcdefghTESTq7JY"  # Enter → keep current
    assert "q7JY" in captured["prompt"] and "TEST" not in captured["prompt"]  # masked


def test_prompt_token_paste_replaces(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "new-remote-token")
    assert onboarding._prompt_token("old") == "new-remote-token"


def test_prompt_token_none_shows_none(monkeypatch) -> None:
    captured = {}

    def fake_input(prompt=""):
        captured["prompt"] = prompt
        return ""

    monkeypatch.setattr("builtins.input", fake_input)
    assert onboarding._prompt_token(None) is None
    assert "none" in captured["prompt"]


def test_auth_probe_sends_token_and_returns_code(monkeypatch) -> None:
    seen = {}

    def fake_http(method, url, headers=None, data=None, timeout=5.0):
        seen["url"] = url
        seen["auth"] = (headers or {}).get("Authorization")
        return 200, b"{}"

    monkeypatch.setattr("app.cli.hooks.doctor._http", fake_http)
    code = onboarding._auth_probe("https://remote.example/", "tok123")
    assert code == 200
    assert seen["url"].endswith("/api/hooks/claude/session-start")
    assert seen["auth"] == "Bearer tok123"


def test_auth_probe_no_token_omits_header(monkeypatch) -> None:
    seen = {}

    def fake_http(method, url, headers=None, data=None, timeout=5.0):
        seen["auth"] = (headers or {}).get("Authorization")
        return 401, b""

    monkeypatch.setattr("app.cli.hooks.doctor._http", fake_http)
    assert onboarding._auth_probe("http://x", None) == 401
    assert seen["auth"] is None
