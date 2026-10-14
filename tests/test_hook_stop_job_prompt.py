"""Stop skips the auto-save for a scheduled job's turn.

A cron/headless loop opens a fresh session per run with a byte-identical
prompt. Once that prompt is on record in two other sessions of the project
within the window, the Stop records the turn but does not save it. A person
repeating a short instruction, or repeating a prompt inside one session, still
saves.
"""

import os
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.web.dashboard.route_modules.hooks as hooks_mod
from app.core.database.base import Database
from app.core.services.hook import HookService
from app.web.dashboard.route_modules.hooks import router as hooks_router

_JOB_PROMPT = (
    "너는 점검 자동화 루프다. "
    + "순서대로 상태를 확인하고 이상이 있으면 보고하라. " * 8
)
_SHORT_PROMPT = "해봐"
# Long enough and keyword-bearing ("해결", "수정") so the Stop handler reaches
# the save decision instead of skipping the turn earlier.
_ANSWER = (
    "버그 원인을 확인했고 다음과 같이 해결했다. 반복 작업 판별 회귀 테스트용 "
    "본문이며 키워드 매칭을 위해 해결/수정을 포함한다."
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
    from app.web.common.dependencies import get_hook_service
    from app.web.oauth.middleware import verify_hook_token

    app = FastAPI()
    app.include_router(hooks_router, prefix="/api")
    app.dependency_overrides[verify_hook_token] = lambda: None
    app.dependency_overrides[get_hook_service] = lambda: hook_service
    return app


async def _prompt(hook_service, session, prompt, project="mem-mesh"):
    await hook_service.record_event(
        project_id=project,
        ide_session_id=session,
        event_name="UserPromptSubmit",
        prompt=prompt,
    )


async def _age(db, session, days):
    old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    await db.execute(
        "UPDATE hook_events SET created_at = ? WHERE ide_session_id = ?",
        (old, session),
    )
    db.connection.commit()


async def _two_other_sessions(db, hs):
    await _prompt(hs, "run-1", _JOB_PROMPT)
    await _prompt(hs, "run-2", _JOB_PROMPT)


async def _one_other_session(db, hs):
    await _prompt(hs, "run-1", _JOB_PROMPT)


async def _short_prompt_in_other_sessions(db, hs):
    for s in ("a", "b", "c"):
        await _prompt(hs, s, _SHORT_PROMPT)


async def _repeats_inside_this_session(db, hs):
    for _ in range(3):
        await _prompt(hs, "current", _JOB_PROMPT)


async def _other_sessions_outside_window(db, hs):
    await _two_other_sessions(db, hs)
    await _age(db, "run-1", 4)
    await _age(db, "run-2", 4)


async def _other_sessions_in_other_project(db, hs):
    await _prompt(hs, "run-1", _JOB_PROMPT, project="other")
    await _prompt(hs, "run-2", _JOB_PROMPT, project="other")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "history, current_prompt, expect_save",
    [
        (_two_other_sessions, _JOB_PROMPT, False),
        (_one_other_session, _JOB_PROMPT, True),
        (_short_prompt_in_other_sessions, _SHORT_PROMPT, True),
        (_repeats_inside_this_session, _JOB_PROMPT, True),
        (_other_sessions_outside_window, _JOB_PROMPT, True),
        (_other_sessions_in_other_project, _JOB_PROMPT, True),
    ],
    ids=[
        "two-other-sessions",
        "one-other-session",
        "short-prompt",
        "same-session-only",
        "outside-window",
        "other-project",
    ],
)
async def test_stop_job_prompt_repeat(
    monkeypatch, history, current_prompt, expect_save
):
    saved: list[str] = []

    async def _capture_save(*args, **kwargs):
        saved.extend(v for v in (*args, *kwargs.values()) if isinstance(v, str))

    monkeypatch.setattr(hooks_mod, "_save_memory", _capture_save)
    async with _temp_db() as db:
        hook_service = HookService(db)
        await history(db, hook_service)
        await _prompt(hook_service, "current", current_prompt)
        transport = ASGITransport(app=_app(hook_service))
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post(
                "/api/hooks/claude/stop",
                json={
                    "session_id": "current",
                    "cwd": "/tmp/mem-mesh",
                    "stop_hook_active": False,
                    "last_assistant_message": _ANSWER,
                },
            )
        recorded = await db.fetchone(
            "SELECT COUNT(*) AS c FROM hook_events "
            "WHERE ide_session_id = 'current' AND event_name = 'Stop'"
        )

    status = r.headers.get("X-Mem-Mesh-Hook-Status", "")
    assert r.status_code == 200
    assert recorded["c"] == 1
    if expect_save:
        assert "queued save" in status, status
        assert any(v.startswith("Q: ") for v in saved), saved
    else:
        assert "job prompt repeated in 2 other sessions" in status, status
        assert not saved
