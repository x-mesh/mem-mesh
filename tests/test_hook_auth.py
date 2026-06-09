"""Unit tests for hook endpoint authentication (P1 #1 server-side fix).

Covers:
* ``is_loopback_host`` classification
* ``resolve_hook_token`` env-first / file-fallback / none
* ``verify_hook_token`` dependency: token match, fail-closed on non-loopback,
  loopback backward-compat
"""

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
    monkeypatch.setattr(mw, "resolve_hook_token", lambda: token)
    monkeypatch.setattr(mw, "get_settings", lambda: SimpleNamespace(server_host=host))


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


def test_resolve_token_env_first(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "get_settings", lambda: SimpleNamespace(hook_token="env-tok"))
    monkeypatch.setattr(cfg, "HOOK_TOKEN_FILE", tmp_path / "hook_token")
    assert cfg.resolve_hook_token() == "env-tok"


def test_resolve_token_file_fallback(monkeypatch, tmp_path):
    f = tmp_path / "hook_token"
    f.write_text("file-tok\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "get_settings", lambda: SimpleNamespace(hook_token=None))
    monkeypatch.setattr(cfg, "HOOK_TOKEN_FILE", f)
    assert cfg.resolve_hook_token() == "file-tok"


def test_resolve_token_none_when_unset(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "get_settings", lambda: SimpleNamespace(hook_token=None))
    monkeypatch.setattr(cfg, "HOOK_TOKEN_FILE", tmp_path / "absent")
    assert cfg.resolve_hook_token() is None


def test_resolve_token_blank_env_falls_through_to_file(monkeypatch, tmp_path):
    f = tmp_path / "hook_token"
    f.write_text("file-tok", encoding="utf-8")
    monkeypatch.setattr(cfg, "get_settings", lambda: SimpleNamespace(hook_token="   "))
    monkeypatch.setattr(cfg, "HOOK_TOKEN_FILE", f)
    assert cfg.resolve_hook_token() == "file-tok"


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


def test_no_token_loopback_passes(monkeypatch):
    # Backward-compat: local dev with no token configured still works.
    _configure(monkeypatch, token=None, host="127.0.0.1")
    assert mw.verify_hook_token(_request(None)) is None


def test_no_token_non_loopback_fails_closed(monkeypatch):
    # The core P1 fix: an exposed server with no token rejects anonymous writes.
    _configure(monkeypatch, token=None, host="0.0.0.0")
    with pytest.raises(HTTPException) as exc:
        mw.verify_hook_token(_request(None))
    assert exc.value.status_code == 401


def test_oauth_middleware_exempts_hook_paths(monkeypatch):
    # Hook paths must be skipped by the OAuth validator (own token scheme),
    # even when web auth is enabled, so a hook bearer is not double-validated.
    settings = SimpleNamespace(
        auth_enabled=True, web_auth_enabled=True, mcp_auth_enabled=True
    )
    middleware = mw.BearerTokenMiddleware(app=lambda *a, **k: None)
    assert middleware._requires_auth("/api/hooks/claude/stop", settings) is False
    # A normal API path is still gated.
    assert middleware._requires_auth("/api/memories", settings) is True


def test_router_has_token_dependency():
    # Wiring check: the hooks router carries verify_hook_token as a dependency.
    from app.web.dashboard.route_modules.hooks import router

    dep_calls = [d.dependency for d in router.dependencies]
    assert mw.verify_hook_token in dep_calls
