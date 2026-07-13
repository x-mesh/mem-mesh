"""Cross-project search: one query spanning a coupled repo pair.

The council verdict behind this: no project_links table, no include_linked flag,
no RRF fusion of a "linked" corpus — just `WHERE project_id IN (...)`. These
tests pin the two things that can silently break: the SQL filter must widen to
the list, and the cache/metric key must not collide with a single-project search
(a `project_id="frontend"` hit must never be served to a [frontend, backend] query).
"""

import os
import tempfile
from contextlib import asynccontextmanager

import pytest

from app.core.database.base import Database, value_filter_clause
from app.core.services.cache_manager import get_cache_manager


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
        for ext in ["", "-wal", "-shm"]:
            if os.path.exists(path + ext):
                os.unlink(path + ext)


async def _add_memory(db, mid, project_id, content):
    await db.execute(
        """
        INSERT INTO memories (
            id, content, content_hash, project_id, category, source,
            embedding, tags, status, created_at, updated_at, content_bytes
        )
        VALUES (?, ?, ?, ?, 'decision', 'test', ?, '[]', 'canonical',
                '2026-01-01', '2026-01-01', 0)
        """,
        (mid, content, f"hash-{mid}", project_id, b"1"),
    )


def test_value_filter_clause_scalar_and_list():
    assert value_filter_clause("frontend", "project_id") == (
        "project_id = ?",
        ["frontend"],
    )
    cond, params = value_filter_clause(["frontend", "backend"], "project_id")
    assert cond == "project_id IN (?,?)"
    assert params == ["frontend", "backend"]
    # Empty / all-empty filters must not emit a clause (that would match nothing).
    assert value_filter_clause(None, "project_id") == ("", [])
    assert value_filter_clause([], "project_id") == ("", [])
    assert value_filter_clause(["", None], "project_id") == ("", [])


@pytest.mark.asyncio
async def test_recent_memories_filter_spans_both_projects():
    async with _temp_db() as db:
        await _add_memory(db, "f1", "frontend", "frontend auth token handling")
        await _add_memory(db, "b1", "backend", "backend auth token expiry")
        await _add_memory(db, "o1", "other", "unrelated project memory")

        both = await db.get_recent_memories(
            limit=10, filters={"project_id": ["frontend", "backend"]}
        )
        ids = {row["id"] for row in both}
        assert ids == {"f1", "b1"}  # 'other' must stay out

        single = await db.get_recent_memories(
            limit=10, filters={"project_id": "frontend"}
        )
        assert {row["id"] for row in single} == {"f1"}

        count = await db.count_memories(filters={"project_id": ["frontend", "backend"]})
        assert count == 2


@pytest.mark.asyncio
async def test_cross_project_cache_key_does_not_collide_with_single_project():
    """A [frontend, backend] search must not be served the cached result of a
    frontend-only search — the scope is part of the key."""

    from app.core.schemas.responses import SearchResponse, SearchResult

    cache = get_cache_manager()
    cache.clear_all_caches()

    single = SearchResponse(
        results=[
            SearchResult(
                id="f1",
                content="frontend only",
                similarity_score=1.0,
                created_at="2026-01-01",
                project_id="frontend",
                category="decision",
                source="test",
            )
        ],
        total=1,
    )
    await cache.cache_search_results(
        query="auth", results=single, project_id="frontend", category=None, limit=5
    )

    # Same query, cross-project scope → must be a MISS, not the frontend entry.
    hit = await cache.get_cached_search(
        query="auth", project_id="backend,frontend", category=None, limit=5
    )
    assert hit is None

    # The single-project key still resolves.
    same = await cache.get_cached_search(
        query="auth", project_id="frontend", category=None, limit=5
    )
    assert same is not None
    cache.clear_all_caches()


@pytest.mark.asyncio
async def test_unified_search_text_paths_bind_a_project_list():
    """Regression (review F1): UnifiedSearch's own inline SQL bound project_id as
    a scalar, so a list raised `type 'list' is not supported` — the FTS/exact/
    fuzzy contribution of a cross-project search died silently behind hybrid's
    vector half. use_unified_search=True is the default, so this IS the path."""

    from app.core.embeddings.service import EmbeddingService
    from app.core.services.unified_search import UnifiedSearchService

    async with _temp_db() as db:
        await _add_memory(db, "f1", "frontend", "auth token ttl on the client")
        await _add_memory(db, "b1", "backend", "auth token ttl on the server")
        await _add_memory(
            db, "o1", "billing", "refund policy has nothing to do with auth"
        )

        svc = UnifiedSearchService(db, EmbeddingService(preload=False))

        # Text-only modes exercise the inline SQL that used to break.
        for mode in ("exact", "fuzzy"):
            result = await svc.search(
                query="auth token",
                project_ids=["frontend", "backend"],
                search_mode=mode,
                limit=10,
            )
            projects = {r.project_id for r in result.results}
            assert projects <= {"frontend", "backend"}, f"{mode} leaked {projects}"


@pytest.mark.asyncio
async def test_id_prefix_shortcut_honours_the_cross_project_scope():
    """Regression (review F2): the memory-id fast path passed only project_id, so
    a query carrying an id token returned memories from outside the requested
    scope."""

    from app.core.embeddings.service import EmbeddingService
    from app.core.services.unified_search import UnifiedSearchService

    async with _temp_db() as db:
        await _add_memory(
            db, "aaaaaaaa-1111-4111-8111-111111111111", "billing", "out of scope memory"
        )
        svc = UnifiedSearchService(db, EmbeddingService(preload=False))

        result = await svc.search(
            query="see memory aaaaaaaa for details",
            project_ids=["frontend", "backend"],
            limit=5,
        )
        assert all(r.project_id != "billing" for r in result.results)
