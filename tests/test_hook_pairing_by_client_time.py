"""Stop/prompt pairing by the hook's client-clock start (``hook_fired_at``).

The forwarders shield their send from a host TERM, so a Stop can reach the
server after the next turn's UserPromptSubmit. Pairing by record order would
then attach the answer to the wrong question. These tests drive the real HTTP
handlers: UserPromptSubmit stores the stamp, and Stop asks ``get_last_prompt``
for the last prompt stamped before its own start.
"""

import os
import tempfile
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.web.dashboard.route_modules.hooks as hooks_mod
from app.core.database.base import Database
from app.core.services.hook import HookService
from app.web.dashboard.route_modules.hooks import router as hooks_router

# Long enough and keyword-bearing ("해결", "수정") so the Stop handler reaches
# the Q&A pairing step instead of skipping the turn.
_ANSWER = (
    "버그 원인을 확인했고 다음과 같이 해결했다. 페어링 회귀 테스트용 본문이며 "
    "키워드 매칭을 위해 해결/수정을 포함한다."
)


@asynccontextmanager
async def _temp_db():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path)
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
        for ext in ["", "-wal", "-shm"]:
            path = db_path + ext
            if os.path.exists(path):
                os.unlink(path)


def _app(hook_service):
    from app.web.common.dependencies import get_hook_service, get_pin_service
    from app.web.oauth.middleware import verify_hook_token

    app = FastAPI()
    app.include_router(hooks_router, prefix="/api")
    app.dependency_overrides[verify_hook_token] = lambda: None
    app.dependency_overrides[get_hook_service] = lambda: hook_service
    app.dependency_overrides[get_pin_service] = lambda: SimpleNamespace(
        get_pins=AsyncMock(return_value=[])
    )
    return app


@pytest.mark.asyncio
async def test_user_prompt_submit_stores_client_stamp(monkeypatch):
    monkeypatch.setattr(hooks_mod, "get_services", lambda: {})
    async with _temp_db() as db:
        hook_service = HookService(db)
        hook_service.writes_since_save = AsyncMock(return_value=0)
        hook_service.turns_since_save = AsyncMock(return_value=0)
        transport = ASGITransport(app=_app(hook_service))
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post(
                "/api/hooks/claude/user-prompt-submit",
                json={
                    "session_id": "sess-t",
                    "cwd": "/tmp/mem-mesh",
                    "prompt": "짧은 질문",
                    "hook_fired_at": 1700000000.25,
                },
            )
        assert r.status_code == 200
        row = await db.fetchone(
            "SELECT client_fired_at FROM hook_events WHERE ide_session_id = 'sess-t'"
        )
        assert row["client_fired_at"] == 1700000000.25


@pytest.mark.asyncio
async def test_stop_pairs_with_prompt_stamped_before_its_start(monkeypatch):
    """Prompts at t=100 and t=103 are on record; the Stop that started at
    t=102 (its send outlived a cancel) must pair with the t=100 question."""
    saved: list[str] = []

    async def _capture_save(*args, **kwargs):
        # _save_memory's content may arrive positionally or by keyword; keep
        # every string argument and look for the paired Q/A below.
        saved.extend(v for v in (*args, *kwargs.values()) if isinstance(v, str))

    monkeypatch.setattr(hooks_mod, "_save_memory", _capture_save)
    async with _temp_db() as db:
        hook_service = HookService(db)
        for prompt, fired in (("first question", 100.0), ("second question", 103.0)):
            await hook_service.record_event(
                project_id="mem-mesh",
                ide_session_id="sess-p",
                event_name="UserPromptSubmit",
                prompt=prompt,
                client_fired_at=fired,
            )
        transport = ASGITransport(app=_app(hook_service))
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post(
                "/api/hooks/claude/stop",
                json={
                    "session_id": "sess-p",
                    "cwd": "/tmp/mem-mesh",
                    "stop_hook_active": False,
                    "last_assistant_message": _ANSWER,
                    "hook_fired_at": 102.0,
                },
            )
        assert r.status_code == 200
        assert any(v.startswith("Q: first question\n") for v in saved), saved
        assert not any("second question" in v for v in saved)
