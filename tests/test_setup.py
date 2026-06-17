"""Tests for the first-run setup token flow.

Covers:
* the setup-token infra in ``app.core.config`` (mint / read / verify / consume,
  idempotency)
* the ``/setup`` routes: redirect when nothing to configure, form when a token
  is pending, invalid-token refusal, and the happy path (config persisted,
  token consumed, session issued, reuse refused).
"""

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from httpx import ASGITransport, AsyncClient

import app.core.config as cfg
from app.core import runtime_config as rc
from app.web.oauth.basic_auth import SESSION_COOKIE_NAME, BasicAuthMiddleware


@pytest.fixture
def setup_token_file(tmp_path, monkeypatch):
    """Pin the setup-token file to a temp path and start with none present."""
    token_path = tmp_path / "setup_token"
    monkeypatch.setattr(cfg, "_data_dir_setup_token_file", lambda: token_path)
    return token_path


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Isolate the global runtime-config override cache between tests."""
    rc._overrides.clear()
    yield
    rc._overrides.clear()


@pytest.fixture(autouse=True)
def _no_auth_env(monkeypatch):
    """Ensure auth keys aren't env-pinned so set_override is allowed."""
    for key in (
        "MEM_MESH_WEB_BASIC_AUTH_ENABLED",
        "MEM_MESH_ADMIN_USERNAME",
        "MEM_MESH_ADMIN_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)


# ───────────────────────── token infra (unit) ─────────────────────────


class TestSetupTokenInfra:
    def test_none_initially(self, setup_token_file):
        assert cfg.read_setup_token() is None
        # verify against a non-existent token is always False
        assert cfg.verify_setup_token("anything") is False

    def test_ensure_creates_and_persists(self, setup_token_file):
        token = cfg.ensure_setup_token()
        assert token
        assert setup_token_file.exists()
        assert cfg.read_setup_token() == token

    def test_ensure_is_idempotent(self, setup_token_file):
        first = cfg.ensure_setup_token()
        second = cfg.ensure_setup_token()
        assert first == second

    def test_verify_constant_time_match(self, setup_token_file):
        token = cfg.ensure_setup_token()
        assert cfg.verify_setup_token(token) is True
        assert cfg.verify_setup_token("wrong") is False
        assert cfg.verify_setup_token("") is False

    def test_clear_consumes_token(self, setup_token_file):
        token = cfg.ensure_setup_token()
        cfg.clear_setup_token()
        assert cfg.read_setup_token() is None
        assert cfg.verify_setup_token(token) is False

    def test_clear_is_idempotent(self, setup_token_file):
        cfg.clear_setup_token()  # nothing present — must not raise
        cfg.clear_setup_token()


# ───────────────────────── /setup routes (integration) ─────────────────────────


def _make_app(db):
    from app.web.oauth.setup_routes import router

    app = FastAPI()
    app.include_router(router)
    app.state.db = db
    return app


async def _client(db):
    transport = ASGITransport(app=_make_app(db))
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_get_setup_redirects_when_no_token(temp_db, setup_token_file):
    async with await _client(temp_db) as ac:
        r = await ac.get("/setup", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/"


@pytest.mark.asyncio
async def test_get_setup_shows_form_with_pending_token(temp_db, setup_token_file):
    cfg.ensure_setup_token()
    async with await _client(temp_db) as ac:
        r = await ac.get("/setup", follow_redirects=False)
    assert r.status_code == 200
    assert "Setup token" in r.text


@pytest.mark.asyncio
async def test_post_setup_rejects_invalid_token(temp_db, setup_token_file):
    cfg.ensure_setup_token()
    async with await _client(temp_db) as ac:
        r = await ac.post(
            "/setup",
            data={"setup_token": "bogus", "password": "longpassword"},
            follow_redirects=False,
        )
    assert r.status_code == 302
    assert "/setup?error=" in r.headers["location"]
    # token NOT consumed by a failed attempt
    assert cfg.read_setup_token() is not None


@pytest.mark.asyncio
async def test_post_setup_rejects_short_password(temp_db, setup_token_file):
    token = cfg.ensure_setup_token()
    async with await _client(temp_db) as ac:
        r = await ac.post(
            "/setup",
            data={"setup_token": token, "password": "short"},
            follow_redirects=False,
        )
    assert r.status_code == 302
    assert "/setup?error=" in r.headers["location"]
    assert cfg.read_setup_token() is not None


@pytest.mark.asyncio
async def test_post_setup_happy_path(temp_db, setup_token_file):
    token = cfg.ensure_setup_token()
    async with await _client(temp_db) as ac:
        r = await ac.post(
            "/setup",
            data={
                "setup_token": token,
                "username": "admin",
                "password": "longpassword",
                "password_confirm": "longpassword",
            },
            follow_redirects=False,
        )
    # logged straight in, landed on dashboard
    assert r.status_code == 302
    assert r.headers["location"] == "/"
    assert SESSION_COOKIE_NAME in r.headers.get("set-cookie", "")
    # token consumed; cannot be reused
    assert cfg.read_setup_token() is None
    # auth now configured via DB override
    assert rc.effective_bool("web_basic_auth_enabled") is True
    assert rc.admin_password_set() is True


@pytest.mark.asyncio
async def test_post_setup_refuses_reuse_after_consumed(temp_db, setup_token_file):
    token = cfg.ensure_setup_token()
    cfg.clear_setup_token()  # simulate already-completed setup
    async with await _client(temp_db) as ac:
        r = await ac.post(
            "/setup",
            data={"setup_token": token, "password": "longpassword"},
            follow_redirects=False,
        )
    assert r.status_code == 302
    assert r.headers["location"] == "/"


# ─────────────── first-run redirect middleware (integration) ───────────────


def _app_with_middleware(db):
    from app.web.oauth.setup_routes import router

    app = FastAPI()
    app.add_middleware(BasicAuthMiddleware)
    app.include_router(router)

    @app.get("/")
    async def _root():
        return HTMLResponse("<html>dashboard</html>")

    app.state.db = db
    return app


@pytest.mark.asyncio
async def test_page_redirects_to_setup_when_token_pending(temp_db, setup_token_file):
    cfg.ensure_setup_token()
    transport = ASGITransport(app=_app_with_middleware(temp_db))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/setup"


@pytest.mark.asyncio
async def test_page_not_redirected_when_no_token(temp_db, setup_token_file):
    # No pending token (auth configured / already onboarded) → normal page.
    transport = ASGITransport(app=_app_with_middleware(temp_db))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_setup_page_itself_not_redirected(temp_db, setup_token_file):
    cfg.ensure_setup_token()
    transport = ASGITransport(app=_app_with_middleware(temp_db))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            "/setup", headers={"accept": "text/html"}, follow_redirects=False
        )
    assert r.status_code == 200
    assert "Setup token" in r.text


@pytest.mark.asyncio
async def test_non_html_request_not_redirected(temp_db, setup_token_file):
    # A fetch/XHR (no text/html Accept) is not a navigation — must pass through.
    cfg.ensure_setup_token()
    transport = ASGITransport(app=_app_with_middleware(temp_db))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            "/", headers={"accept": "application/json"}, follow_redirects=False
        )
    assert r.status_code == 200
