"""Cross-project inbox section in the SessionStart injection.

A pin tagged ``INBOX_PIN_TAG`` was written by ANOTHER project (x-kit's
``/xm:toss``) to report a problem it found in this one. These tests pin three
contracts:

1. **Zero incoming → byte-identical output.** Adding the feature must not change
   what an existing project sees.
2. **Incoming pins render in their own section, not the activity list.** They are
   foreign work; showing them as this project's own pins would be wrong, and
   showing them in *both* places would duplicate.
3. **A failure inside the block never costs the whole injection.** The block is
   wrapped in its own try/except for the same reason ``team_hub_block`` is — an
   escaping exception aborts the entire handler, dropping all injected context.

Placement is also asserted: the section must sit ahead of "Recent Activity",
because compact mode truncates ``additionalContext`` at
``COMPACT_CONTEXT_CHARS`` and a trailing section would be invisible there.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.web.dashboard.route_modules.hooks as hooks_mod
from app.web.dashboard.route_modules.hooks import INBOX_PIN_TAG
from app.web.dashboard.route_modules.hooks import router as hooks_router


def _app():
    from app.web.common.dependencies import (
        get_hook_service,
        get_pin_service,
        get_session_service,
    )
    from app.web.oauth.middleware import verify_hook_token

    app = FastAPI()
    app.include_router(hooks_router, prefix="/api")
    app.dependency_overrides[verify_hook_token] = lambda: None
    return app, get_hook_service, get_pin_service, get_session_service


def _pin(content, *, tags=None, status="in_progress"):
    pin = {"status": status, "content": content}
    if tags is not None:
        pin["tags"] = tags
    return pin


async def _run(monkeypatch, pins):
    """POST session-start with `pins` as the resumed context; return the text."""

    async def _noop_record(*a, **k):
        return None

    monkeypatch.setattr(hooks_mod, "_record", _noop_record)

    class _Ctx:
        pins_count = len(pins)
        open_pins = len(pins)
        completed_pins = 0

    _Ctx.pins = pins

    class _Session:
        async def resume_last_session(self, **k):
            return _Ctx()

        async def get_or_create_active_session(self, **k):
            return None

    hook_stub = SimpleNamespace(is_continuation=AsyncMock(return_value=False))

    # No embedding service → memory surfacing branch stays out of the way.
    monkeypatch.setattr(
        hooks_mod,
        "get_services",
        lambda: {
            "search_service": SimpleNamespace(db=None),
            "embedding_service": SimpleNamespace(is_ready=False),
        },
    )

    app, get_hook_service, _, get_session_service = _app()
    app.dependency_overrides[get_hook_service] = lambda: hook_stub
    app.dependency_overrides[get_session_service] = lambda: _Session()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post(
            "/api/hooks/claude/session-start",
            json={"session_id": "s1", "cwd": "/tmp/mem-mesh"},
        )
    assert r.status_code == 200
    return r.json()["hookSpecificOutput"]["additionalContext"]


@pytest.mark.asyncio
async def test_no_incoming_pins_leaves_output_unchanged(monkeypatch):
    """Zero incoming → no section, and ordinary pins render exactly as before."""
    text = await _run(monkeypatch, [_pin("ordinary local work")])

    assert "### Incoming" not in text
    assert "- [pin] ordinary local work" in text
    assert "### Recent Activity" in text


@pytest.mark.asyncio
async def test_untagged_pins_are_never_treated_as_incoming(monkeypatch):
    """A pin with unrelated tags stays in the activity list."""
    text = await _run(monkeypatch, [_pin("local work", tags=["refactor", "cli"])])

    assert "### Incoming" not in text
    assert "- [pin] local work" in text


@pytest.mark.asyncio
async def test_incoming_pin_renders_in_its_own_section(monkeypatch):
    """Tagged pins appear under Incoming and are removed from the activity list."""
    text = await _run(
        monkeypatch,
        [
            _pin("local work"),
            _pin("land가 paused를 ok로 보고", tags=[INBOX_PIN_TAG]),
        ],
    )

    assert "### Incoming (1)" in text
    assert "land가 paused를 ok로 보고" in text
    # Rendered once, in the Incoming section only — never as this project's pin.
    assert "- [pin] land가 paused를 ok로 보고" not in text
    # The local pin is untouched.
    assert "- [pin] local work" in text


@pytest.mark.asyncio
async def test_incoming_section_precedes_recent_activity(monkeypatch):
    """Compact mode truncates from the front, so Incoming must come first."""
    text = await _run(
        monkeypatch,
        [_pin("foreign report", tags=[INBOX_PIN_TAG])],
    )

    assert text.index("### Incoming") < text.index("### Recent Activity")


@pytest.mark.asyncio
async def test_incoming_list_is_capped_with_overflow_line(monkeypatch):
    """A large backlog must not crowd out the rest of the context."""
    pins = [_pin(f"report {i}", tags=[INBOX_PIN_TAG]) for i in range(7)]
    text = await _run(monkeypatch, pins)

    assert "### Incoming (7)" in text
    assert "report 0" in text
    assert "report 4" in text
    # Beyond the preview limit the bodies collapse into a count.
    assert "report 5" not in text
    assert "report 6" not in text
    assert "…외 2건" in text


@pytest.mark.asyncio
async def test_failure_inside_incoming_block_preserves_rest_of_context(monkeypatch):
    """An exception in the block must cost only the block, never the injection."""
    # Slicing content by a non-int raises TypeError inside the block.
    monkeypatch.setattr(hooks_mod, "_INBOX_CONTENT_CHARS", "boom")

    text = await _run(
        monkeypatch,
        [
            _pin("local work"),
            _pin("foreign report", tags=[INBOX_PIN_TAG]),
        ],
    )

    # Section is gone...
    assert "### Incoming" not in text
    # ...but everything else survived.
    assert "## mem-mesh Session Context (Auto-injected)" in text
    assert "### Recent Activity" in text
    assert "- [pin] local work" in text
