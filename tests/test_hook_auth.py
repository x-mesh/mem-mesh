"""Unit tests for hook endpoint authentication (P1 server-side).

Covers:
* ``is_loopback_host`` classification
* ``resolve_hook_token`` env-first / file-fallback / none
* effective bind-host capture (``set/get_effective_bind_host``)
* ``verify_hook_token`` dependency policy: token match (any host); no-token
  loopback allow; no-token non-loopback **allow + one-time WARNING** (the
  intentional reversal of the earlier 401 fail-closed — see task a0b90505)
"""

import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.core.config as cfg
import app.web.oauth.middleware as mw


def _request(authorization=None):
    """Minimal stand-in for starlette Request (dependency only reads headers)."""
    headers = {}
    if authorization is not None:
        headers["Authorization"] = authorization
    return SimpleNamespace(headers=headers)


def _configure(monkeypatch, *, token, host):
    # verify_hook_token judges loopback against the *effective* bind host now,
    # not settings.server_host. Reset the one-time warning guard per test.
    monkeypatch.setattr(mw, "resolve_hook_token", lambda: token)
    monkeypatch.setattr(mw, "get_effective_bind_host", lambda: host)
    monkeypatch.setattr(mw, "_exposure_warned", False)


# ───────────────────────── is_loopback_host ─────────────────────────


@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.0.0.1", True),
        ("127.0.0.53", True),
        ("localhost", True),
        ("::1", True),
        ("0.0.0.0", False),
        ("::", False),
        ("192.168.1.10", False),
        ("example.com", False),
        ("", False),
        (None, False),
    ],
)
def test_is_loopback_host(host, expected):
    assert mw.is_loopback_host(host) is expected


# ──────────────────────── resolve_hook_token ────────────────────────


def _settings(tmp_path, *, hook_token):
    """Stand-in settings with a database_path (drives the data-dir token path)."""
    return SimpleNamespace(
        hook_token=hook_token, database_path=str(tmp_path / "memories.db")
    )


def test_resolve_token_env_first(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cfg, "get_settings", lambda: _settings(tmp_path, hook_token="env-tok")
    )
    monkeypatch.setattr(cfg, "HOOK_TOKEN_FILE", tmp_path / "legacy_hook_token")
    assert cfg.resolve_hook_token() == "env-tok"


def test_resolve_token_data_dir_before_legacy(monkeypatch, tmp_path):
    # The data-dir token (next to the DB) outranks the legacy ~/.mem-mesh file.
    (tmp_path / "hook_token").write_text("data-tok\n", encoding="utf-8")
    legacy = tmp_path / "legacy_hook_token"
    legacy.write_text("legacy-tok\n", encoding="utf-8")
    monkeypatch.setattr(
        cfg, "get_settings", lambda: _settings(tmp_path, hook_token=None)
    )
    monkeypatch.setattr(cfg, "HOOK_TOKEN_FILE", legacy)
    assert cfg.resolve_hook_token() == "data-tok"


def test_resolve_token_legacy_fallback(monkeypatch, tmp_path):
    # No env, no data-dir token -> fall through to the legacy ~/.mem-mesh file.
    legacy = tmp_path / "legacy_hook_token"
    legacy.write_text("legacy-tok\n", encoding="utf-8")
    monkeypatch.setattr(
        cfg,
        "get_settings",
        lambda: SimpleNamespace(
            hook_token=None, database_path=str(tmp_path / "sub" / "memories.db")
        ),
    )
    monkeypatch.setattr(cfg, "HOOK_TOKEN_FILE", legacy)
    assert cfg.resolve_hook_token() == "legacy-tok"


def test_resolve_token_none_when_unset(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cfg,
        "get_settings",
        lambda: SimpleNamespace(
            hook_token=None, database_path=str(tmp_path / "sub" / "memories.db")
        ),
    )
    monkeypatch.setattr(cfg, "HOOK_TOKEN_FILE", tmp_path / "absent")
    assert cfg.resolve_hook_token() is None


def test_resolve_token_blank_env_falls_through_to_file(monkeypatch, tmp_path):
    (tmp_path / "hook_token").write_text("data-tok", encoding="utf-8")
    monkeypatch.setattr(
        cfg, "get_settings", lambda: _settings(tmp_path, hook_token="   ")
    )
    monkeypatch.setattr(cfg, "HOOK_TOKEN_FILE", tmp_path / "legacy_absent")
    assert cfg.resolve_hook_token() == "data-tok"


# ─────────────────── bootstrap / rotate / source ────────────────────


def test_bootstrap_generates_when_unset(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cfg, "get_settings", lambda: _settings(tmp_path, hook_token=None)
    )
    monkeypatch.setattr(cfg, "HOOK_TOKEN_FILE", tmp_path / "legacy_absent")
    token, created = cfg.bootstrap_hook_token()
    assert created is True and token
    data_file = tmp_path / "hook_token"
    assert data_file.read_text(encoding="utf-8").strip() == token
    assert (data_file.stat().st_mode & 0o777) == 0o600
    # Idempotent: a second call reuses the persisted token.
    token2, created2 = cfg.bootstrap_hook_token()
    assert created2 is False and token2 == token


def test_bootstrap_reuses_legacy_without_writing_data_dir(monkeypatch, tmp_path):
    # A pre-existing legacy token must NOT be shadowed by a new data-dir file.
    legacy = tmp_path / "legacy_hook_token"
    legacy.write_text("legacy-tok\n", encoding="utf-8")
    monkeypatch.setattr(
        cfg, "get_settings", lambda: _settings(tmp_path, hook_token=None)
    )
    monkeypatch.setattr(cfg, "HOOK_TOKEN_FILE", legacy)
    token, created = cfg.bootstrap_hook_token()
    assert created is False and token == "legacy-tok"
    assert not (tmp_path / "hook_token").exists()


def test_rotate_replaces_token(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cfg, "get_settings", lambda: _settings(tmp_path, hook_token=None)
    )
    monkeypatch.setattr(cfg, "HOOK_TOKEN_FILE", tmp_path / "legacy_absent")
    t1, _ = cfg.bootstrap_hook_token()
    t2 = cfg.rotate_hook_token()
    assert t2 != t1
    assert cfg.resolve_hook_token() == t2


def test_hook_token_source(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "HOOK_TOKEN_FILE", tmp_path / "legacy_absent")
    monkeypatch.setattr(
        cfg, "get_settings", lambda: _settings(tmp_path, hook_token="x")
    )
    assert cfg.hook_token_source() == "env"
    (tmp_path / "hook_token").write_text("d", encoding="utf-8")
    monkeypatch.setattr(
        cfg, "get_settings", lambda: _settings(tmp_path, hook_token=None)
    )
    assert cfg.hook_token_source() == "data_file"


# ───────────────────────── verify_hook_token ────────────────────────


def test_token_set_correct_bearer_passes(monkeypatch):
    _configure(monkeypatch, token="s3cret", host="0.0.0.0")
    # Should not raise even on a non-loopback bind when the token matches.
    assert mw.verify_hook_token(_request("Bearer s3cret")) is None


def test_token_set_wrong_bearer_rejected(monkeypatch):
    _configure(monkeypatch, token="s3cret", host="127.0.0.1")
    with pytest.raises(HTTPException) as exc:
        mw.verify_hook_token(_request("Bearer nope"))
    assert exc.value.status_code == 401


def test_token_set_missing_header_rejected(monkeypatch):
    _configure(monkeypatch, token="s3cret", host="127.0.0.1")
    with pytest.raises(HTTPException) as exc:
        mw.verify_hook_token(_request(None))
    assert exc.value.status_code == 401


def test_no_token_loopback_allows_no_warning(monkeypatch, caplog):
    # Backward-compat: local dev with no token configured still works, silently.
    _configure(monkeypatch, token=None, host="127.0.0.1")
    with caplog.at_level(logging.WARNING, logger="app.web.oauth.middleware"):
        assert mw.verify_hook_token(_request(None)) is None
    assert "WITHOUT a hook token" not in caplog.text


def test_no_token_non_loopback_allows_with_warning(monkeypatch, caplog):
    # Policy reversal (task a0b90505): an exposed server with no token now
    # ALLOWS the write (not 401) but logs a one-time prominent WARNING.
    _configure(monkeypatch, token=None, host="0.0.0.0")
    with caplog.at_level(logging.WARNING, logger="app.web.oauth.middleware"):
        assert mw.verify_hook_token(_request(None)) is None  # allowed, no raise
    assert "WITHOUT a hook token" in caplog.text
    assert "0.0.0.0" in caplog.text


def test_exposure_warning_is_one_time(monkeypatch, caplog):
    _configure(monkeypatch, token=None, host="0.0.0.0")
    with caplog.at_level(logging.WARNING, logger="app.web.oauth.middleware"):
        mw.verify_hook_token(_request(None))
        mw.verify_hook_token(_request(None))
        mw.verify_hook_token(_request(None))
    assert caplog.text.count("WITHOUT a hook token") == 1


def test_effective_host_override_not_static_setting(monkeypatch):
    # The effective bind host reflects a --host / MEM_MESH_SERVER_HOST override;
    # the static settings.server_host is never mutated.
    monkeypatch.setattr(
        cfg, "get_settings", lambda: SimpleNamespace(server_host="127.0.0.1")
    )
    monkeypatch.setattr(cfg, "_effective_bind_host", None)
    monkeypatch.delenv(cfg._EFFECTIVE_BIND_HOST_ENV, raising=False)

    # No override recorded → falls back to the static setting.
    assert cfg.get_effective_bind_host() == "127.0.0.1"

    # Server start records the real bind host.
    cfg.set_effective_bind_host("0.0.0.0")
    assert cfg.get_effective_bind_host() == "0.0.0.0"
    # Static setting is untouched.
    assert cfg.get_settings().server_host == "127.0.0.1"


def test_oauth_middleware_exempts_hook_paths(monkeypatch):
    # Hook paths must be skipped by the OAuth validator (own token scheme),
    # even when web auth is enabled, so a hook bearer is not double-validated.
    # _requires_auth now resolves flags through runtime_config (env > db >
    # default); stub them "on" to exercise the gating logic.
    import app.core.runtime_config as rc

    monkeypatch.setattr(rc, "effective_bool", lambda key: True)
    monkeypatch.setattr(rc, "effective_tribool", lambda key: True)
    middleware = mw.BearerTokenMiddleware(app=lambda *a, **k: None)
    assert middleware._requires_auth("/api/hooks/claude/stop") is False
    # A normal API path is still gated.
    assert middleware._requires_auth("/api/memories") is True


def test_router_has_token_dependency():
    # Wiring check: the hooks router carries verify_hook_token as a dependency.
    from app.web.dashboard.route_modules.hooks import router

    dep_calls = [d.dependency for d in router.dependencies]
    assert mw.verify_hook_token in dep_calls
