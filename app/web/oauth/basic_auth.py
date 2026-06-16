"""Basic Authentication Middleware for Web Dashboard.

Provides simple username/password authentication for browser access.
Uses SQLite-backed session store for persistence across restarts and workers.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "mem_mesh_session"
SESSION_TTL_HOURS = 24


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStore:
    """SQLite-backed session store.

    Falls back to in-memory dict when no database is available
    (e.g. during startup before lifespan completes).
    """

    def __init__(self):
        self._db = None
        self._memory: dict[str, dict] = {}
        self._table_ready = False

    def set_database(self, db) -> None:
        """Attach a Database instance (called from lifespan)."""
        self._db = db

    async def _ensure_table(self) -> None:
        if self._table_ready or self._db is None:
            return
        try:
            await self._db.execute("""
                CREATE TABLE IF NOT EXISTS web_sessions (
                    session_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            self._db.connection.commit()
            self._table_ready = True
        except Exception as e:
            logger.warning(f"Failed to create web_sessions table: {e}")

    async def create(self, username: str) -> str:
        session_id = secrets.token_urlsafe(32)
        now = _utc_now()
        expires = now + timedelta(hours=SESSION_TTL_HOURS)

        if self._db is not None:
            await self._ensure_table()
            try:
                await self._db.execute(
                    "INSERT INTO web_sessions (session_id, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
                    (session_id, username, now.isoformat(), expires.isoformat()),
                )
                self._db.connection.commit()
                return session_id
            except Exception as e:
                logger.warning(f"SQLite session create failed, using memory: {e}")

        self._memory[session_id] = {
            "username": username,
            "created_at": now,
            "expires_at": expires,
        }
        return session_id

    async def validate(self, session_id: str) -> Optional[dict]:
        if not session_id:
            return None

        if self._db is not None:
            await self._ensure_table()
            try:
                row = await self._db.fetchone(
                    "SELECT username, expires_at FROM web_sessions WHERE session_id = ?",
                    (session_id,),
                )
                if row:
                    expires_at = datetime.fromisoformat(row["expires_at"])
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)
                    if _utc_now() > expires_at:
                        await self.delete(session_id)
                        return None
                    return {"username": row["username"]}
                return None
            except Exception as e:
                logger.warning(f"SQLite session validate failed, checking memory: {e}")

        session = self._memory.get(session_id)
        if session is None:
            return None
        if _utc_now() > session["expires_at"]:
            del self._memory[session_id]
            return None
        return {"username": session["username"]}

    async def delete(self, session_id: str) -> None:
        if self._db is not None:
            try:
                await self._db.execute(
                    "DELETE FROM web_sessions WHERE session_id = ?",
                    (session_id,),
                )
                self._db.connection.commit()
            except Exception as e:
                logger.warning(f"SQLite session delete failed: {e}")

        self._memory.pop(session_id, None)

    async def cleanup_expired(self) -> int:
        """Remove expired sessions. Returns count of removed sessions."""
        removed = 0
        if self._db is not None:
            await self._ensure_table()
            try:
                result = await self._db.execute(
                    "DELETE FROM web_sessions WHERE expires_at < ?",
                    (_utc_now().isoformat(),),
                )
                self._db.connection.commit()
                removed = result.rowcount if hasattr(result, "rowcount") else 0
            except Exception as e:
                logger.debug(f"Failed to remove expired DB sessions: {e}")

        expired_keys = [
            k for k, v in self._memory.items() if _utc_now() > v["expires_at"]
        ]
        for k in expired_keys:
            del self._memory[k]
        removed += len(expired_keys)
        return removed


# Global session store instance
session_store = SessionStore()


async def create_session(username: str) -> str:
    """Create a new session and return session ID."""
    return await session_store.create(username)


async def validate_session(session_id: str) -> Optional[dict]:
    """Validate session and return session data if valid."""
    return await session_store.validate(session_id)


async def delete_session(session_id: str) -> None:
    """Delete a session."""
    await session_store.delete(session_id)


def verify_credentials(username: str, password: str) -> bool:
    """Verify username/password against the active source (env or dashboard DB).

    The password may be an env-provided plaintext or a dashboard-set hash;
    :func:`check_admin_password` handles both.
    """
    from app.core.runtime_config import (
        admin_password_set,
        check_admin_password,
        effective,
    )

    if not admin_password_set():
        logger.warning("Basic auth enabled but no admin password set")
        return False

    uname, _ = effective("admin_username")
    username_match = secrets.compare_digest(str(username), str(uname or "admin"))
    password_match = check_admin_password(password)

    return username_match and password_match


LOGIN_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login · mem-mesh</title>
    <script>
      // Apply the dashboard theme before paint (no FOUC). Mirrors theme-manager:
      // localStorage 'mem-mesh-theme' = light | dark | system.
      (function () {
        try {
          var t = localStorage.getItem('mem-mesh-theme') || 'system';
          var dark = t === 'dark' || (t === 'system' &&
            window.matchMedia('(prefers-color-scheme: dark)').matches);
          document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
        } catch (e) {}
      })();
    </script>
    <link rel="stylesheet" href="/static/css/main.css">
    <style>
        body {
            min-height: 100vh;
            margin: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 1.5rem;
            background: var(--bg-secondary, #fafafa);
            font-family: var(--font-body, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif);
            color: var(--text-primary, #171717);
        }
        .login-card {
            width: 100%;
            max-width: 380px;
            background: var(--card-bg, #ffffff);
            border: 1px solid var(--border-color, #e5e5e5);
            border-radius: 16px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05), 0 12px 32px rgba(0, 0, 0, 0.05);
            padding: 2.5rem 2rem;
            box-sizing: border-box;
        }
        .login-brand { text-align: center; margin-bottom: 2rem; }
        .login-brand .mark {
            display: inline-flex; align-items: center; gap: 0.55rem;
            font-size: 1.5rem; font-weight: 700; letter-spacing: -0.02em;
            color: var(--text-primary, #171717);
        }
        .login-brand .mark svg { width: 26px; height: 26px; color: var(--text-primary, #171717); }
        .login-brand p { margin: 0.5rem 0 0; font-size: 0.85rem; color: var(--text-secondary, #525252); }
        .login-form { display: flex; flex-direction: column; gap: 1.1rem; }
        .login-field label {
            display: block; margin-bottom: 0.4rem;
            font-size: 0.82rem; font-weight: 500; color: var(--text-secondary, #525252);
        }
        .login-field input {
            width: 100%; box-sizing: border-box;
            padding: 0.7rem 0.85rem;
            border: 1px solid var(--border-color, #e5e5e5);
            border-radius: 10px;
            background: var(--bg-primary, #ffffff);
            color: var(--text-primary, #171717);
            font-size: 0.95rem;
            transition: border-color 0.15s, box-shadow 0.15s;
        }
        .login-field input:focus {
            outline: none;
            border-color: var(--text-primary, #171717);
            box-shadow: 0 0 0 3px rgba(115, 115, 115, 0.14);
        }
        .login-btn {
            margin-top: 0.4rem;
            width: 100%; padding: 0.8rem;
            background: var(--text-primary, #171717);
            color: var(--bg-primary, #ffffff);
            border: none; border-radius: 10px;
            font-size: 0.95rem; font-weight: 600; cursor: pointer;
            transition: opacity 0.15s, transform 0.1s;
        }
        .login-btn:hover { opacity: 0.9; }
        .login-btn:active { transform: translateY(1px); }
        .error-message {
            background: var(--error-bg, #fef2f2);
            color: var(--error-color, #dc2626);
            border: 1px solid rgba(239, 68, 68, 0.22);
            padding: 0.7rem 0.85rem; border-radius: 10px;
            font-size: 0.85rem; margin-bottom: 1.25rem;
        }
    </style>
</head>
<body>
    <main class="login-card">
        <div class="login-brand">
            <span class="mark">
                <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <path d="M16 4L4 10L16 16L28 10L16 4Z" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>
                    <path d="M4 22L16 28L28 22" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>
                    <path d="M4 16L16 22L28 16" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>
                </svg>
                mem-mesh
            </span>
            <p>AI Memory Management</p>
        </div>
        {error_html}
        <form class="login-form" method="POST" action="/login?next={next}">
            <div class="login-field">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required autofocus autocomplete="username">
            </div>
            <div class="login-field">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required autocomplete="current-password">
            </div>
            <button type="submit" class="login-btn">Sign in</button>
        </form>
    </main>
</body>
</html>
"""


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Middleware for Basic Auth with session cookies."""

    PUBLIC_PATHS = [
        "/health",
        "/static",
        "/favicon.ico",
        "/login",
        "/logout",
        "/docs",
        "/redoc",
        "/openapi.json",
    ]

    # Surfaces that carry their OWN auth scheme (OAuth bearer / hook token) or
    # are not browser pages. Basic Auth gates dashboard *pages* only — gating
    # these would lock out API / MCP / hook clients that have no dashboard
    # session cookie (Claude Code hooks authenticate with MEM_MESH_HOOK_TOKEN;
    # MCP and the REST API via OAuth bearer). Their own middleware
    # (BearerTokenMiddleware / verify_hook_token) enforces auth independently —
    # configure it with MEM_MESH_WEB_AUTH_ENABLED / MEM_MESH_MCP_AUTH_ENABLED.
    EXEMPT_PATHS = [
        "/.well-known/",
        "/oauth/",
        "/mcp/",
        "/api/",
    ]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        from app.core.runtime_config import effective_bool

        path = request.url.path

        # Resolve env > db(dashboard) > default so a dashboard toggle applies
        # without a restart.
        if not effective_bool("web_basic_auth_enabled"):
            return await call_next(request)

        if self._is_public_path(path):
            return await call_next(request)

        # Resolve a dashboard session once and reuse it for both the page gate
        # and the API exemption. Attaching it to request.state lets
        # BearerTokenMiddleware accept the browser SPA's /api calls (which carry
        # only the session cookie, no OAuth bearer).
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session = await validate_session(session_id) if session_id else None
        if session:
            request.state.auth_user = session["username"]
            request.state.dashboard_session = session["username"]

        # /api, /mcp, /oauth carry their own auth — never redirect them to login.
        # The session (if any) was attached above for the /api dual-auth path.
        if self._is_exempt_path(path):
            return await call_next(request)

        # Dashboard pages require a valid session.
        if session:
            return await call_next(request)

        return RedirectResponse(url=f"/login?next={path}", status_code=302)

    def _is_public_path(self, path: str) -> bool:
        for public_path in self.PUBLIC_PATHS:
            if path == public_path or path.startswith(public_path):
                return True
        return False

    def _is_exempt_path(self, path: str) -> bool:
        for prefix in self.EXEMPT_PATHS:
            if path.startswith(prefix):
                return True
        return False
