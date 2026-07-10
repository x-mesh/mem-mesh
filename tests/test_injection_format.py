"""Shared injection formatter + enrichment batch-merge (t17 / R8).

Both hook paths — SessionStart (session_start) and UserPromptSubmit
(user_prompt_submit) — must render their surfaced/retrieved memories through the
single ``recall.render_memory_lines`` formatter, and enrichment (title/abstract)
must be merged with ONE ``memory_id IN (...)`` batch query rather than per-item
lookups. These tests pin both contracts.
"""

import json
import os
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.services.recall as recall_mod
import app.web.dashboard.route_modules.hooks as hooks_mod
from app.core.database.base import Database
from app.core.services.enrich_store import EnrichmentStore
from app.core.services.recall import (
    _age_days,
    _clip,
    _first_sentence,
    _is_aged_anchor,
    _relative_age,
    attach_enrichment,
    attach_stale,
    fetch_enrichment_map,
    fetch_stale_map,
    filter_injectable,
    format_memory_lines,
    normalize_search_result,
    render_memory_lines,
    surface_relevant_memories,
)
from app.core.services.unified_search import UnifiedSearchService
from app.web.dashboard.route_modules.hooks import router as hooks_router

# Fixed clock so relative-age assertions stay deterministic across time.
_NOW = datetime(2026, 7, 5)


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


# ─────────────────────── pure formatter ───────────────────────


def test_format_memory_lines_shape():
    """New shape: ``- [cat] (age · source) title`` for content-derived memories."""
    lines = format_memory_lines(
        [
            {"category": "decision", "created_at": "2026-06-30", "content": "use vec"},
            {"category": "bug", "created_at": "2026-07-05", "content": "fixed null"},
        ],
        now=_NOW,
    )
    assert lines == [
        "- [decision] (5일 전 · extracted) use vec",
        "- [bug] (오늘 · extracted) fixed null",
    ]


def test_format_memory_lines_missing_category_defaults_unknown():
    """Missing category → 'unknown'; source label is always present in the meta."""
    lines = format_memory_lines(
        [{"category": "", "created_at": "2026-07-05", "content": "some note"}],
        now=_NOW,
    )
    assert lines[0] == "- [unknown] (오늘 · extracted) some note"


def test_format_memory_lines_missing_created_at_drops_age():
    """No created_at → meta collapses to source only, no dangling separator."""
    lines = format_memory_lines(
        [{"category": "idea", "created_at": "", "content": "raw idea"}],
        now=_NOW,
    )
    assert lines[0] == "- [idea] (extracted) raw idea"


def test_normalize_search_result_object_and_dict():
    """SearchResult-object and surface-dict inputs converge on one schema."""
    obj = SimpleNamespace(
        id="m1",
        category="decision",
        content="c",
        created_at="2026-01-01T00:00:00Z",
        similarity_score=0.9,
        title="T",
        abstract="A",
    )
    n_obj = normalize_search_result(obj)
    assert n_obj["id"] == "m1"
    assert n_obj["category"] == "decision"
    assert n_obj["score"] == 0.9
    assert n_obj["title"] == "T"

    # surface dict uses "score" (not "similarity_score") and lacks title/abstract.
    n_dict = normalize_search_result(
        {"id": "m2", "category": "bug", "content": "c2", "score": 0.4}
    )
    assert n_dict["id"] == "m2"
    assert n_dict["score"] == 0.4
    assert n_dict["title"] is None


# ───────────── 3-tier fallback (LLM-free, pure parsing) [R4] ─────────────


def _line(mem: dict) -> str:
    return format_memory_lines([mem], now=_NOW)[0]


def test_tier1_enrichment_title_and_abstract():
    """Tier 1: enrichment title/abstract present → title — abstract, source=enriched."""
    line = _line(
        {
            "category": "decision",
            "created_at": "2026-07-05",
            "title": "sqlite-vec 채택",
            "abstract": "FTS5와 벡터를 하이브리드로 결합한다. 재현율이 오른다.",
            "content": "이 원문은 abstract가 있으면 무시된다.",
        }
    )
    assert line == (
        "- [decision] (오늘 · enriched) "
        "sqlite-vec 채택 — FTS5와 벡터를 하이브리드로 결합한다. 재현율이 오른다."
    )


def test_tier1_enrichment_title_without_abstract():
    """Tier 1 with empty abstract → title only, no dangling ' — '."""
    line = _line(
        {
            "category": "idea",
            "created_at": "2026-07-05",
            "title": "제목만 있는 메모리",
            "abstract": "",
            "content": "원문 본문",
        }
    )
    assert line == "- [idea] (오늘 · enriched) 제목만 있는 메모리"


def test_tier2_structure_extraction_markdown_heading():
    """Tier 2: markdown heading → title, first following sentence → summary."""
    content = "## 벡터 검색 결정\n\nsqlite-vec를 사용한다. 그리고 FTS5도 쓴다."
    line = _line(
        {"category": "decision", "created_at": "2026-07-05", "content": content}
    )
    assert line == (
        "- [decision] (오늘 · extracted) 벡터 검색 결정 — sqlite-vec를 사용한다."
    )


def test_tier2_structure_extraction_plain_title_line():
    """Tier 2: a short first line (no terminator) acts as a title over the body."""
    content = "검색 성능 최적화\n캐시를 도입해 지연을 줄였다. 추가 튜닝 예정."
    line = _line(
        {"category": "incident", "created_at": "2026-07-05", "content": content}
    )
    assert line == (
        "- [incident] (오늘 · extracted) 검색 성능 최적화 — 캐시를 도입해 지연을 줄였다."
    )


def test_tier3_free_text_sentence_boundary_clip():
    """Tier 3: long prose is clipped at a sentence boundary within ~200 chars.

    Sentences that overflow the limit are dropped at a boundary, never mid-sentence.
    """
    content = (
        "짧은 문장이다. " * 25
        + "이 마지막 잘림 표식 문장은 이백 자를 넘겨 노출되면 안 된다."
    )
    line = _line(
        {"category": "decision", "created_at": "2026-07-05", "content": content}
    )
    assert line.startswith("- [decision] (오늘 · extracted) ")
    body = line.split(") ", 1)[1]
    assert body.endswith("짧은 문장이다.")  # clean sentence boundary, not mid-word
    assert not body.endswith("…")  # a real boundary was found
    assert "잘림 표식" not in body  # overflow sentence dropped
    assert " — " not in body  # tier 3 has no title/summary separator
    assert len(body) <= 201


# ─────────────── LLM 미등록(ChatService 없음) 동일 동작 [R5] ───────────────


def test_all_tiers_are_llm_free():
    """The format path never imports or calls a chat/LLM service.

    ``format_memory_lines`` is a pure function of stored fields + parsing, so the same
    inputs yield the same lines with or without an LLM configured. We assert the module
    never references a chat/LLM client (a static guard against a future regression).
    """
    import inspect

    src = inspect.getsource(recall_mod)
    for needle in ("ChatService", "chat_service", "openai", "anthropic"):
        assert needle not in src, f"formatter must stay LLM-free, found: {needle}"


def test_tiers_stable_without_enrichment_or_llm():
    """With no enrichment title (Tier 2/3) and no services at all, output is exact."""
    tier2 = _line(
        {
            "category": "decision",
            "created_at": "2026-07-05",
            "content": "# 결정 제목\n본문 첫 문장이다. 둘째 문장.",
            "title": None,
            "abstract": None,
        }
    )
    tier3 = _line(
        {
            "category": "bug",
            "created_at": "2026-07-05",
            "content": "구조 없는 한 문단 텍스트다.",
            "title": None,
            "abstract": None,
        }
    )
    assert tier2 == "- [decision] (오늘 · extracted) 결정 제목 — 본문 첫 문장이다."
    assert tier3 == "- [bug] (오늘 · extracted) 구조 없는 한 문단 텍스트다."
    assert "둘째 문장" not in tier2  # tier-2 summary is first-sentence only


# ───────────────── 나이·출처 표기 스냅샷 [R6] ─────────────────


def test_relative_age_buckets():
    """오늘 / N일 전 / N주 전 / N개월 전 buckets and future/blank guards."""
    assert _relative_age("2026-07-05", now=_NOW) == "오늘"
    assert _relative_age("2026-07-04", now=_NOW) == "1일 전"
    assert _relative_age("2026-06-30", now=_NOW) == "5일 전"
    assert _relative_age("2026-06-21", now=_NOW) == "2주 전"
    assert _relative_age("2026-05-01", now=_NOW) == "2개월 전"
    assert _relative_age("2026-01-05", now=_NOW) == "6개월 전"
    # ISO with tz and future dates.
    assert _relative_age("2026-07-05T09:00:00Z", now=_NOW) == "오늘"
    assert _relative_age("2026-08-01", now=_NOW) == "오늘"  # future → 오늘
    assert _relative_age("", now=_NOW) == ""  # blank → no age
    assert _relative_age("not-a-date", now=_NOW) == ""


def test_source_label_snapshot():
    """enriched vs extracted source labels appear exactly as specified."""
    enriched = _line(
        {
            "category": "decision",
            "created_at": "2026-07-04",
            "title": "T",
            "abstract": "요약이다.",
        }
    )
    extracted = _line(
        {"category": "decision", "created_at": "2026-07-04", "content": "raw content"}
    )
    assert "(1일 전 · enriched)" in enriched
    assert "(1일 전 · extracted)" in extracted


# ────────── 문장 중간 절단 0건 보장 (경계 케이스) ──────────


def test_no_mid_sentence_cut_long_korean():
    """A long Korean run with no terminators clips at a space + '…', never mid-word."""
    text = ("메모리 검색 시스템 성능 최적화 인덱스 튜닝 " * 20).strip()
    out = _clip(text, 200)
    assert out.endswith("…")
    assert len(out) <= 201  # 200 window + ellipsis
    core = out[:-1]  # drop the ellipsis
    # The clip is a clean prefix ending at a word boundary (next char is a space).
    assert text.startswith(core)
    assert text[len(core)] == " "


def test_no_mid_sentence_cut_skips_code_block():
    """Fenced code is stripped, not dumped, and the result is a clean sentence."""
    content = (
        "결정 요약\n"
        "```python\n"
        "import os\n"
        "token = os.environ['SECRET_TOKEN']\n"
        "```\n"
        "토큰은 환경변수로 주입한다."
    )
    line = _line(
        {"category": "decision", "created_at": "2026-07-05", "content": content}
    )
    assert "import os" not in line
    assert "SECRET_TOKEN" not in line
    assert "```" not in line
    assert line == (
        "- [decision] (오늘 · extracted) 결정 요약 — 토큰은 환경변수로 주입한다."
    )


def test_no_mid_sentence_cut_qa_dump():
    """Q:/A: dump → question's first sentence only; the answer body never leaks."""
    content = (
        "Q: 벡터 검색은 어떻게 설정하나요?\n"
        "A: sqlite-vec 확장을 로드하고 하이브리드로 결합하세요. 자세한 건 문서 참고."
    )
    line = _line(
        {"category": "decision", "created_at": "2026-07-05", "content": content}
    )
    assert line == ("- [decision] (오늘 · extracted) 벡터 검색은 어떻게 설정하나요?")
    assert "sqlite-vec 확장" not in line
    assert "A:" not in line


def test_no_mid_sentence_cut_with_emoji():
    """Emoji-laden prose clips at a boundary/space, never inside a token."""
    text = "배포 완료 🚀 성능 개선 📈 캐시 적중률 상승 ✅ 후속 작업 다수 남음 " * 6
    out = _first_sentence(text, 200)
    # First sentence ends at the note-style '남음' ender (다/요/음/함), cleanly.
    assert out.endswith("남음")
    assert "🚀" in out and "📈" in out
    assert not out.endswith("…")  # a real boundary was found, not a forced cut


# ─────────────────── enrichment IN batch merge ───────────────────


@pytest.mark.asyncio
async def test_fetch_enrichment_map_single_in_query():
    """title/abstract/tags are fetched with exactly one IN query for N ids."""
    async with _temp_db() as db:
        store = EnrichmentStore(db)
        await store.upsert(memory_id="a", title="Ta", abstract="Aa", tags=["x", "y"])
        await store.upsert(memory_id="b", title="Tb", abstract="Ab")

        calls = {"n": 0}
        real_fetchall = db.fetchall

        async def _counting_fetchall(query, params=()):
            calls["n"] += 1
            return await real_fetchall(query, params)

        db.fetchall = _counting_fetchall
        emap = await fetch_enrichment_map(db, ["a", "b", "missing"])

        assert calls["n"] == 1  # single batch IN query, not per-id
        assert emap["a"]["title"] == "Ta"
        assert emap["a"]["abstract"] == "Aa"
        assert emap["a"]["tags"] == ["x", "y"]  # enrichment topic tags flow through
        assert emap["b"]["title"] == "Tb"
        assert emap["b"]["tags"] == []  # no tags upserted → empty list
        assert "missing" not in emap


@pytest.mark.asyncio
async def test_fetch_enrichment_map_missing_table_graceful():
    """A DB that never ran enrichment (no table) yields {} without raising."""
    async with _temp_db() as db:
        # No EnrichmentStore.ensure_schema() → memory_enrichment absent.
        emap = await fetch_enrichment_map(db, ["a", "b"])
        assert emap == {}


@pytest.mark.asyncio
async def test_fetch_enrichment_map_empty_inputs():
    async with _temp_db() as db:
        assert await fetch_enrichment_map(db, []) == {}
        assert await fetch_enrichment_map(None, ["a"]) == {}


@pytest.mark.asyncio
async def test_attach_enrichment_merges_without_overwriting():
    """Batch merge fills empty title/abstract but preserves pre-set (hub) values."""
    async with _temp_db() as db:
        store = EnrichmentStore(db)
        await store.upsert(memory_id="a", title="local-A", abstract="abs-A")
        await store.upsert(memory_id="b", title="local-B", abstract="abs-B")

        mems = [
            {"id": "a", "title": None, "abstract": None},
            {"id": "b", "title": "hub-B", "abstract": None},  # hub title preserved
        ]
        await attach_enrichment(db, mems)

        assert mems[0]["title"] == "local-A"
        assert mems[0]["abstract"] == "abs-A"
        assert mems[1]["title"] == "hub-B"  # not overwritten
        assert mems[1]["abstract"] == "abs-B"  # empty field filled


@pytest.mark.asyncio
async def test_render_memory_lines_end_to_end():
    """render_memory_lines: normalize → enrich → shared format, in one call.

    Enrichment title/abstract wins (Tier 1) over the raw content, source=enriched.
    """
    async with _temp_db() as db:
        await EnrichmentStore(db).upsert(
            memory_id="m1", title="Vector search decision", abstract="Use sqlite-vec."
        )
        items = [
            SimpleNamespace(
                id="m1",
                category="decision",
                content="body one",
                created_at="2026-07-04T00:00:00Z",
                similarity_score=0.9,
                title=None,
                abstract=None,
            )
        ]
        lines = await render_memory_lines(db, items, now=_NOW)
        assert lines == [
            "- [decision] (1일 전 · enriched) "
            "Vector search decision — Use sqlite-vec."
        ]


# ───────────── both hooks route through the shared formatter ─────────────


def _spy_render(monkeypatch, sentinel_lines):
    """Patch recall.render_memory_lines with a spy returning canned lines."""
    spy = AsyncMock(return_value=sentinel_lines)
    monkeypatch.setattr(recall_mod, "render_memory_lines", spy)
    return spy


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


@pytest.mark.asyncio
async def test_session_start_routes_through_shared_formatter(monkeypatch):
    sentinel = "- [decision] (2026-01-01) SHARED_FORMATTER_SENTINEL"
    spy = _spy_render(monkeypatch, [sentinel])

    async def _noop_record(*a, **k):
        return None

    monkeypatch.setattr(hooks_mod, "_record", _noop_record)

    # An open pin so open_pin_texts is non-empty (surfacing precondition).
    class _Ctx:
        pins_count = 1
        open_pins = 1
        completed_pins = 0
        pins = [{"status": "open", "content": "wire the shared formatter"}]

    class _Session:
        async def resume_last_session(self, **k):
            return _Ctx()

        async def get_or_create_active_session(self, **k):
            return None

    hook_stub = SimpleNamespace(is_continuation=AsyncMock(return_value=False))

    # search_service present + embedding ready so the surface branch runs.
    monkeypatch.setattr(
        hooks_mod,
        "get_services",
        lambda: {
            "search_service": SimpleNamespace(db=None),
            "embedding_service": SimpleNamespace(is_ready=True),
        },
    )
    # surface returns a canned memory; render (spied) turns it into the sentinel.
    monkeypatch.setattr(
        recall_mod,
        "surface_relevant_memories",
        AsyncMock(
            return_value=[
                {
                    "id": "m1",
                    "category": "decision",
                    "content": "x",
                    "created_at": "2026-01-01",
                    "score": 0.9,
                }
            ]
        ),
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
    assert spy.await_count == 1
    assert sentinel in r.json()["hookSpecificOutput"]["additionalContext"]


@pytest.mark.asyncio
async def test_user_prompt_submit_routes_through_shared_formatter(monkeypatch):
    sentinel = "- [decision] (2026-01-01) SHARED_FORMATTER_SENTINEL"
    spy = _spy_render(monkeypatch, [sentinel])

    async def _noop_record(*a, **k):
        return None

    monkeypatch.setattr(hooks_mod, "_record", _noop_record)

    search_stub = SimpleNamespace(
        db=None,
        search=AsyncMock(
            return_value=SimpleNamespace(
                results=[
                    SimpleNamespace(
                        id="m1",
                        category="decision",
                        content="x",
                        created_at="2026-01-01",
                        similarity_score=0.9,
                    )
                ]
            )
        ),
    )
    monkeypatch.setattr(
        hooks_mod,
        "get_services",
        lambda: {
            "search_service": search_stub,
            "embedding_service": SimpleNamespace(is_ready=True),
        },
    )

    # Keep part2/part3 reminders quiet: no uncaptured writes → work_done False.
    hook_stub = SimpleNamespace(
        writes_since_save=AsyncMock(return_value=0),
        turns_since_save=AsyncMock(return_value=0),
    )
    pin_stub = SimpleNamespace(get_pins=AsyncMock(return_value=[]))

    app, get_hook_service, get_pin_service, _ = _app()
    app.dependency_overrides[get_hook_service] = lambda: hook_stub
    app.dependency_overrides[get_pin_service] = lambda: pin_stub

    # Prompt >= 30 chars and contains a search keyword ("이전").
    prompt = "이전에 결정한 벡터 검색 방식이 무엇이었는지 다시 확인해줘 정확히 기억이 안 난다"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post(
            "/api/hooks/claude/user-prompt-submit",
            json={"session_id": "s1", "cwd": "/tmp/mem-mesh", "prompt": prompt},
        )

    assert r.status_code == 200
    assert spy.await_count == 1
    assert sentinel in r.json()["hookSpecificOutput"]["additionalContext"]


# ───────────── canonical-status injection filter (t6 / R7) ─────────────
#
# superseded(=deprecated) 메모리는 어떤 주입 경로에도 나오면 안 된다:
# semantic / hybrid / exact / fuzzy 검색 결과, 그리고 render_memory_lines 주입
# 라인. 유일한 예외는 명시적 id-prefix 직접 조회(_search_by_id_prefix)로, 이는
# superseded도 찾아야 한다(구버전 메모리 감사/추적용).

_CANON_MARK = "CANONICAL_KEEP_VISIBLE"
_DEP_MARK = "SUPERSEDED_MUST_HIDE"


async def _add_status_mem(
    db,
    mid,
    *,
    status,
    content,
    project_id="p6",
    created_at="2026-07-01T00:00:00Z",
):
    """Insert a memory with an explicit reconcile status ('canonical'|'deprecated')."""
    await db.add_memory(
        {
            "id": mid,
            "content": content,
            "content_hash": "h_" + mid,
            "project_id": project_id,
            "category": "decision",
            "status": status,
            "source": "test",
            # memories.embedding is NOT NULL; the real vec column lives in the
            # separate memory_embeddings table, so a placeholder blob suffices.
            "embedding": b"\x00" * 16,
            "tags": None,
            "created_at": created_at,
            "updated_at": created_at,
        }
    )


def _make_search_service(db, embedding):
    """UnifiedSearchService with post-processing off so the ONLY row-dropping
    behavior under test is the canonical-status gate (not quality/noise/norm)."""
    return UnifiedSearchService(
        db=db,
        embedding_service=embedding,
        enable_quality_features=False,
        enable_korean_optimization=False,
        enable_noise_filter=False,
        enable_score_normalization=False,
    )


def _clear_search_cache():
    # Isolate each mode's result: the global cache is keyed by query, so without
    # this an earlier mode's result would cache-hit into the next mode's call.
    from app.core.services.cache_manager import get_cache_manager

    get_cache_manager().clear_all_caches()


@pytest.mark.asyncio
async def test_vector_search_main_path_excludes_deprecated(temp_db):
    """db.vector_search (sqlite-vec JOIN path) drops deprecated at SQL level.

    Both rows get an identical embedding so KNN returns both candidates; only the
    canonical one must survive the ``COALESCE(status,'canonical')='canonical'`` gate.
    """
    from app.core.config import Settings

    dim = Settings().embedding_dim
    canon = uuid.uuid4().hex
    dep = uuid.uuid4().hex
    await _add_status_mem(
        temp_db, canon, status="canonical", content=f"벡터 검색 결정 {_CANON_MARK}"
    )
    await _add_status_mem(
        temp_db, dep, status="deprecated", content=f"벡터 검색 결정 {_DEP_MARK}"
    )

    vec = [0.1] * dim
    active = await temp_db.active_embedding_table()
    for mid in (canon, dep):
        await temp_db.execute(
            f"INSERT INTO {active} (memory_id, embedding) VALUES (?, ?)",
            (mid, json.dumps(vec)),
        )

    qbytes = np.array(vec, dtype=np.float32).tobytes()
    rows = await temp_db.vector_search(
        embedding=qbytes, limit=10, filters={"project_id": "p6"}
    )
    ids = {r["id"] for r in rows}
    assert canon in ids  # canonical still surfaces from the vec path
    assert dep not in ids  # deprecated filtered before it can be injected


@pytest.mark.asyncio
async def test_vector_fallback_path_excludes_deprecated(temp_db):
    """When no vectors are stored, vector_search falls back to _fallback_search,
    which must apply the same canonical gate (this is the path a vec-less test DB
    or a sqlite-vec-unavailable deploy actually exercises)."""
    from app.core.config import Settings

    dim = Settings().embedding_dim
    canon = uuid.uuid4().hex
    dep = uuid.uuid4().hex
    await _add_status_mem(
        temp_db, canon, status="canonical", content=f"폴백 검색 {_CANON_MARK}"
    )
    await _add_status_mem(
        temp_db, dep, status="deprecated", content=f"폴백 검색 {_DEP_MARK}"
    )

    # No rows in the active embedding table → KNN empty → _fallback_search runs.
    qbytes = np.zeros(dim, dtype=np.float32).tobytes()
    rows = await temp_db.vector_search(
        embedding=qbytes, limit=10, filters={"project_id": "p6"}
    )
    ids = {r["id"] for r in rows}
    assert canon in ids
    assert dep not in ids


@pytest.mark.asyncio
async def test_search_modes_exclude_deprecated(temp_db, mock_embedding_service):
    """Every injection-facing search mode hides the deprecated memory.

    exact→FTS gate, semantic/hybrid→vector(+fallback) gate, fuzzy→SQL gate.
    """
    canon = uuid.uuid4().hex
    dep = uuid.uuid4().hex
    # Shared query words so FTS/fuzzy match the canonical row on its merits.
    await _add_status_mem(
        temp_db,
        canon,
        status="canonical",
        content=f"하이브리드 검색 아키텍처 {_CANON_MARK}",
    )
    await _add_status_mem(
        temp_db,
        dep,
        status="deprecated",
        content=f"하이브리드 검색 아키텍처 {_DEP_MARK}",
    )

    svc = _make_search_service(temp_db, mock_embedding_service)
    query = "하이브리드 검색"

    for mode in ("exact", "semantic", "hybrid", "fuzzy"):
        _clear_search_cache()
        resp = await svc.search(
            query=query,
            project_id="p6",
            search_mode=mode,
            record_access=False,
        )
        ids = {r.id for r in resp.results}
        assert dep not in ids, f"deprecated memory leaked in '{mode}' mode"
        assert canon in ids, f"canonical memory missing in '{mode}' mode"


@pytest.mark.asyncio
async def test_render_memory_lines_excludes_deprecated(temp_db, mock_embedding_service):
    """End-to-end: search → render_memory_lines injection lines carry the
    canonical content but never the superseded marker."""
    canon = uuid.uuid4().hex
    dep = uuid.uuid4().hex
    await _add_status_mem(
        temp_db, canon, status="canonical", content=f"하이브리드 검색 {_CANON_MARK}"
    )
    await _add_status_mem(
        temp_db, dep, status="deprecated", content=f"하이브리드 검색 {_DEP_MARK}"
    )

    svc = _make_search_service(temp_db, mock_embedding_service)
    _clear_search_cache()
    resp = await svc.search(
        query="하이브리드 검색",
        project_id="p6",
        search_mode="hybrid",
        record_access=False,
    )
    lines = await render_memory_lines(temp_db, resp.results, now=_NOW)
    blob = "\n".join(lines)
    assert _DEP_MARK not in blob
    assert _CANON_MARK in blob


@pytest.mark.asyncio
async def test_id_prefix_lookup_still_finds_deprecated(temp_db, mock_embedding_service):
    """Regression: an explicit id-prefix hunt is the deliberate exception —
    _search_by_id_prefix must still surface a superseded memory by id."""
    dep = uuid.uuid4().hex  # 32 hex chars → id-shaped, routes to id-prefix lookup
    await _add_status_mem(
        temp_db, dep, status="deprecated", content=f"구버전 결정 {_DEP_MARK}"
    )

    svc = _make_search_service(temp_db, mock_embedding_service)
    _clear_search_cache()
    resp = await svc.search(query=dep[:12], project_id="p6", record_access=False)
    ids = {r.id for r in resp.results}
    assert dep in ids  # deprecated is intentionally reachable by direct id lookup


# ─────────────── stale-anchor gate + aged marking (t12 / R14) ───────────────
#
# 2단 stale 판정: 강한 신호(클라이언트가 report_anchor_status로 보고한 stale)는 주입
# 선별 단계에서 제외하고, 약한 신호(commit_hash 앵커 + 나이만 오래된 미검증 메모리)는
# 제외하지 않고 포맷터가 ``· 미검증 anchor`` 경고 토큰만 붙인다. 'fresh'로 검증된 것은
# 경고하지 않는다.

_AGED_ANCHOR = {"commit_hash": "a1b2c3d"}


def test_age_days_buckets():
    """_age_days: 경과 일수(정수), 파싱 불가 None, 미래 음수."""
    assert _age_days("2026-07-05", now=_NOW) == 0
    assert _age_days("2026-07-01", now=_NOW) == 4
    assert _age_days("2026-01-01", now=_NOW) == 185
    assert _age_days("2026-07-05T09:00:00Z", now=_NOW) == 0
    assert _age_days("", now=_NOW) is None
    assert _age_days("not-a-date", now=_NOW) is None
    assert _age_days("2026-08-01", now=_NOW) < 0  # future


def test_is_aged_anchor_matrix():
    """_is_aged_anchor: commit_hash 앵커 + 오래됨 + 미검증일 때만 True."""
    old_commit = {
        "created_at": "2026-01-01",
        "anchors": _AGED_ANCHOR,
        "stale_status": None,
    }
    assert _is_aged_anchor(old_commit, now=_NOW, age_days=90) is True
    # 최근이면 aged 아님
    assert (
        _is_aged_anchor(
            {**old_commit, "created_at": "2026-07-01"}, now=_NOW, age_days=90
        )
        is False
    )
    # 클라이언트가 fresh로 검증했으면 경고 안 함
    assert (
        _is_aged_anchor({**old_commit, "stale_status": "fresh"}, now=_NOW, age_days=90)
        is False
    )
    # commit_hash 없는 앵커(파일 경로만)는 도달성 판단 근거 약함 → 경고 안 함
    assert (
        _is_aged_anchor(
            {**old_commit, "anchors": {"file_paths": ["app/x.py"]}},
            now=_NOW,
            age_days=90,
        )
        is False
    )
    # 앵커 자체가 없으면 경고 안 함
    assert (
        _is_aged_anchor(
            {"created_at": "2026-01-01", "anchors": None}, now=_NOW, age_days=90
        )
        is False
    )


def test_format_aged_anchor_token_appended():
    """오래된 미검증 commit 앵커 → meta에 ``· 미검증 anchor`` 경고 토큰."""
    line = format_memory_lines(
        [
            {
                "category": "decision",
                "created_at": "2026-01-01",
                "content": "old anchored decision",
                "anchors": _AGED_ANCHOR,
            }
        ],
        now=_NOW,
        aged_days=90,
    )[0]
    assert line == (
        "- [decision] (6개월 전 · extracted · 미검증 anchor) old anchored decision"
    )


def test_format_no_aged_token_when_recent_or_fresh_or_no_anchor():
    """최근·fresh검증·앵커없음은 경고 토큰이 붙지 않는다(정상 라인)."""
    recent = format_memory_lines(
        [
            {
                "category": "decision",
                "created_at": "2026-07-01",
                "content": "recent anchored",
                "anchors": _AGED_ANCHOR,
            }
        ],
        now=_NOW,
        aged_days=90,
    )[0]
    verified = format_memory_lines(
        [
            {
                "category": "decision",
                "created_at": "2026-01-01",
                "content": "old but verified",
                "anchors": _AGED_ANCHOR,
                "stale_status": "fresh",
            }
        ],
        now=_NOW,
        aged_days=90,
    )[0]
    no_anchor = format_memory_lines(
        [
            {
                "category": "decision",
                "created_at": "2026-01-01",
                "content": "old no anchor",
            }
        ],
        now=_NOW,
        aged_days=90,
    )[0]
    for line in (recent, verified, no_anchor):
        assert "미검증 anchor" not in line


async def _add_mem(
    db,
    mid,
    *,
    content,
    anchors=None,
    stale_status=None,
    created_at="2026-07-01T00:00:00Z",
    project_id="p12",
    category="decision",
):
    """Insert a memory row and optionally stamp a client stale verdict."""
    await db.add_memory(
        {
            "id": mid,
            "content": content,
            "content_hash": "h_" + mid,
            "project_id": project_id,
            "category": category,
            "status": "canonical",
            "source": "test",
            "embedding": b"\x00" * 16,
            "tags": None,
            "anchors": json.dumps(anchors) if anchors else None,
            "created_at": created_at,
            "updated_at": created_at,
        }
    )
    if stale_status is not None:
        await db.execute(
            "UPDATE memories SET stale_status = ? WHERE id = ?", (stale_status, mid)
        )


@pytest.mark.asyncio
async def test_fetch_stale_map_returns_status_anchors_created_at():
    async with _temp_db() as db:
        await _add_mem(
            db, "s1", content="stale one", anchors=_AGED_ANCHOR, stale_status="stale"
        )
        await _add_mem(db, "s2", content="unverified one")
        smap = await fetch_stale_map(db, ["s1", "s2", "missing"])
        assert smap["s1"]["stale_status"] == "stale"
        assert smap["s1"]["anchors"] == _AGED_ANCHOR  # JSON string parsed to dict
        assert smap["s2"]["stale_status"] is None
        assert smap["s2"]["anchors"] is None
        assert "missing" not in smap


@pytest.mark.asyncio
async def test_fetch_stale_map_graceful_empty_and_none():
    async with _temp_db() as db:
        assert await fetch_stale_map(db, []) == {}
        assert await fetch_stale_map(None, ["s1"]) == {}


@pytest.mark.asyncio
async def test_filter_injectable_drops_stale_preserving_order_and_type():
    async with _temp_db() as db:
        await _add_mem(db, "keep1", content="k1")
        await _add_mem(db, "drop", content="d", stale_status="stale")
        await _add_mem(db, "keep2", content="k2")

        obj_items = [
            SimpleNamespace(id="keep1"),
            SimpleNamespace(id="drop"),
            SimpleNamespace(id="keep2"),
        ]
        out = await filter_injectable(db, obj_items)
        assert [it.id for it in out] == ["keep1", "keep2"]

        dict_items = [{"id": "keep1"}, {"id": "drop"}, {"id": "keep2"}]
        out2 = await filter_injectable(db, dict_items)
        assert [it["id"] for it in out2] == ["keep1", "keep2"]


@pytest.mark.asyncio
async def test_filter_injectable_graceful_db_none_returns_input():
    items = [SimpleNamespace(id="a")]
    # db None → stale set empty → original list object returned unchanged.
    assert await filter_injectable(None, items) is items


@pytest.mark.asyncio
async def test_attach_stale_fills_status_and_anchors_from_db():
    async with _temp_db() as db:
        await _add_mem(
            db,
            "m1",
            content="c1",
            anchors=_AGED_ANCHOR,
            stale_status="fresh",
            created_at="2026-01-01T00:00:00Z",
        )
        # surface-style dict lacks anchors/stale_status; attach_stale fills them.
        mems = [{"id": "m1", "category": "decision", "content": "c1"}]
        await attach_stale(db, mems)
        assert mems[0]["stale_status"] == "fresh"
        assert mems[0]["anchors"] == _AGED_ANCHOR


@pytest.mark.asyncio
async def test_render_marks_aged_but_not_fresh_or_verified_stale():
    """render_memory_lines: aged 미검증 앵커에만 경고 토큰. stale은 여기서 거르지
    않지만(선별 단계 책임) fresh 검증분엔 경고가 없다."""
    async with _temp_db() as db:
        await _add_mem(
            db,
            "aged1",
            content="aged decision",
            anchors=_AGED_ANCHOR,
            created_at="2026-01-01T00:00:00Z",
        )
        await _add_mem(
            db,
            "fresh1",
            content="fresh decision",
            anchors=_AGED_ANCHOR,
            stale_status="fresh",
            created_at="2026-01-01T00:00:00Z",
        )
        items = [
            SimpleNamespace(
                id="aged1",
                category="decision",
                content="aged decision",
                created_at="2026-01-01T00:00:00Z",
                similarity_score=0.9,
            ),
            SimpleNamespace(
                id="fresh1",
                category="decision",
                content="fresh decision",
                created_at="2026-01-01T00:00:00Z",
                similarity_score=0.9,
            ),
        ]
        lines = await render_memory_lines(db, items, now=_NOW)
        aged_line = next(line for line in lines if "aged decision" in line)
        fresh_line = next(line for line in lines if "fresh decision" in line)
        assert "미검증 anchor" in aged_line
        assert "미검증 anchor" not in fresh_line


@pytest.mark.asyncio
async def test_stale_excluded_at_selection_then_aged_marked_on_render():
    """End-to-end 주입 반영: filter_injectable(선별)이 stale을 제외하고, 이어지는
    render가 aged 미검증 앵커에 경고를 붙인다 — stale은 주입 라인에 나오지 않는다."""
    async with _temp_db() as db:
        await _add_mem(
            db,
            "stale1",
            content="stale decision",
            anchors=_AGED_ANCHOR,
            stale_status="stale",
            created_at="2026-01-01T00:00:00Z",
        )
        await _add_mem(
            db,
            "aged1",
            content="aged decision",
            anchors=_AGED_ANCHOR,
            created_at="2026-01-01T00:00:00Z",
        )
        items = [
            SimpleNamespace(
                id="stale1",
                category="decision",
                content="stale decision",
                created_at="2026-01-01T00:00:00Z",
                similarity_score=0.9,
            ),
            SimpleNamespace(
                id="aged1",
                category="decision",
                content="aged decision",
                created_at="2026-01-01T00:00:00Z",
                similarity_score=0.9,
            ),
        ]
        kept = await filter_injectable(db, items)
        assert [it.id for it in kept] == ["aged1"]  # stale dropped at selection
        lines = await render_memory_lines(db, kept, now=_NOW)
        blob = "\n".join(lines)
        assert "stale decision" not in blob  # excluded from injection
        assert "aged decision" in blob
        assert "미검증 anchor" in blob


@pytest.mark.asyncio
async def test_surface_relevant_memories_excludes_stale():
    """recall.surface 소비부: 클라이언트가 stale로 검증한 메모리는 surface되지 않는다."""
    async with _temp_db() as db:
        await _add_mem(db, "keep", content="keep decision")
        await _add_mem(db, "drop", content="drop decision", stale_status="stale")

        results = [
            SimpleNamespace(
                id="keep",
                category="decision",
                content="keep decision",
                created_at="2026-07-01T00:00:00Z",
                similarity_score=0.9,
            ),
            SimpleNamespace(
                id="drop",
                category="decision",
                content="drop decision",
                created_at="2026-07-01T00:00:00Z",
                similarity_score=0.9,
            ),
        ]
        search_service = SimpleNamespace(
            db=db,
            search=AsyncMock(return_value=SimpleNamespace(results=results)),
        )
        out = await surface_relevant_memories(search_service, "p12", query="decision")
        ids = {m["id"] for m in out}
        assert "keep" in ids
        assert "drop" not in ids
