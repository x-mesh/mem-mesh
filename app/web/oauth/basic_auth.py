"""Basic Authentication Middleware for Web Dashboard.

Provides simple username/password authentication for browser access.
Uses SQLite-backed session store for persistence across restarts and workers.
"""

import secrets
import logging
from typing import Optional, Callable
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings

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
                row = await self._db.fetch_one(
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
            except Exception:
                pass

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
    """Verify username and password against settings."""
    settings = get_settings()

    if not settings.admin_password:
        logger.warning("Basic auth enabled but no admin password set")
        return False

    username_match = secrets.compare_digest(username, settings.admin_username)
    password_match = secrets.compare_digest(password, settings.admin_password)

    return username_match and password_match


LOGIN_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - mem-mesh</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .login-container {
            background: white;
            padding: 2.5rem;
            border-radius: 16px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
            width: 100%;
            max-width: 400px;
        }
        .logo { text-align: center; margin-bottom: 2rem; }
        .logo h1 { font-size: 2rem; color: #1a1a2e; margin-bottom: 0.5rem; }
        .logo p { color: #666; font-size: 0.9rem; }
        .form-group { margin-bottom: 1.5rem; }
        .form-group label { display: block; margin-bottom: 0.5rem; font-weight: 500; color: #333; }
        .form-group input {
            width: 100%; padding: 0.75rem 1rem;
            border: 2px solid #e0e0e0; border-radius: 8px; font-size: 1rem;
            transition: border-color 0.2s;
        }
        .form-group input:focus { outline: none; border-color: #667eea; }
        .btn-login {
            width: 100%; padding: 0.875rem;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; border: none; border-radius: 8px;
            font-size: 1rem; font-weight: 600; cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .btn-login:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3); }
        .error-message {
            background: #fee2e2; color: #dc2626;
            padding: 0.75rem 1rem; border-radius: 8px;
            margin-bottom: 1.5rem; font-size: 0.9rem;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">
            <h1>mem-mesh</h1>
            <p>AI Memory Management System</p>
        </div>
        {error_html}
        <form method="POST" action="/login">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required autofocus>
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required>
            </div>
            <button type="submit" class="btn-login">Sign In</button>
        </form>
    </div>
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
    ]

    OAUTH_PATHS = [
        "/.well-known/oauth-authorization-server",
        "/oauth/",
        "/mcp/",
    ]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_settings()
        path = request.url.path

        if not settings.web_basic_auth_enabled:
            return await call_next(request)

        if self._is_public_path(path):
            return await call_next(request)

        if self._is_oauth_path(path):
            return await call_next(request)

        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session = await validate_session(session_id) if session_id else None

        if session:
            request.state.auth_user = session["username"]
            return await call_next(request)

        return RedirectResponse(url=f"/login?next={path}", status_code=302)

    def _is_public_path(self, path: str) -> bool:
        for public_path in self.PUBLIC_PATHS:
            if path == public_path or path.startswith(public_path):
                return True
        return False

    def _is_oauth_path(self, path: str) -> bool:
        for oauth_path in self.OAUTH_PATHS:
            if path.startswith(oauth_path):
                return True
        return False
