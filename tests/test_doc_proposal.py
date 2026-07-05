"""Doc proposal 상태 머신 (P4 문서 승격) 테스트.

정상 전이 전부 + 불법 전이 거부, path traversal 검증, 그리고 서버가 파일에
쓰지 않는다는 부재 검증을 다룬다.
"""

import builtins
import hashlib
import os
import pathlib
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.database.base import Database
from app.core.errors import (
    ChatNotConfiguredError,
    ChatProviderError,
    DocProposalNotFoundError,
    DocProposalPathError,
    InvalidStatusTransitionError,
    ValidationError,
)
from app.core.schemas.doc_proposal import DocProposalCreate
from app.core.services.chat import ChatService
from app.core.services.doc_proposal import DocProposalService


@asynccontextmanager
async def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path, embedding_dim=3)
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
        os.remove(path)


def _params(
    *,
    project_id="proj",
    file_path="docs/notes.md",
    original_hash="abc123",
    proposed_content="# Notes\n\nupdated body",
    rationale="high-value memory belongs in the versioned doc",
    source_memory_ids=None,
    model="stub-model",
):
    return DocProposalCreate(
        project_id=project_id,
        file_path=file_path,
        original_hash=original_hash,
        proposed_content=proposed_content,
        rationale=rationale,
        source_memory_ids=source_memory_ids or ["m1", "m2"],
        model=model,
    )


# ── create ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_proposal_starts_pending_and_parses_sources():
    async with _temp_db() as db:
        svc = DocProposalService(db)
        created = await svc.create_proposal(_params())

        assert created["status"] == "pending"
        assert created["file_path"] == "docs/notes.md"
        assert created["original_hash"] == "abc123"
        assert created["source_memory_ids"] == ["m1", "m2"]
        assert created["model"] == "stub-model"

        # Round-trips through get_proposal with the JSON source list decoded.
        fetched = await svc.get_proposal(created["id"])
        assert fetched is not None
        assert fetched["source_memory_ids"] == ["m1", "m2"]


@pytest.mark.asyncio
async def test_create_proposal_strips_whitespace_in_path():
    async with _temp_db() as db:
        svc = DocProposalService(db)
        created = await svc.create_proposal(_params(file_path="  docs/a.md  "))
        assert created["file_path"] == "docs/a.md"


# ── valid transitions ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_approve_apply_path():
    """pending → approved → applied (모든 정상 전이의 승인 경로)."""
    async with _temp_db() as db:
        svc = DocProposalService(db)
        created = await svc.create_proposal(_params())
        pid = created["id"]

        approved = await svc.approve_proposal(pid)
        assert approved["status"] == "approved"

        applied = await svc.mark_applied(pid)
        assert applied["status"] == "applied"


@pytest.mark.asyncio
async def test_reject_path():
    """pending → rejected (거부 경로)."""
    async with _temp_db() as db:
        svc = DocProposalService(db)
        created = await svc.create_proposal(_params())

        rejected = await svc.reject_proposal(created["id"])
        assert rejected["status"] == "rejected"


# ── illegal transitions ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_cannot_skip_to_applied():
    async with _temp_db() as db:
        svc = DocProposalService(db)
        created = await svc.create_proposal(_params())
        with pytest.raises(InvalidStatusTransitionError):
            await svc.mark_applied(created["id"])
        # Unchanged after the rejected transition.
        assert (await svc.get_proposal(created["id"]))["status"] == "pending"


@pytest.mark.asyncio
async def test_approved_cannot_be_rejected():
    async with _temp_db() as db:
        svc = DocProposalService(db)
        created = await svc.create_proposal(_params())
        await svc.approve_proposal(created["id"])
        with pytest.raises(InvalidStatusTransitionError):
            await svc.reject_proposal(created["id"])


@pytest.mark.asyncio
async def test_approved_cannot_be_reapproved():
    async with _temp_db() as db:
        svc = DocProposalService(db)
        created = await svc.create_proposal(_params())
        await svc.approve_proposal(created["id"])
        with pytest.raises(InvalidStatusTransitionError):
            await svc.approve_proposal(created["id"])


@pytest.mark.asyncio
async def test_applied_is_terminal():
    async with _temp_db() as db:
        svc = DocProposalService(db)
        created = await svc.create_proposal(_params())
        pid = created["id"]
        await svc.approve_proposal(pid)
        await svc.mark_applied(pid)
        for transition in (svc.approve_proposal, svc.reject_proposal, svc.mark_applied):
            with pytest.raises(InvalidStatusTransitionError):
                await transition(pid)


@pytest.mark.asyncio
async def test_rejected_is_terminal():
    async with _temp_db() as db:
        svc = DocProposalService(db)
        created = await svc.create_proposal(_params())
        pid = created["id"]
        await svc.reject_proposal(pid)
        for transition in (svc.approve_proposal, svc.reject_proposal, svc.mark_applied):
            with pytest.raises(InvalidStatusTransitionError):
                await transition(pid)


@pytest.mark.asyncio
async def test_transition_on_missing_proposal_raises_not_found():
    async with _temp_db() as db:
        svc = DocProposalService(db)
        with pytest.raises(DocProposalNotFoundError):
            await svc.approve_proposal("no-such-id")


# ── path validation (traversal / absolute) ───────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_path",
    [
        "/etc/passwd",  # absolute POSIX
        "../secrets.md",  # parent traversal
        "docs/../../etc/hosts",  # traversal mid-path
        "C:\\Windows\\system32",  # Windows drive
        "\\\\host\\share\\x",  # UNC / backslash root
        "~/secrets",  # home-relative
        "   ",  # empty after strip
    ],
)
async def test_create_rejects_unsafe_paths(bad_path):
    async with _temp_db() as db:
        svc = DocProposalService(db)
        with pytest.raises(DocProposalPathError):
            await svc.create_proposal(_params(file_path=bad_path))


# ── filtering ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_and_count_by_status():
    async with _temp_db() as db:
        svc = DocProposalService(db)
        a = await svc.create_proposal(_params(file_path="docs/a.md"))
        b = await svc.create_proposal(_params(file_path="docs/b.md"))
        await svc.create_proposal(_params(file_path="docs/c.md"))
        await svc.approve_proposal(a["id"])
        await svc.reject_proposal(b["id"])

        assert await svc.count_proposals(project_id="proj", status="pending") == 1
        assert await svc.count_proposals(project_id="proj", status="approved") == 1
        assert await svc.count_proposals(project_id="proj", status="rejected") == 1

        pending = await svc.list_proposals(project_id="proj", status="pending")
        assert [p["file_path"] for p in pending] == ["docs/c.md"]


# ── server never writes files (absence proof) ────────────────────────────────


@pytest.mark.asyncio
async def test_service_never_writes_to_filesystem(monkeypatch):
    """공개 메서드 전 생명주기를 돌리는 동안 어떤 파일 쓰기도 일어나지 않음을
    증명한다. sqlite는 C 확장으로 동작하므로 ``builtins.open``/``Path`` 쓰기
    가드에 걸리지 않는다 — 즉 서비스가 파일에 쓰면 곧바로 실패한다."""
    real_open = builtins.open

    def _guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"file write attempted: open({file!r}, {mode!r})")
        return real_open(file, mode, *args, **kwargs)

    def _blocked(*args, **kwargs):
        raise AssertionError("file write attempted via pathlib.Path")

    monkeypatch.setattr(builtins, "open", _guarded_open)
    monkeypatch.setattr(pathlib.Path, "write_text", _blocked)
    monkeypatch.setattr(pathlib.Path, "write_bytes", _blocked)

    async with _temp_db() as db:
        svc = DocProposalService(db)
        created = await svc.create_proposal(_params())
        pid = created["id"]
        await svc.approve_proposal(pid)
        await svc.mark_applied(pid)
        await svc.list_proposals(project_id="proj")
        await svc.count_proposals(project_id="proj")

        # The proposed content lives in the DB, not on disk.
        applied = await svc.get_proposal(pid)
        assert applied["status"] == "applied"
        assert applied["proposed_content"] == "# Notes\n\nupdated body"


# ── generation: fixtures + fakes ──────────────────────────────────────────────


def _iso(hours_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


async def _add_memory(
    db,
    memory_id,
    *,
    project_id="proj",
    category="decision",
    content="a durable decision worth promoting into the versioned doc",
    access_count=0,
    tags="[]",
    status="canonical",
    hours_ago=0.0,
):
    ts = _iso(hours_ago)
    await db.execute(
        """
        INSERT INTO memories (
            id, content, content_hash, project_id, category, source,
            embedding, tags, access_count, status, created_at, updated_at,
            content_bytes
        )
        VALUES (?, ?, ?, ?, ?, 'test', ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            memory_id,
            content,
            f"hash-{memory_id}",
            project_id,
            category,
            b"123",
            tags,
            access_count,
            status,
            ts,
            ts,
        ),
    )


async def _add_enrichment(db, memory_id, *, title="T", abstract="A", tags="[]"):
    from app.core.services.enrich_store import EnrichmentStore

    store = EnrichmentStore(db)
    await store.ensure_schema()
    await db.execute(
        """
        INSERT INTO memory_enrichment
            (memory_id, title, abstract, tags, display_kind, model, created_at)
        VALUES (?, ?, ?, ?, '', '', ?)
        """,
        (memory_id, title, abstract, tags, _iso()),
    )


class _FakeChatService:
    """generate_proposal에 주입하는 LLM stub — 실제 provider 호출 없음."""

    def __init__(self, *, configured=True, revision=None, fail=None):
        self._configured = configured
        self._revision = revision or {
            "proposed_content": "# Notes\n\n## Auth\nRotate JWTs every 15m.\n",
            "rationale": "Folded the auth-rotation decision into the doc.",
            "model": "stub-model",
        }
        self._fail = fail
        self.calls: list = []

    async def is_configured(self, settings):
        return self._configured

    async def generate_doc_revision(
        self,
        *,
        file_path,
        file_content,
        memories,
        settings,
        http_client=None,
        language=None,
    ):
        self.calls.append(
            {"file_path": file_path, "file_content": file_content, "memories": memories}
        )
        if self._fail is not None:
            raise self._fail
        return dict(self._revision)


class _FakeHTTPResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeHTTPClient:
    def __init__(self, response):
        self.response = response
        self.calls: list = []

    async def post(self, url, *, headers, json, timeout):
        self.calls.append({"url": url, "json": json})
        return self.response


def _chat_settings(**overrides):
    base = dict(
        chat_llm_provider="anthropic",
        chat_llm_api_key="",
        chat_llm_model="",
        chat_llm_base_url="",
        chat_llm_timeout=60.0,
        chat_llm_max_tokens=2048,
        chat_output_language="auto",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ── generate_proposal: happy path (LLM mock) ──────────────────────────────────


@pytest.mark.asyncio
async def test_generate_proposal_creates_pending_from_memories():
    async with _temp_db() as db:
        await _add_memory(db, "m1", content="decision one")
        await _add_memory(db, "m2", content="decision two")
        await _add_enrichment(db, "m1", abstract="short summary of m1")
        svc = DocProposalService(db)
        chat = _FakeChatService()

        file_content = "# Notes\n\nold body"
        created = await svc.generate_proposal(
            project_id="proj",
            file_path="  docs/notes.md  ",
            file_content=file_content,
            memory_ids=["m1", "m2"],
            chat_service=chat,
            settings=SimpleNamespace(),
        )

        assert created["status"] == "pending"
        assert created["file_path"] == "docs/notes.md"  # stripped + validated
        assert created["proposed_content"].startswith("# Notes\n\n## Auth")
        assert created["rationale"] == "Folded the auth-rotation decision into the doc."
        assert created["model"] == "stub-model"
        assert created["source_memory_ids"] == ["m1", "m2"]
        # original_hash is computed server-side from the client-provided content.
        assert (
            created["original_hash"]
            == hashlib.sha256(file_content.encode("utf-8")).hexdigest()
        )
        # The LLM saw both memories, in order, with m1's enrichment abstract.
        assert [m["id"] for m in chat.calls[0]["memories"]] == ["m1", "m2"]
        assert chat.calls[0]["memories"][0]["abstract"] == "short summary of m1"


@pytest.mark.asyncio
async def test_generate_proposal_skips_unknown_memory_ids():
    async with _temp_db() as db:
        await _add_memory(db, "m1", content="only real memory")
        svc = DocProposalService(db)
        chat = _FakeChatService()

        created = await svc.generate_proposal(
            project_id="proj",
            file_path="docs/a.md",
            file_content="# A",
            memory_ids=["m1", "ghost"],
            chat_service=chat,
            settings=SimpleNamespace(),
        )
        # Unknown id dropped from what the LLM saw and from the stored sources.
        assert created["source_memory_ids"] == ["m1"]
        assert [m["id"] for m in chat.calls[0]["memories"]] == ["m1"]


# ── generate_proposal: feature gate + validation ──────────────────────────────


@pytest.mark.asyncio
async def test_generate_proposal_rejected_when_llm_unconfigured():
    async with _temp_db() as db:
        await _add_memory(db, "m1")
        svc = DocProposalService(db)
        chat = _FakeChatService(configured=False)

        with pytest.raises(ChatNotConfiguredError):
            await svc.generate_proposal(
                project_id="proj",
                file_path="docs/notes.md",
                file_content="# Notes",
                memory_ids=["m1"],
                chat_service=chat,
                settings=SimpleNamespace(),
            )
        # Gate fired before any LLM work, and no proposal was stored.
        assert chat.calls == []
        assert await svc.count_proposals(project_id="proj", status="pending") == 0


@pytest.mark.asyncio
async def test_generate_proposal_rejects_bad_path_before_llm():
    async with _temp_db() as db:
        await _add_memory(db, "m1")
        svc = DocProposalService(db)
        chat = _FakeChatService()
        with pytest.raises(DocProposalPathError):
            await svc.generate_proposal(
                project_id="proj",
                file_path="../escape.md",
                file_content="# x",
                memory_ids=["m1"],
                chat_service=chat,
                settings=SimpleNamespace(),
            )
        assert chat.calls == []  # never reached the model


@pytest.mark.asyncio
async def test_generate_proposal_requires_at_least_one_memory():
    async with _temp_db() as db:
        svc = DocProposalService(db)
        chat = _FakeChatService()
        with pytest.raises(ValidationError):
            await svc.generate_proposal(
                project_id="proj",
                file_path="docs/notes.md",
                file_content="# Notes",
                memory_ids=[],
                chat_service=chat,
                settings=SimpleNamespace(),
            )
        assert chat.calls == []


@pytest.mark.asyncio
async def test_generate_proposal_errors_on_empty_revision():
    async with _temp_db() as db:
        await _add_memory(db, "m1")
        svc = DocProposalService(db)
        chat = _FakeChatService(revision={"proposed_content": "  ", "rationale": ""})
        with pytest.raises(ChatProviderError):
            await svc.generate_proposal(
                project_id="proj",
                file_path="docs/notes.md",
                file_content="# Notes",
                memory_ids=["m1"],
                chat_service=chat,
                settings=SimpleNamespace(),
            )


# ── list_promotion_candidates: works WITHOUT an LLM ───────────────────────────


@pytest.mark.asyncio
async def test_list_promotion_candidates_ranks_high_value_first():
    async with _temp_db() as db:
        # A plain task with no signal, and a bug that is enriched + often surfaced.
        await _add_memory(db, "low", category="task", content="chore note", hours_ago=1)
        await _add_memory(
            db, "high", category="bug", content="nasty prod bug", access_count=9
        )
        await _add_enrichment(db, "high", title="Prod bug", abstract="root cause")
        svc = DocProposalService(db)

        candidates = await svc.list_promotion_candidates("proj")

        ids = [c["id"] for c in candidates]
        assert ids[0] == "high"  # decision/bug + access + enrichment outrank a task
        top = candidates[0]
        assert top["category"] == "bug"
        assert top["has_enrichment"] is True
        assert top["title"] == "Prod bug"
        assert top["access_count"] == 9
        assert top["score"] > candidates[-1]["score"]


@pytest.mark.asyncio
async def test_list_promotion_candidates_no_llm_and_scopes_project():
    async with _temp_db() as db:
        await _add_memory(db, "a", project_id="proj")
        await _add_memory(db, "b", project_id="other")
        await _add_memory(db, "draft", project_id="proj", status="pending")
        svc = DocProposalService(db)

        # No chat_service involved — the free tier never touches the LLM.
        candidates = await svc.list_promotion_candidates("proj")
        ids = {c["id"] for c in candidates}
        assert ids == {"a"}  # other project excluded; non-canonical excluded


@pytest.mark.asyncio
async def test_list_promotion_candidates_empty_for_unknown_project():
    async with _temp_db() as db:
        svc = DocProposalService(db)
        assert await svc.list_promotion_candidates("nope") == []


# ── ChatService.generate_doc_revision: prompt + JSON parse via fake HTTP ───────


@pytest.mark.asyncio
async def test_generate_doc_revision_parses_json_via_fake_http():
    async with _temp_db() as db:
        service = ChatService(db)
        http = _FakeHTTPClient(
            _FakeHTTPResponse(
                payload={
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                '{"proposed_content":"# Doc\\n\\nrevised body",'
                                '"rationale":"merged the decision"}'
                            ),
                        }
                    ]
                }
            )
        )
        out = await service.generate_doc_revision(
            file_path="docs/x.md",
            file_content="# Doc\n\nold body",
            memories=[
                {"id": "m1", "category": "decision", "content": "c1", "tags": ["t"]}
            ],
            settings=_chat_settings(chat_llm_api_key="k"),
            http_client=http,
        )
        assert out["proposed_content"] == "# Doc\n\nrevised body"
        assert out["rationale"] == "merged the decision"
        # System prompt forbids code fences; the user turn carries the file body.
        sent = http.calls[0]["json"]
        assert http.calls, "the fake HTTP client should have been called"
        assert "old body" in str(sent)


@pytest.mark.asyncio
async def test_generate_doc_revision_bad_json_raises():
    async with _temp_db() as db:
        service = ChatService(db)
        http = _FakeHTTPClient(
            _FakeHTTPResponse(
                payload={"content": [{"type": "text", "text": "not json at all"}]}
            )
        )
        with pytest.raises(ChatProviderError, match="parse"):
            await service.generate_doc_revision(
                file_path="docs/x.md",
                file_content="# Doc",
                memories=[{"id": "m1", "content": "c"}],
                settings=_chat_settings(chat_llm_api_key="k"),
                http_client=http,
            )


@pytest.mark.asyncio
async def test_generate_doc_revision_unconfigured_raises_not_configured():
    async with _temp_db() as db:
        service = ChatService(db)
        with pytest.raises(ChatNotConfiguredError):
            await service.generate_doc_revision(
                file_path="docs/x.md",
                file_content="# Doc",
                memories=[{"id": "m1", "content": "c"}],
                settings=_chat_settings(chat_llm_api_key=""),
            )


# ── approval surface: REST routes + MCP tools (t21) ───────────────────────────
#
# End-to-end over the two review surfaces that connect proposals to a human and
# then to the applying agent: the Curation REST routes (approve/reject) and the
# MCP tools (doc_proposals to fetch approved work, doc_proposal_applied to report
# the terminal transition). The server still writes no files anywhere here.

from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.schemas.doc_proposal import (  # noqa: E402
    DocProposalAgentView,
    DocProposalAppliedResponse,
)
from app.mcp_common.dispatcher import MCPDispatcher  # noqa: E402
from app.mcp_common.tools import MCPToolHandlers  # noqa: E402
from app.web.common.dependencies import get_database  # noqa: E402
from app.web.common.middleware import setup_exception_handlers  # noqa: E402
from app.web.dashboard.route_modules import curation as curation_route  # noqa: E402


def _rest_app(db) -> FastAPI:
    """Curation router under /api with the MemMeshError handler wired, so a
    state-machine rejection maps to its HTTP status (400/404) rather than a 500."""
    app = FastAPI()
    app.include_router(curation_route.router, prefix="/api")
    app.dependency_overrides[get_database] = lambda: db
    setup_exception_handlers(app)
    return app


def _mcp_handlers(db) -> MCPToolHandlers:
    """MCP handlers over a stub storage whose ``.db`` is the temp Database —
    ``_get_database`` reads exactly that attribute."""
    return MCPToolHandlers(SimpleNamespace(db=db), enable_compression=False)


async def _seed_pending(db, **overrides) -> dict:
    """Insert one pending proposal via the service (path validation + row shape)."""
    return await DocProposalService(db).create_proposal(_params(**overrides))


@pytest.mark.asyncio
async def test_rest_approve_then_mcp_applied_e2e():
    """pending →(REST approve)→ approved →(MCP applied)→ applied, end to end."""
    async with _temp_db() as db:
        created = await _seed_pending(db)
        pid = created["id"]
        app = _rest_app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            # The pending proposal shows up in the review queue.
            r = await client.get(
                "/api/curation/doc-proposals", params={"status": "pending"}
            )
            assert r.status_code == 200
            body = r.json()
            assert body["count"] == 1
            assert body["proposals"][0]["id"] == pid

            # Approve flips state (pure transition — no file apply on the server).
            r = await client.post(f"/api/curation/doc-proposals/{pid}/approve")
            assert r.status_code == 200
            assert r.json()["status"] == "approved"

        # The applying agent fetches approved work and gets the fields it needs.
        handlers = _mcp_handlers(db)
        listed = await handlers.doc_proposals(project_id="proj", status="approved")
        assert listed["count"] == 1
        item = listed["proposals"][0]
        assert item["id"] == pid
        assert item["file_path"] == "docs/notes.md"
        assert item["proposed_content"] == "# Notes\n\nupdated body"
        assert item["original_hash"] == "abc123"

        # Agent reports the local apply — terminal transition, no server writes.
        applied = await handlers.doc_proposal_applied(proposal_id=pid)
        assert applied == {"proposal_id": pid, "status": "applied", "applied": True}

        # State is durably applied.
        assert (await DocProposalService(db).get_proposal(pid))["status"] == "applied"


@pytest.mark.asyncio
async def test_rest_reject_path_then_approve_is_conflict():
    async with _temp_db() as db:
        created = await _seed_pending(db)
        pid = created["id"]
        app = _rest_app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post(f"/api/curation/doc-proposals/{pid}/reject")
            assert r.status_code == 200
            assert r.json()["status"] == "rejected"

            # rejected is terminal → approving it is an illegal transition (400).
            r = await client.post(f"/api/curation/doc-proposals/{pid}/approve")
            assert r.status_code == 400
            assert r.json()["error"] == "INVALID_STATUS_TRANSITION"


@pytest.mark.asyncio
async def test_rest_approve_unknown_proposal_is_404():
    async with _temp_db() as db:
        app = _rest_app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/api/curation/doc-proposals/no-such-id/approve")
            assert r.status_code == 404
            assert r.json()["error"] == "DOC_PROPOSAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_rest_get_detail_and_missing():
    async with _temp_db() as db:
        created = await _seed_pending(db)
        pid = created["id"]
        app = _rest_app(db)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.get(f"/api/curation/doc-proposals/{pid}")
            assert r.status_code == 200
            assert r.json()["proposed_content"] == "# Notes\n\nupdated body"

            r = await client.get("/api/curation/doc-proposals/ghost")
            assert r.status_code == 404


@pytest.mark.asyncio
async def test_mcp_applied_before_approval_is_rejected():
    """A pending proposal cannot jump to applied — the client must wait for a
    human approval first. Verified at the handler and through the dispatcher."""
    async with _temp_db() as db:
        created = await _seed_pending(db)
        pid = created["id"]
        handlers = _mcp_handlers(db)

        with pytest.raises(InvalidStatusTransitionError):
            await handlers.doc_proposal_applied(proposal_id=pid)

        # Through the dispatcher the same rejection surfaces as an MCP tool error.
        dispatcher = MCPDispatcher(handlers)
        resp = await dispatcher.dispatch("doc_proposal_applied", {"proposal_id": pid})
        assert resp["isError"] is True

        # Untouched: still pending, never applied.
        assert (await DocProposalService(db).get_proposal(pid))["status"] == "pending"


@pytest.mark.asyncio
async def test_mcp_doc_proposals_only_returns_matching_status_as_agent_view():
    async with _temp_db() as db:
        svc = DocProposalService(db)
        approved = await svc.create_proposal(_params(file_path="docs/a.md"))
        await svc.approve_proposal(approved["id"])
        await svc.create_proposal(_params(file_path="docs/b.md"))  # stays pending

        handlers = _mcp_handlers(db)
        listed = await handlers.doc_proposals(project_id="proj", status="approved")

        assert listed["count"] == 1
        assert listed["status"] == "approved"
        item = listed["proposals"][0]
        # Agent view carries what an applier needs and drops server-only fields.
        assert DocProposalAgentView(**item).file_path == "docs/a.md"
        assert "model" not in item
        assert "created_at" not in item
        assert set(item) == {
            "id",
            "project_id",
            "file_path",
            "original_hash",
            "proposed_content",
            "rationale",
            "source_memory_ids",
            "status",
            "updated_at",
        }


@pytest.mark.asyncio
async def test_mcp_doc_proposal_applied_response_schema():
    async with _temp_db() as db:
        svc = DocProposalService(db)
        created = await svc.create_proposal(_params())
        await svc.approve_proposal(created["id"])

        handlers = _mcp_handlers(db)
        applied = await handlers.doc_proposal_applied(proposal_id=created["id"])

        model = DocProposalAppliedResponse(**applied)
        assert model.proposal_id == created["id"]
        assert model.status == "applied"
        assert model.applied is True


@pytest.mark.asyncio
async def test_mcp_dispatch_requires_project_id_and_proposal_id():
    async with _temp_db() as db:
        dispatcher = MCPDispatcher(_mcp_handlers(db))
        r1 = await dispatcher.dispatch("doc_proposals", {})
        assert r1["isError"] is True
        r2 = await dispatcher.dispatch("doc_proposal_applied", {})
        assert r2["isError"] is True


def test_doc_proposal_tools_registered_in_schema():
    from app.mcp_common.schemas import get_all_tool_schemas

    names = [s["name"] for s in get_all_tool_schemas()]
    assert "doc_proposals" in names
    assert "doc_proposal_applied" in names
