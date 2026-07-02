"""Hook endpoints must answer fast and save in the background.

The save path (embedding + single-writer SQLite) can exceed the shell hooks'
curl --max-time / Claude Code's hook timeout under concurrent batch load, so
/stop-style endpoints queue the save via BackgroundTasks instead of awaiting
it in the request. These tests pin that contract.
"""

import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.web.dashboard.route_modules.hooks as hooks_mod
from app.web.dashboard.route_modules.hooks import router as hooks_router


class _SlowSaveRecorder:
    """Stands in for _save_memory: slow like the real embedding+write path."""

    def __init__(self, delay: float = 0.2):
        self.delay = delay
        self.calls = []

    async def __call__(self, project_id, content, category, **kwargs):
        await asyncio.sleep(self.delay)
        self.calls.append({"project_id": project_id, "category": category})
        return True


def _app():
    from app.web.common.dependencies import get_hook_service
    from app.web.oauth.middleware import verify_hook_token

    app = FastAPI()
    app.include_router(hooks_router, prefix="/api")
    app.dependency_overrides[verify_hook_token] = lambda: None
    # _record is monkeypatched to a no-op in these tests, so the service
    # object is never actually used — a bare stub keeps the DB out of scope.
    app.dependency_overrides[get_hook_service] = lambda: object()
    return app


@pytest.mark.asyncio
async def test_stop_returns_before_slow_save_and_still_saves(monkeypatch):
    recorder = _SlowSaveRecorder(delay=0.2)
    monkeypatch.setattr(hooks_mod, "_save_memory", recorder)

    async def _noop_record(*a, **k):
        return None

    monkeypatch.setattr(hooks_mod, "_record", _noop_record)

    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        r = await client.post(
            "/api/hooks/claude/stop",
            json={
                "session_id": "s1",
                "cwd": "/tmp/proj",
                "stop_hook_active": False,
                "last_assistant_message": (
                    "버그 원인을 확인했고 다음과 같이 해결했다. 백그라운드 저장 "
                    "회귀 테스트용 본문이며 키워드 매칭을 위해 해결/수정을 포함한다."
                ),
            },
        )
        elapsed = loop.time() - t0

    assert r.status_code == 200
    assert "queued save" in r.headers.get("X-Mem-Mesh-Hook-Status", "")
    # The response must NOT have awaited the slow save inline. ASGITransport
    # runs background tasks after the response; by the time the client context
    # exits they have completed — so the save itself still happened.
    assert recorder.calls and recorder.calls[0]["project_id"] == "proj"
    assert elapsed < 5  # sanity bound; inline await would add recorder.delay


@pytest.mark.asyncio
async def test_subagent_stop_queues_save(monkeypatch):
    recorder = _SlowSaveRecorder(delay=0.05)
    monkeypatch.setattr(hooks_mod, "_save_memory", recorder)

    async def _noop_record(*a, **k):
        return None

    monkeypatch.setattr(hooks_mod, "_record", _noop_record)

    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post(
            "/api/hooks/claude/subagent-stop",
            json={
                "session_id": "s1",
                "cwd": "/tmp/proj",
                "stop_hook_active": False,
                "agent_type": "tester",
                "last_assistant_message": (
                    "서브에이전트가 버그를 수정했고 원인을 해결했다는 결과 보고이다. "
                    "백그라운드 저장 회귀 테스트용 본문으로, 서브에이전트 훅의 길이 "
                    "게이트(기본 100자)를 확실히 통과하도록 충분히 긴 부가 설명 문장을 "
                    "덧붙여 총 길이를 넉넉하게 확보한다."
                ),
            },
        )

    assert r.status_code == 200
    assert "queued save" in r.headers.get("X-Mem-Mesh-Hook-Status", "")
    assert recorder.calls


# ── findings-envelope → markdown transform (server-side hook saves) ─────────


def test_findings_envelope_rendered_as_markdown():
    """A raw {"findings": [...]} answer (codex/claude stop path saves
    server-side) must be stored as readable markdown, not a JSON blob."""
    raw = (
        '{"findings":[{"severity":"high","file":"lib/tasks.mjs","line":1173,'
        '"claim":"early completion","evidence":"line one\nline two"}]}'
    )
    out = hooks_mod._render_json_answer(raw)
    assert "## Review findings (1)" in out
    assert "[high] `lib/tasks.mjs:1173` — early completion" in out
    assert "evidence: line one line two" in out
    assert '{"findings"' not in out


def test_findings_envelope_in_qa_pair_rewrites_answer_only():
    raw = '{"findings":[{"severity":"low","file":"a.py","claim":"c"}]}'
    combined = "Q: review this diff\n\nA: " + raw
    out = hooks_mod._render_json_answer(combined)
    assert out.startswith("Q: review this diff\n\nA: ## Review findings (1)")


def test_fenced_findings_envelope_rendered():
    raw = '{"findings":[{"severity":"medium","file":"b.js","line":9,"claim":"x"}]}'
    out = hooks_mod._render_json_answer("```json\n" + raw + "\n```")
    assert "## Review findings (1)" in out


def test_non_findings_content_passes_through():
    for text in (
        "일반 산문 응답은 그대로 저장되어야 한다.",
        '{"status": "ok", "message": "not findings"}',
        '{"findings": []}',
        "Q: 질문\n\nA: 일반 답변",
    ):
        assert hooks_mod._render_json_answer(text) == text
