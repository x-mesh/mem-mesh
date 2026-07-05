"""Injection recording into ``injected_memories`` (t8 / R9).

The two injection points — SessionStart (``session_start``) and UserPromptSubmit
(``user_prompt_submit``) — must persist the memory ids they actually place into
``additionalContext`` so the injection→utilization link can be measured. These
integration tests drive the real HTTP handlers against a real ``HookService`` +
temp DB and assert the rows land (and don't, when they shouldn't):

* session_start injection → one row per surfaced memory (``injected_via='session_start'``)
* user_prompt_submit injection → one row per threshold-passing result (``injected_via='user_prompt_submit'``)
* below-threshold results are searched but never recorded
* a missing ``ide_session_id`` skips recording (no orphan rows)
* a record failure is swallowed and never blocks the hook response
"""

import os
import tempfile
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.services.recall as recall_mod
import app.web.dashboard.route_modules.hooks as hooks_mod
from app.core.database.base import Database
from app.core.services.hook import HookService
from app.web.dashboard.route_modules.hooks import router as hooks_router


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


async def _injected_rows(db):
    return await db.fetchall(
        "SELECT * FROM injected_memories ORDER BY turn_index, position"
    )


# ─────────────────────────── session_start ───────────────────────────


@pytest.mark.asyncio
async def test_session_start_records_injected_memories(monkeypatch):
    """A SessionStart that surfaces memories writes one injected_memories row per
    memory, in order, tagged injected_via='session_start'."""
    async with _temp_db() as db:
        hook_service = HookService(db)

        class _Ctx:
            pins_count = 1
            open_pins = 1
            completed_pins = 0
            pins = [{"status": "open", "content": "wire injection tracking"}]

        class _Session:
            async def resume_last_session(self, **k):
                return _Ctx()

            async def get_or_create_active_session(self, **k):
                return None

        # search_service present + embedding ready so the surface branch runs;
        # db=None keeps enrichment a graceful no-op (rows still render).
        monkeypatch.setattr(
            hooks_mod,
            "get_services",
            lambda: {
                "search_service": SimpleNamespace(db=None),
                "embedding_service": SimpleNamespace(is_ready=True),
            },
        )
        monkeypatch.setattr(
            recall_mod,
            "surface_relevant_memories",
            AsyncMock(
                return_value=[
                    {
                        "id": "mem-a",
                        "category": "decision",
                        "content": "첫 번째 결정 노트다.",
                        "created_at": "2026-07-01",
                        "score": 0.9,
                    },
                    {
                        "id": "mem-b",
                        "category": "code_snippet",
                        "content": "두 번째 스니펫이다.",
                        "created_at": "2026-07-02",
                        "score": 0.8,
                    },
                ]
            ),
        )

        app, get_hook_service, _, get_session_service = _app()
        app.dependency_overrides[get_hook_service] = lambda: hook_service
        app.dependency_overrides[get_session_service] = lambda: _Session()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post(
                "/api/hooks/claude/session-start",
                json={"session_id": "sess-1", "cwd": "/tmp/mem-mesh"},
            )

        assert r.status_code == 200

        rows = await _injected_rows(db)
        assert len(rows) == 2
        assert [row["memory_id"] for row in rows] == ["mem-a", "mem-b"]
        assert [row["position"] for row in rows] == [0, 1]
        assert {row["injected_via"] for row in rows} == {"session_start"}
        assert {row["ide_session_id"] for row in rows} == {"sess-1"}
        assert {row["project_id"] for row in rows} == {"mem-mesh"}
        # SessionStart is turn 0 of a fresh session; injection reuses that turn.
        assert {row["turn_index"] for row in rows} == {0}


# ─────────────────────────── user_prompt_submit ───────────────────────────


def _search_stub(results):
    return SimpleNamespace(
        db=None, search=AsyncMock(return_value=SimpleNamespace(results=results))
    )


def _result(mid, score):
    return SimpleNamespace(
        id=mid,
        category="decision",
        content=f"{mid} 관련 결정 내용이다.",
        created_at="2026-07-01",
        similarity_score=score,
    )


# A prompt >= 30 chars containing a search keyword ("이전"), so Part 1 runs.
_PROMPT = (
    "이전에 결정한 벡터 검색 방식이 무엇이었는지 다시 확인해줘 정확히 기억이 안 난다"
)


def _quiet_hook_service(db):
    """Real HookService whose reminder counters stay quiet (no uncaptured
    writes), so only the Part-1 injection path is exercised."""
    svc = HookService(db)
    svc.writes_since_save = AsyncMock(return_value=0)
    svc.turns_since_save = AsyncMock(return_value=0)
    return svc


@pytest.mark.asyncio
async def test_user_prompt_submit_records_injected_memories(monkeypatch):
    """A UserPromptSubmit that injects threshold-passing results writes one
    injected_memories row per result, tagged injected_via='user_prompt_submit'."""
    monkeypatch.setenv("MEM_MESH_SEARCH_THRESHOLD", "0.75")
    async with _temp_db() as db:
        hook_service = _quiet_hook_service(db)
        monkeypatch.setattr(
            hooks_mod,
            "get_services",
            lambda: {
                "search_service": _search_stub(
                    [_result("mem-x", 0.9), _result("mem-y", 0.8)]
                ),
                "embedding_service": SimpleNamespace(is_ready=True),
            },
        )

        app, get_hook_service, get_pin_service, _ = _app()
        app.dependency_overrides[get_hook_service] = lambda: hook_service
        app.dependency_overrides[get_pin_service] = lambda: SimpleNamespace(
            get_pins=AsyncMock(return_value=[])
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post(
                "/api/hooks/claude/user-prompt-submit",
                json={
                    "session_id": "sess-2",
                    "cwd": "/tmp/mem-mesh",
                    "prompt": _PROMPT,
                },
            )

        assert r.status_code == 200
        assert "Related Memories" in r.json()["hookSpecificOutput"]["additionalContext"]

        rows = await _injected_rows(db)
        assert len(rows) == 2
        assert [row["memory_id"] for row in rows] == ["mem-x", "mem-y"]
        assert [row["position"] for row in rows] == [0, 1]
        assert {row["injected_via"] for row in rows} == {"user_prompt_submit"}
        assert {row["ide_session_id"] for row in rows} == {"sess-2"}
        assert {row["turn_index"] for row in rows} == {0}


@pytest.mark.asyncio
async def test_below_threshold_results_not_recorded_as_injected(monkeypatch):
    """Results searched but dropped below threshold are never recorded — only
    what actually reaches additionalContext counts as injected."""
    monkeypatch.setenv("MEM_MESH_SEARCH_THRESHOLD", "0.75")
    async with _temp_db() as db:
        hook_service = _quiet_hook_service(db)
        # 0.5 < 0.75 threshold → filtered out, so nothing is injected.
        monkeypatch.setattr(
            hooks_mod,
            "get_services",
            lambda: {
                "search_service": _search_stub([_result("mem-low", 0.5)]),
                "embedding_service": SimpleNamespace(is_ready=True),
            },
        )

        app, get_hook_service, get_pin_service, _ = _app()
        app.dependency_overrides[get_hook_service] = lambda: hook_service
        app.dependency_overrides[get_pin_service] = lambda: SimpleNamespace(
            get_pins=AsyncMock(return_value=[])
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post(
                "/api/hooks/claude/user-prompt-submit",
                json={
                    "session_id": "sess-3",
                    "cwd": "/tmp/mem-mesh",
                    "prompt": _PROMPT,
                },
            )

        assert r.status_code == 200
        assert await _injected_rows(db) == []


@pytest.mark.asyncio
async def test_missing_session_id_skips_injected_record(monkeypatch):
    """Without an ide_session_id there is no join key, so recording is skipped
    even though the memories are still injected into the context."""
    monkeypatch.setenv("MEM_MESH_SEARCH_THRESHOLD", "0.75")
    async with _temp_db() as db:
        hook_service = _quiet_hook_service(db)
        monkeypatch.setattr(
            hooks_mod,
            "get_services",
            lambda: {
                "search_service": _search_stub([_result("mem-x", 0.9)]),
                "embedding_service": SimpleNamespace(is_ready=True),
            },
        )

        app, get_hook_service, get_pin_service, _ = _app()
        app.dependency_overrides[get_hook_service] = lambda: hook_service
        app.dependency_overrides[get_pin_service] = lambda: SimpleNamespace(
            get_pins=AsyncMock(return_value=[])
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post(
                "/api/hooks/claude/user-prompt-submit",
                json={"session_id": "", "cwd": "/tmp/mem-mesh", "prompt": _PROMPT},
            )

        assert r.status_code == 200
        # The memory was still surfaced into the context …
        assert "Related Memories" in r.json()["hookSpecificOutput"]["additionalContext"]
        # … but no orphan row was written.
        assert await _injected_rows(db) == []


@pytest.mark.asyncio
async def test_injected_record_failure_does_not_block_response(monkeypatch):
    """A write failure in the injected_memories path is rolled back and swallowed:
    the hook still answers 200 and still injects the memory into the context."""
    monkeypatch.setenv("MEM_MESH_SEARCH_THRESHOLD", "0.75")
    async with _temp_db() as db:
        # Make only the injected_memories INSERT explode; hook_events stays fine.
        real_execute = db.execute

        async def _boom_on_injected(query, params=()):
            if "injected_memories" in query:
                raise RuntimeError("simulated injected_memories write failure")
            return await real_execute(query, params)

        db.execute = _boom_on_injected

        hook_service = _quiet_hook_service(db)
        monkeypatch.setattr(
            hooks_mod,
            "get_services",
            lambda: {
                "search_service": _search_stub([_result("mem-x", 0.9)]),
                "embedding_service": SimpleNamespace(is_ready=True),
            },
        )

        app, get_hook_service, get_pin_service, _ = _app()
        app.dependency_overrides[get_hook_service] = lambda: hook_service
        app.dependency_overrides[get_pin_service] = lambda: SimpleNamespace(
            get_pins=AsyncMock(return_value=[])
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post(
                "/api/hooks/claude/user-prompt-submit",
                json={
                    "session_id": "sess-4",
                    "cwd": "/tmp/mem-mesh",
                    "prompt": _PROMPT,
                },
            )

        assert r.status_code == 200
        assert "Related Memories" in r.json()["hookSpecificOutput"]["additionalContext"]
        # The failed transaction rolled back — no partial rows survive. fetchall
        # uses the read pool, not the patched execute, so it observes the DB.
        assert await db.fetchall("SELECT * FROM injected_memories") == []


# ─────────────────────────── unit: record_injected ───────────────────────────


@pytest.mark.asyncio
async def test_record_injected_skips_when_no_session_id():
    """No session id → no rows, returns 0 (guards against orphan rows)."""
    async with _temp_db() as db:
        svc = HookService(db)
        written = await svc.record_injected(
            project_id="p",
            ide_session_id="",
            memory_ids=["m1"],
            turn_index=0,
            injected_via="session_start",
        )
        assert written == 0
        assert await db.fetchall("SELECT * FROM injected_memories") == []


@pytest.mark.asyncio
async def test_record_injected_skips_empty_ids():
    """Empty / falsy id list → nothing written."""
    async with _temp_db() as db:
        svc = HookService(db)
        written = await svc.record_injected(
            project_id="p",
            ide_session_id="s1",
            memory_ids=[None, ""],
            turn_index=3,
            injected_via="user_prompt_submit",
        )
        assert written == 0
        assert await db.fetchall("SELECT * FROM injected_memories") == []


# ─────────────────── unit: _judge_row verdict rules (t9 / R10) ───────────────────
#
# _judge_row is pure/deterministic, so the four verdict tiers are exercised in
# isolation with no DB. Rule order (first match wins): id_ref → keyword →
# activity_only → none.

_MEM_ID = "a1b2c3d4-1111-2222-3333-444455556666"


def test_judge_row_id_ref_wins():
    """The memory id's 8-hex prefix in the message → utilized=1, method='id_ref',
    even when the content keywords are absent and there was downstream activity."""
    utilized, method = HookService._judge_row(
        memory_id=_MEM_ID,
        injection_turn=0,
        message_lower=f"앞서 주입된 {_MEM_ID[:8]} 메모리를 참고해 처리했다",
        content="완전히 다른 주제의 내용이다 과일과 날씨",
        max_activity_turn=9,
    )
    assert (utilized, method) == (1, "id_ref")


def test_judge_row_keyword_match():
    """>= 2 of the memory's top keywords appearing (Korean stem + English token)
    → utilized=1, method='keyword'."""
    content = "sqlite-vec 벡터 검색 인덱스를 하이브리드 검색에 통합하기로 결정했다"
    message = "앞서 결정한 벡터 검색 방식대로 sqlite-vec 인덱스를 구현했다".lower()
    utilized, method = HookService._judge_row(
        memory_id="deadbeef-0000-0000-0000-000000000000",
        injection_turn=0,
        message_lower=message,
        content=content,
        max_activity_turn=-1,
    )
    assert (utilized, method) == (1, "keyword")


def test_judge_row_single_keyword_is_not_enough():
    """A single shared keyword is below the >= 2 threshold → not 'keyword'; with no
    id ref and no activity it falls through to 'none'."""
    utilized, method = HookService._judge_row(
        memory_id=_MEM_ID,
        injection_turn=0,
        message_lower="카프카 이야기만 잠깐 나눴다".lower(),
        content="카프카 이벤트 스트리밍 파티션 재구성 결정",
        max_activity_turn=-1,
    )
    assert (utilized, method) == (0, "none")


def test_judge_row_activity_only():
    """No id/keyword evidence but a write/save happened after injection → weak
    signal: utilized=0, method='activity_only' (never counted as utilized)."""
    utilized, method = HookService._judge_row(
        memory_id=_MEM_ID,
        injection_turn=0,
        message_lower="관계없는 요약 텍스트만 남겼다".lower(),
        content="벡터 검색 인덱스 통합 결정",
        max_activity_turn=3,
    )
    assert (utilized, method) == (0, "activity_only")


def test_judge_row_none():
    """No id ref, no keyword hit, no downstream activity → utilized=0, 'none'."""
    utilized, method = HookService._judge_row(
        memory_id=_MEM_ID,
        injection_turn=5,
        message_lower="관계없는 요약 텍스트만 남겼다".lower(),
        content="벡터 검색 인덱스 통합 결정",
        max_activity_turn=-1,
    )
    assert (utilized, method) == (0, "none")


def test_judge_row_short_id_not_matched():
    """An id shorter than the 8-char prefix can never be an id_ref (guards against
    a too-loose prefix)."""
    utilized, method = HookService._judge_row(
        memory_id="abc123",
        injection_turn=0,
        message_lower="abc123 mentioned verbatim here",
        content=None,
        max_activity_turn=-1,
    )
    assert (utilized, method) == (0, "none")


# ─────────────────── integration: judge_injected (t9 / R10) ───────────────────


async def _insert_memory(db, memory_id, content):
    """Minimal valid memories row so keyword matching has content to read."""
    now = "2026-07-01T00:00:00+00:00"
    await db.execute(
        "INSERT INTO memories (id, content, content_hash, project_id, category, "
        "source, embedding, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            memory_id,
            content,
            f"h-{memory_id}",
            "mem-mesh",
            "decision",
            "test",
            b"",
            now,
            now,
        ),
    )
    db.connection.commit()


@pytest.mark.asyncio
async def test_judge_injected_persists_verdicts_and_summary():
    """judge_injected writes utilized/judge_method/judged_at per row and returns a
    {judged, utilized, by_method} summary. id-referenced memory → utilized, the
    other → none."""
    mid_a = "a1b2c3d4-aaaa-bbbb-cccc-000000000001"
    mid_b = "ffffeeee-dddd-cccc-bbbb-000000000002"
    async with _temp_db() as db:
        svc = HookService(db)
        await svc.record_injected(
            project_id="mem-mesh",
            ide_session_id="s1",
            memory_ids=[mid_a, mid_b],
            turn_index=0,
            injected_via="session_start",
        )
        summary = await svc.judge_injected(
            "s1", f"이전에 주입된 {mid_a[:8]} 메모리를 참고해 처리했다"
        )
        assert summary["judged"] == 2
        assert summary["utilized"] == 1
        assert summary["by_method"] == {"id_ref": 1, "none": 1}

        rows = await db.fetchall(
            "SELECT memory_id, utilized, judge_method, judged_at "
            "FROM injected_memories"
        )
        by_id = {r["memory_id"]: r for r in rows}
        assert by_id[mid_a]["utilized"] == 1
        assert by_id[mid_a]["judge_method"] == "id_ref"
        assert by_id[mid_b]["utilized"] == 0
        assert by_id[mid_b]["judge_method"] == "none"
        assert all(r["judged_at"] for r in rows)


@pytest.mark.asyncio
async def test_judge_injected_keyword_reads_memory_content():
    """A memory whose top keywords resurface in the message is judged 'keyword'
    from its persisted content."""
    mid = "0badf00d-0000-1111-2222-000000000010"
    async with _temp_db() as db:
        svc = HookService(db)
        await _insert_memory(
            db, mid, "sqlite-vec 벡터 검색 인덱스를 하이브리드 검색에 통합 결정했다"
        )
        await svc.record_injected(
            project_id="mem-mesh",
            ide_session_id="s1",
            memory_ids=[mid],
            turn_index=0,
            injected_via="session_start",
        )
        summary = await svc.judge_injected(
            "s1", "앞서 결정한 벡터 검색 방식대로 sqlite-vec 인덱스를 구현했다"
        )
        assert summary["utilized"] == 1
        assert summary["by_method"] == {"keyword": 1}


@pytest.mark.asyncio
async def test_judge_injected_activity_only_from_event_stream():
    """With no id/keyword tie but a write recorded after the injection turn, the
    verdict is the weak 'activity_only' (utilized stays 0)."""
    mid = "0badbeef-0000-1111-2222-000000000020"
    async with _temp_db() as db:
        svc = HookService(db)
        await svc.record_event(
            project_id="mem-mesh", ide_session_id="s1", event_name="SessionStart"
        )  # turn 0
        await svc.record_injected(
            project_id="mem-mesh",
            ide_session_id="s1",
            memory_ids=[mid],
            turn_index=0,
            injected_via="session_start",
        )
        await svc.record_event(
            project_id="mem-mesh",
            ide_session_id="s1",
            event_name="UserPromptSubmit",
            prompt="작업 진행",
        )  # turn 1
        await svc.record_write(
            project_id="mem-mesh", ide_session_id="s1", tool_name="Edit"
        )  # turn 2 (PostToolUse)

        summary = await svc.judge_injected("s1", "관계없는 요약 텍스트만 남겼다")
        assert summary["utilized"] == 0
        assert summary["by_method"] == {"activity_only": 1}


@pytest.mark.asyncio
async def test_judge_injected_only_judges_unjudged_rows():
    """Cumulative judging: each Stop touches only the still-NULL rows, so a prior
    verdict is frozen while a newly injected memory is judged on its own."""
    mid_a = "a1b2c3d4-aaaa-0000-0000-000000000001"
    mid_c = "cccccccc-3333-0000-0000-000000000003"
    async with _temp_db() as db:
        svc = HookService(db)
        await svc.record_injected(
            project_id="mem-mesh",
            ide_session_id="s1",
            memory_ids=[mid_a],
            turn_index=0,
            injected_via="session_start",
        )
        first = await svc.judge_injected("s1", f"used {mid_a[:8]} directly")
        assert first == {"judged": 1, "utilized": 1, "by_method": {"id_ref": 1}}

        # A later turn injects another memory; a fresh Stop judges only it.
        await svc.record_injected(
            project_id="mem-mesh",
            ide_session_id="s1",
            memory_ids=[mid_c],
            turn_index=2,
            injected_via="user_prompt_submit",
        )
        second = await svc.judge_injected("s1", "완전히 무관한 마무리 텍스트")
        assert second == {"judged": 1, "utilized": 0, "by_method": {"none": 1}}

        rows = await db.fetchall(
            "SELECT memory_id, judge_method FROM injected_memories"
        )
        by_id = {r["memory_id"]: r["judge_method"] for r in rows}
        assert by_id[mid_a] == "id_ref"  # unchanged by the second Stop
        assert by_id[mid_c] == "none"


@pytest.mark.asyncio
async def test_judge_injected_no_rows_or_no_session_is_noop():
    """Empty session id, or a session with no unjudged rows, returns the zero
    summary and writes nothing."""
    async with _temp_db() as db:
        svc = HookService(db)
        assert await svc.judge_injected("", "anything") == {
            "judged": 0,
            "utilized": 0,
            "by_method": {},
        }
        assert await svc.judge_injected("no-such-session", "anything") == {
            "judged": 0,
            "utilized": 0,
            "by_method": {},
        }


@pytest.mark.asyncio
async def test_judge_injected_swallows_errors_and_leaves_rows_unjudged():
    """A write failure mid-judge is rolled back and swallowed (non-blocking): the
    summary is empty and the row stays utilized IS NULL for a later retry."""
    mid = "deadbeef-0000-1111-2222-000000000030"
    async with _temp_db() as db:
        svc = HookService(db)
        await svc.record_injected(
            project_id="mem-mesh",
            ide_session_id="s1",
            memory_ids=[mid],
            turn_index=0,
            injected_via="session_start",
        )

        real_execute = db.execute

        async def _boom_on_update(query, params=()):
            if "UPDATE injected_memories" in query:
                raise RuntimeError("simulated verdict write failure")
            return await real_execute(query, params)

        db.execute = _boom_on_update
        summary = await svc.judge_injected("s1", f"used {mid[:8]} directly")
        assert summary == {"judged": 0, "utilized": 0, "by_method": {}}

        db.execute = real_execute
        rows = await db.fetchall("SELECT utilized FROM injected_memories")
        assert rows[0]["utilized"] is None
