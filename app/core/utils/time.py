"""Display-timezone conversion for API/MCP output.

Storage stays UTC everywhere — DB ``created_at`` / ``updated_at`` and the 100+
``datetime.utcnow()`` call sites are never touched. Only the OUTPUT boundary
localizes UTC ISO8601 timestamps to the configured display timezone
(``display_timezone``, e.g. ``Asia/Seoul``) as offset-bearing ISO8601
(``2026-06-16T10:56:43+09:00``).

The default ``UTC`` short-circuits every path so a UTC deployment pays nothing.
Conversion is best-effort: an unparseable value or unknown zone is returned
unchanged — this code runs on the response path and must never raise.
"""

from datetime import datetime, timezone
from typing import Any, Optional

# Field names whose string values are UTC timestamps to localize. Kept as a
# whitelist so non-timestamp strings (ids, content) are never reinterpreted.
_TIME_FIELDS = frozenset(
    {
        "created_at",
        "updated_at",
        "completed_at",
        "last_migration",
        "last_accessed",
        "last_accessed_at",
        "expires_at",
        "started_at",
        "ended_at",
        "resolved_at",
        "promoted_at",
        "timestamp",
    }
)


def get_display_tz() -> str:
    """Resolved display timezone (env > db override > default ``UTC``)."""
    try:
        from app.core.runtime_config import effective

        val, _ = effective("display_timezone")
        return str(val or "UTC")
    except Exception:
        return "UTC"


def _zone(tz_name: str):
    """ZoneInfo for ``tz_name``, falling back to UTC on any failure."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def to_display_tz(value: str, tz_name: Optional[str] = None) -> str:
    """Convert one UTC ISO8601 string to the display tz as offset ISO8601.

    ``UTC`` (default) and any non-string / unparseable value are returned
    unchanged.
    """
    if not isinstance(value, str) or not value:
        return value
    tz_name = tz_name or get_display_tz()
    if tz_name.upper() == "UTC":
        return value
    try:
        # Accept both trailing-Z and offset forms.
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_zone(tz_name)).isoformat()
    except Exception:
        return value


def localize_timestamps(obj: Any, tz_name: Optional[str] = None) -> Any:
    """Recursively localize known UTC timestamp fields in dicts/lists.

    Returns a new structure (input is not mutated). Only string values under
    keys in :data:`_TIME_FIELDS` are converted. The ``UTC`` display tz
    short-circuits without walking the structure.
    """
    tz_name = tz_name or get_display_tz()
    if tz_name.upper() == "UTC":
        return obj
    return _walk(obj, tz_name)


def _walk(obj: Any, tz_name: str) -> Any:
    if isinstance(obj, dict):
        return {
            k: (
                to_display_tz(v, tz_name)
                if k in _TIME_FIELDS and isinstance(v, str)
                else _walk(v, tz_name)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_walk(x, tz_name) for x in obj]
    return obj
