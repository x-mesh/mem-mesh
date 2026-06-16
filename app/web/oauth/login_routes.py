"""Login/Logout routes for Basic Auth."""

import html as html_lib
import logging
from typing import Optional

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .basic_auth import (
    LOGIN_PAGE_HTML,
    SESSION_COOKIE_NAME,
    create_session,
    delete_session,
    verify_credentials,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Authentication"])


def _safe_next(next_url: Optional[str]) -> str:
    """Restrict post-login redirects to local paths (no open redirect).

    Accepts only an absolute in-app path (``/...``); rejects scheme-relative
    (``//host``) and absolute URLs, falling back to ``/``.
    """
    if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    return next_url


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: Optional[str] = Query(default=None),
    next: Optional[str] = Query(default="/"),
):
    """Display login page."""
    from app.core.runtime_config import effective_bool

    # If basic auth is not enabled, redirect to home. MUST use the same resolver
    # as BasicAuthMiddleware (env > db > default) — reading
    # settings.web_basic_auth_enabled directly would disagree with a DB-enabled
    # toggle and ping-pong / <-> /login forever.
    if not effective_bool("web_basic_auth_enabled"):
        return RedirectResponse(url="/", status_code=302)

    safe_next = _safe_next(next)

    # If already logged in, redirect to next
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        from .basic_auth import validate_session

        if await validate_session(session_id):
            return RedirectResponse(url=safe_next, status_code=302)

    # Show login page (escape both error text and the next value for their
    # respective HTML contexts).
    error_html = ""
    if error:
        error_html = f'<div class="error-message">{html_lib.escape(error)}</div>'

    html = LOGIN_PAGE_HTML.replace("{error_html}", error_html).replace(
        "{next}", html_lib.escape(safe_next, quote=True)
    )
    return HTMLResponse(content=html)


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Query(default="/"),
):
    """Process login form submission."""
    from app.core.runtime_config import effective_bool

    if not effective_bool("web_basic_auth_enabled"):
        return RedirectResponse(url="/", status_code=302)

    from urllib.parse import quote

    safe_next = _safe_next(next)

    # Verify credentials
    if not verify_credentials(username, password):
        logger.warning(f"Failed login attempt for user: {username}")
        return RedirectResponse(
            url=f"/login?error=Invalid+username+or+password&next={quote(safe_next)}",
            status_code=302,
        )

    # Create session
    session_id = await create_session(username)
    logger.info(f"User logged in: {username}")

    # Redirect to next page with session cookie
    response = RedirectResponse(url=safe_next, status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=86400,  # 24 hours
    )
    return response


@router.get("/logout")
async def logout(request: Request):
    """Log out and clear session."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)

    if session_id:
        await delete_session(session_id)
        logger.info("User logged out")

    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return response
