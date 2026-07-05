"""weekly_review injection_stats + zero_result_queries (t9 / R11).

Two additions to the weekly review are covered against a real temp DB:

* ``summary.injection_stats`` aggregates the v13 utilization verdicts on
  ``injected_memories`` (injected / judged / utilized / hit_rate / by_method).
* ``zero_result_queries`` now reads the real ``search_metrics`` table
  (``result_count`` / ``timestamp``) instead of the non-existent ``search_logs``
  it used to query — which always fell into the ``except`` and returned nothing.
"""

import os
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.database.base import Database
from app.mcp_common.tools import MCPToolHandlers


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


def _handlers(db):
    # A storage stub exposing .db is all _get_database() needs; compression off
    # keeps the optimizer out of a path that doesn't use it.
    return MCPToolHandlers(SimpleNamespace(db=db), enable_compression=False)


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _insert_injected(db, *, utilized, method, project="mem-mesh"):
    now = _now()
    await db.execute(
        """
        INSERT INTO injected_memories (
            id, project_id, ide_session_id, memory_id, turn_index, position,
            injected_via, created_at, utilized, judge_method, judged_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            project,
            "sess",
            str(uuid4()),
            0,
            0,
            "session_start",
            now,
            utilized,
            method,
            now if utilized is not None else None,
        ),
    )
    db.connection.commit()


async def _insert_search_metric(db, *, query, result_count, project="mem-mesh"):
    await db.execute(
        """
        INSERT INTO search_metrics (
            id, timestamp, query, query_length, project_id, result_count,
            response_time_ms, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(uuid4()), _now(), query, len(query), project, result_count, 10, "test"),
    )
    db.connection.commit()


@pytest.mark.asyncio
async def test_weekly_review_injection_stats():
    """injection_stats aggregates verdicts: 4 injected, 3 judged, 2 utilized →
    hit_rate 2/3, and by_method excludes the still-unjudged (NULL) row."""
    async with _temp_db() as db:
        await _insert_injected(db, utilized=1, method="id_ref")
        await _insert_injected(db, utilized=1, method="keyword")
        await _insert_injected(db, utilized=0, method="none")
        await _insert_injected(db, utilized=None, method=None)  # unjudged
        # A different project's row must not leak into mem-mesh's stats.
        await _insert_injected(db, utilized=1, method="id_ref", project="other")

        report = await _handlers(db).weekly_review("mem-mesh")
        stats = report["summary"]["injection_stats"]

        assert stats["injected"] == 4
        assert stats["judged"] == 3
        assert stats["utilized"] == 2
        assert stats["hit_rate"] == round(2 / 3, 4)
        assert stats["by_method"] == {"id_ref": 1, "keyword": 1, "none": 1}


@pytest.mark.asyncio
async def test_weekly_review_injection_stats_empty():
    """No injected rows → a zeroed injection_stats block (never missing/None)."""
    async with _temp_db() as db:
        report = await _handlers(db).weekly_review("mem-mesh")
        assert report["summary"]["injection_stats"] == {
            "injected": 0,
            "judged": 0,
            "utilized": 0,
            "hit_rate": 0.0,
            "by_method": {},
        }


@pytest.mark.asyncio
async def test_weekly_review_enrichment_coverage():
    """summary.enrichment_coverage — 커버리지 개선 추이를 세션 안에서 확인."""
    from app.core.services.enrich_store import EnrichmentStore

    async with _temp_db() as db:
        # 빈 프로젝트 → zeroed block (누락/None 금지)
        empty = await _handlers(db).weekly_review("mem-mesh")
        assert empty["summary"]["enrichment_coverage"] == {
            "total": 0,
            "enriched": 0,
            "ratio": 0.0,
        }

        for mid in ("e1", "e2"):
            await db.execute(
                "INSERT INTO memories (id, content, content_hash, project_id, "
                "category, source, embedding, created_at, updated_at) "
                "VALUES (?, 'c', ?, 'mem-mesh', 'decision', 't', ?, "
                "'2026-07-01', '2026-07-01')",
                (mid, f"h-{mid}", b"\x00" * 4),
            )
        await EnrichmentStore(db).upsert(memory_id="e1", title="T")

        report = await _handlers(db).weekly_review("mem-mesh")
        cov = report["summary"]["enrichment_coverage"]
        assert cov == {"total": 2, "enriched": 1, "ratio": 0.5}


@pytest.mark.asyncio
async def test_weekly_review_zero_result_queries_from_search_metrics():
    """zero_result_queries returns real search_metrics rows with result_count=0,
    excluding hits and other projects — the previously-dead search_logs query."""
    async with _temp_db() as db:
        await _insert_search_metric(db, query="없는 검색어 하나", result_count=0)
        await _insert_search_metric(db, query="없는 검색어 둘", result_count=0)
        await _insert_search_metric(db, query="결과 있는 쿼리", result_count=5)
        await _insert_search_metric(
            db, query="타 프로젝트", result_count=0, project="other"
        )

        report = await _handlers(db).weekly_review("mem-mesh")

        assert report["summary"]["zero_result_searches"] == 2
        queries = {q["query"] for q in report["zero_result_queries"]}
        assert queries == {"없는 검색어 하나", "없는 검색어 둘"}
        # Each entry carries the mapped timestamp under created_at.
        assert all(q["created_at"] for q in report["zero_result_queries"])
