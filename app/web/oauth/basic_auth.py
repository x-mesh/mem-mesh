"""Basic Authentication Middleware for Web Dashboard.

Provides simple username/password authentication for browser access.
Uses session cookies to maintain login state.
"""

import secrets
import hashlib
import logging
from typing import Optional, Callable, Dict
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# In-memory session store (for simplicity; use Redis in production)
_sessions: Dict[str, dict] = {}
SESSION_COOKIE_NAME = "mem_mesh_session"
SESSION_TTL_HOURS = 24


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_session(username: str) -> str:
    """Create a new session and return session ID."""
    session_id = secrets.token_urlsafe(32)
    _sessions[session_id] = {
        "username": username,
        "created_at": _utc_now(),
        "expires_at": _utc_now() + timedelta(hours=SESSION_TTL_HOURS),
    }
    return session_id


def validate_session(session_id: str) -> Optional[dict]:
    """Validate session and return session data if valid."""
    if not session_id or session_id not in _sessions:
        return None
    
    session = _sessions[session_id]
    if _utc_now() > session["expires_at"]:
        del _sessions[session_id]
        return None
    
    return session


def delete_session(session_id: str) -> None:
    """Delete a session."""
    if session_id in _sessions:
        del _sessions[session_id]


def verify_credentials(username: str, password: str) -> bool:
    """Verify username and password against settings."""
    settings = get_settings()
    
    if not settings.admin_password:
        logger.warning("Basic auth enabled but no admin password set")
        return False
    
    # Constant-time comparison to prevent timing attacks
    username_match = secrets.compare_digest(username, settings.admin_username)
    password_match = secrets.compare_digest(password, settings.admin_password)
    
    return username_match and password_match


# Login page HTML template
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
        .logo {
            text-align: center;
            margin-bottom: 2rem;
        }
        .logo h1 {
            font-size: 2rem;
            color: #1a1a2e;
            margin-bottom: 0.5rem;
        }
        .logo p {
            color: #666;
            font-size: 0.9rem;
        }
        .form-group {
            margin-bottom: 1.5rem;
        }
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 500;
            color: #333;
        }
        .form-group input {
            width: 100%;
            padding: 0.75rem 1rem;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 1rem;
            transition: border-color 0.2s;
        }
        .form-group input:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn-login {
            width: 100%;
            padding: 0.875rem;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .btn-login:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3);
        }
        .error-message {
            background: #fee2e2;
            color: #dc2626;
            padding: 0.75rem 1rem;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            font-size: 0.9rem;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">
            <h1>🧠 mem-mesh</h1>
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

    # Paths that don't require authentication
    PUBLIC_PATHS = [
        "/health",
        "/static",
        "/favicon.ico",
        "/login",
        "/logout",
    ]
    
    # Paths that use OAuth instead of Basic Auth
    OAUTH_PATHS = [
        "/.well-known/oauth-authorization-server",
        "/oauth/",
        "/mcp/",
    ]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_settings()
        path = request.url.path

        # Skip if basic auth is not enabled
        if not settings.web_basic_auth_enabled:
            return await call_next(request)

        # Skip public paths
        if self._is_public_path(path):
            return await call_next(request)

        # Skip OAuth/MCP paths (handled by BearerTokenMiddleware)
        if self._is_oauth_path(path):
            return await call_next(request)

        # Check session cookie
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session = validate_session(session_id) if session_id else None

        if session:
            # Valid session - allow request
            request.state.auth_user = session["username"]
            return await call_next(request)

        # No valid session - redirect to login
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
