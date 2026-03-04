"""Login/Logout routes for Basic Auth."""

import logging
from typing import Optional

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import get_settings

from .basic_auth import (
    LOGIN_PAGE_HTML,
    SESSION_COOKIE_NAME,
    create_session,
    delete_session,
    verify_credentials,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Authentication"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: Optional[str] = Query(default=None),
    next: Optional[str] = Query(default="/"),
):
    """Display login page."""
    settings = get_settings()

    # If basic auth is not enabled, redirect to home
    if not settings.web_basic_auth_enabled:
        return RedirectResponse(url="/", status_code=302)

    # If already logged in, redirect to next
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        from .basic_auth import validate_session

        if await validate_session(session_id):
            return RedirectResponse(url=next, status_code=302)

    # Show login page
    error_html = ""
    if error:
        error_html = f'<div class="error-message">{error}</div>'

    html = LOGIN_PAGE_HTML.replace("{error_html}", error_html)
    return HTMLResponse(content=html)


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Query(default="/"),
):
    """Process login form submission."""
    settings = get_settings()

    if not settings.web_basic_auth_enabled:
        return RedirectResponse(url="/", status_code=302)

    # Verify credentials
    if not verify_credentials(username, password):
        logger.warning(f"Failed login attempt for user: {username}")
        return RedirectResponse(
            url=f"/login?error=Invalid+username+or+password&next={next}",
            status_code=302,
        )

    # Create session
    session_id = await create_session(username)
    logger.info(f"User logged in: {username}")

    # Redirect to next page with session cookie
    response = RedirectResponse(url=next, status_code=302)
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
