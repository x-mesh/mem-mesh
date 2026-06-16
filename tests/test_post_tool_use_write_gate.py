"""PostToolUse write-signal gate tests.

The pin/save reminders are evidence-based: they fire only when the session has
an uncaptured write (an Edit/Write recorded since the last save), so a pure
question/analysis session never gets nagged. This covers:

* ``HookService.record_write`` / ``writes_since_save`` counting + save reset;
* a write event never inflates the UserPromptSubmit turn counter;
* the ``/post-tool-use`` handler records only write tools, skips the rest;
* the ``_require_write_signal`` env knob.

The installer wiring (PostToolUse entry per mode/profile) is covered by the
build-settings assertions in ``test_install_hooks_idempotency.py`` and the
import-time checks; here we focus on the runtime gate logic.
"""

import os
import tempfile

import pytest

from app.core.schemas.hooks import PostToolUsePayload
from app.core.services.hook import WRITE_TOOLS, HookService
from app.web.dashboard.route_modules import hooks as http_hooks


@pytest.fixture
async def temp_db():
    from app.core.database.base import Database

    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    db = Database(db_path)
    await db.connect()
    yield db
    await db.close()

    for ext in ["", "-wal", "-shm"]:
        path = db_path + ext
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture
async def hook_service(temp_db):
    return HookService(temp_db)


class TestWritesSinceSave:
    """record_write + writes_since_save counting semantics."""

    @pytest.mark.asyncio
    async def test_zero_with_no_writes(self, hook_service):
        await hook_service.record_event(
            project_id="p",
            ide_session_id="s1",
            event_name="UserPromptSubmit",
            prompt="just a question",
        )
        assert await hook_service.writes_since_save("s1") == 0

    @pytest.mark.asyncio
    async def test_record_write_is_counted(self, hook_service):
        await hook_service.record_write(
            project_id="p", ide_session_id="s1", tool_name="Edit"
        )
        await hook_service.record_write(
            project_id="p", ide_session_id="s1", tool_name="Write"
        )
        assert await hook_service.writes_since_save("s1") == 2

    @pytest.mark.asyncio
    async def test_save_resets_writes_since(self, hook_service):
        # A write happens, then a save (pin_add marker) lands on a Stop turn.
        await hook_service.record_write(
            project_id="p", ide_session_id="s1", tool_name="Edit"
        )
        assert await hook_service.writes_since_save("s1") == 1

        await hook_service.record_event(
            project_id="p",
            ide_session_id="s1",
            event_name="Stop",
            assistant_message="called mcp__mem-mesh__pin_add to track work",
        )
        # The save turn resets the counter — nothing uncaptured remains.
        assert await hook_service.writes_since_save("s1") == 0

        # A fresh write after the save counts again.
        await hook_service.record_write(
            project_id="p", ide_session_id="s1", tool_name="MultiEdit"
        )
        assert await hook_service.writes_since_save("s1") == 1

    @pytest.mark.asyncio
    async def test_write_event_does_not_inflate_turn_counter(self, hook_service):
        # PostToolUse writes must never count as UserPromptSubmit turns, else
        # the "N turns since save" reminder would mis-fire.
        await hook_service.record_event(
            project_id="p",
            ide_session_id="s1",
            event_name="UserPromptSubmit",
            prompt="q1",
        )
        await hook_service.record_write(
            project_id="p", ide_session_id="s1", tool_name="Edit"
        )
        await hook_service.record_write(
            project_id="p", ide_session_id="s1", tool_name="Write"
        )
        assert await hook_service.turns_since_save("s1") == 1

    @pytest.mark.asyncio
    async def test_empty_session_id_is_zero(self, hook_service):
        assert await hook_service.writes_since_save("") == 0


class TestPostToolUseHandler:
    """The /post-tool-use endpoint records only write tools."""

    @pytest.mark.asyncio
    async def test_write_tool_recorded(self, hook_service):
        for tool in WRITE_TOOLS:
            payload = PostToolUsePayload(session_id="sw", tool_name=tool, cwd="/x/p")
            resp = await http_hooks.post_tool_use(payload, hook_service)
            assert resp.status_code == 200
        assert await hook_service.writes_since_save("sw") == len(WRITE_TOOLS)

    @pytest.mark.asyncio
    async def test_non_write_tool_skipped(self, hook_service):
        for tool in ("Read", "Grep", "Bash", "Glob", ""):
            payload = PostToolUsePayload(session_id="sr", tool_name=tool, cwd="/x/p")
            resp = await http_hooks.post_tool_use(payload, hook_service)
            assert resp.status_code == 200
        assert await hook_service.writes_since_save("sr") == 0

    @pytest.mark.asyncio
    async def test_missing_session_id_skipped(self, hook_service):
        payload = PostToolUsePayload(session_id=None, tool_name="Edit", cwd="/x/p")
        resp = await http_hooks.post_tool_use(payload, hook_service)
        assert resp.status_code == 200  # never raises into the caller


class TestRequireWriteKnob:
    """MEM_MESH_REMINDER_REQUIRE_WRITE toggles the gate."""

    def test_default_on(self, monkeypatch):
        monkeypatch.delenv("MEM_MESH_REMINDER_REQUIRE_WRITE", raising=False)
        assert http_hooks._require_write_signal() is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", "False", "OFF"])
    def test_disabled_values(self, monkeypatch, val):
        monkeypatch.setenv("MEM_MESH_REMINDER_REQUIRE_WRITE", val)
        assert http_hooks._require_write_signal() is False

    @pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
    def test_enabled_values(self, monkeypatch, val):
        monkeypatch.setenv("MEM_MESH_REMINDER_REQUIRE_WRITE", val)
        assert http_hooks._require_write_signal() is True
