"""First-run setup routes — configure dashboard auth via a one-time token.

Available only while NO dashboard auth is configured: the lifespan startup mints
a setup token and prints it to the server console. Submitting that token here
sets the admin credentials, turns Basic Auth on, consumes the token, and logs
the operator straight in — so onboarding happens in the browser without shell
access, yet a network-exposed unconfigured server can't be hijacked (only the
console/data-dir reader ever sees the token).
"""

import html as html_lib
import logging
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import clear_setup_token, read_setup_token, verify_setup_token

from .basic_auth import SESSION_COOKIE_NAME, create_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Setup"])

# Minimum admin password length accepted by the setup form. Kept conservative;
# the loopback/console-token gate is the real protection, this just avoids an
# obviously trivial password during onboarding.
MIN_PASSWORD_LEN = 8


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, error: Optional[str] = Query(default=None)):
    """Render the first-run setup form, or redirect home if nothing to set up."""
    # No pending token → auth already configured (or token consumed). Nothing to
    # do here; send the operator to the dashboard / login.
    if read_setup_token() is None:
        return RedirectResponse(url="/", status_code=302)

    error_html = ""
    if error:
        error_html = f'<div class="error-message">{html_lib.escape(error)}</div>'
    html = SETUP_PAGE_HTML.replace("{error_html}", error_html)
    return HTMLResponse(content=html)


@router.post("/setup")
async def setup_submit(
    request: Request,
    setup_token: str = Form(...),
    username: str = Form("admin"),
    password: str = Form(...),
    password_confirm: str = Form(""),
):
    """Validate the setup token and persist the initial dashboard auth config."""

    def _err(msg: str):
        return RedirectResponse(url=f"/setup?error={quote(msg)}", status_code=302)

    # Token already consumed (someone finished setup first) → refuse and bounce.
    # Combined with constant-time verify below, this closes the first-run race:
    # the first valid submit wins and the window shuts.
    if read_setup_token() is None:
        return RedirectResponse(url="/", status_code=302)
    if not verify_setup_token(setup_token):
        logger.warning("Invalid first-run setup token submitted")
        return _err("Invalid setup token")

    uname = (username or "admin").strip() or "admin"
    if len(uname) > 64 or any(ord(c) < 32 for c in uname):
        return _err("Invalid username")
    if len(password) < MIN_PASSWORD_LEN:
        return _err(f"Password must be at least {MIN_PASSWORD_LEN} characters")
    if password_confirm and password_confirm != password:
        return _err("Passwords do not match")

    db = getattr(request.app.state, "db", None)
    if db is None:
        return _err("Server not ready")

    from app.core import runtime_config as rc

    # Order matters: set the password BEFORE enabling Basic Auth so there is
    # never a window where auth is on without a credential.
    try:
        await rc.set_override(db, "admin_username", uname)
        await rc.set_override(db, "admin_password", password)
        await rc.set_override(db, "web_basic_auth_enabled", True)
    except PermissionError:
        # An env var pins one of these keys — it can't be overridden from here.
        # (Shouldn't happen: a token is only minted when nothing is configured.)
        return _err("Auth is configured via environment; setup is disabled")
    except Exception as e:  # pragma: no cover - defensive
        logger.error("Setup failed to persist auth config: %s", e)
        return _err("Could not save configuration")

    # Consume the token: the page closes and the same token cannot be reused.
    clear_setup_token()
    logger.info("First-run setup completed; Basic Auth enabled (user=%s)", uname)

    # Log the operator straight in so they land on the dashboard, not /login.
    session_id = await create_session(uname)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=86400,  # 24 hours
    )
    return response


SETUP_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Setup · mem-mesh</title>
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
        .login-brand { text-align: center; margin-bottom: 1.5rem; }
        .login-brand .mark {
            display: inline-flex; align-items: center; gap: 0.55rem;
            font-size: 1.5rem; font-weight: 700; letter-spacing: -0.02em;
            color: var(--text-primary, #171717);
        }
        .login-brand .mark svg { width: 26px; height: 26px; color: var(--text-primary, #171717); }
        .login-brand p { margin: 0.5rem 0 0; font-size: 0.85rem; color: var(--text-secondary, #525252); }
        .setup-hint {
            font-size: 0.8rem; color: var(--text-secondary, #525252);
            background: var(--bg-secondary, #fafafa);
            border: 1px solid var(--border-color, #e5e5e5);
            border-radius: 10px; padding: 0.7rem 0.85rem; margin-bottom: 1.25rem;
            line-height: 1.45;
        }
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
            <p>First-run setup</p>
        </div>
        <div class="setup-hint">
            Paste the <strong>setup token</strong> printed on the server console,
            then choose an admin username and password to secure the dashboard.
        </div>
        {error_html}
        <form class="login-form" method="POST" action="/setup">
            <div class="login-field">
                <label for="setup_token">Setup token</label>
                <input type="text" id="setup_token" name="setup_token" required autofocus autocomplete="off" spellcheck="false">
            </div>
            <div class="login-field">
                <label for="username">Admin username</label>
                <input type="text" id="username" name="username" value="admin" required autocomplete="username">
            </div>
            <div class="login-field">
                <label for="password">Admin password</label>
                <input type="password" id="password" name="password" required autocomplete="new-password">
            </div>
            <div class="login-field">
                <label for="password_confirm">Confirm password</label>
                <input type="password" id="password_confirm" name="password_confirm" required autocomplete="new-password">
            </div>
            <button type="submit" class="login-btn">Complete setup</button>
        </form>
    </main>
</body>
</html>
"""
