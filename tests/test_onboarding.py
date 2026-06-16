"""Tests for the onboarding installer flow."""

from app.cli import onboarding


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

    monkeypatch.setattr(
        onboarding,
        "check_connectivity",
        lambda url: (False, "unreachable: test"),
    )
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
