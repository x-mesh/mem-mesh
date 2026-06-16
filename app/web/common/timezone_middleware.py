"""Response middleware that localizes UTC timestamps to ``display_timezone``.

JSON responses under ``/api/`` are post-processed so timestamps in the body
match the configured display timezone (env > dashboard DB > default UTC).

* **No-op on UTC** — the default short-circuits before the body is read, so a
  UTC deployment pays nothing.
* **MCP excluded** — ``/mcp/*`` responses are localized at their own boundary
  (``mcp_common.transport.format_tool_response``); this middleware only covers
  the Web/REST API to avoid double work.
* Best-effort: any parse/serialize failure leaves the body untouched.
"""

import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.utils.time import get_display_tz, localize_timestamps


class DisplayTimezoneMiddleware(BaseHTTPMiddleware):
    """Localize timestamps in JSON ``/api/`` responses to the display tz."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        tz = get_display_tz()
        if tz.upper() == "UTC":
            return response  # default: no body read, zero overhead
        if not request.url.path.startswith("/api/"):
            return response
        if "application/json" not in response.headers.get("content-type", ""):
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        try:
            body = json.dumps(localize_timestamps(json.loads(body), tz)).encode("utf-8")
        except Exception:
            pass  # leave body unchanged on any failure

        headers = dict(response.headers)
        headers.pop("content-length", None)  # length changed; let Starlette recompute
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type="application/json",
        )
