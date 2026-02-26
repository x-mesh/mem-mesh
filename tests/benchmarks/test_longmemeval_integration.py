"""Integration tests for LongMemEval benchmark pipeline.

Tests the full flow: index → retrieve → cleanup using real DirectStorageBackend.
"""

from pathlib import Path

import pytest

from app.core.schemas.requests import SearchParams
from app.core.schemas.responses import SearchResponse
from app.core.storage.direct import DirectStorageBackend
from benchmarks.longmemeval.indexer import SessionIndexer
from benchmarks.longmemeval.models import BenchmarkItem
from benchmarks.longmemeval.retriever import Retriever


def make_benchmark_item() -> BenchmarkItem:
    """Create a mock BenchmarkItem for testing."""
    return BenchmarkItem(
        question_id="test_001",
        question_type="single-session-user-centric",
        question="What is Alice's favorite programming language?",
        answer="Python",
        haystack_sessions=[
            [
                "User: Hey Alice, what programming language do you like the most?",
                "Assistant: I really love Python! It's so versatile and readable.",
                "User: Why do you prefer Python over other languages?",
                "Assistant: Python has great libraries for data science and machine learning, plus its syntax is clean.",
            ],
            [
                "User: What did you have for lunch today?",
                "Assistant: I had a nice pasta with marinara sauce.",
                "User: That sounds delicious!",
                "Assistant: It was! I also had a side salad.",
            ],
            [
                "User: Can you recommend a good book?",
                "Assistant: I'd recommend 'Clean Code' by Robert C. Martin.",
                "User: What's it about?",
                "Assistant: It's about writing maintainable and readable code. Great for any developer.",
            ],
        ],
        haystack_dates=[
            "2024/03/15 Friday 14:30",
            "2024/03/16 Saturday 12:00",
            "2024/03/17 Sunday 10:00",
        ],
        answer_session_ids=[0],
    )


async def cleanup_project(storage: DirectStorageBackend, project_id: str) -> None:
    """Delete all memories for a given project_id."""
    params = SearchParams(query="", project_id=project_id, limit=20)
    while True:
        response = await storage.search_memories(params)
        if not response.results:
            break
        for result in response.results:
            await storage.delete_memory(result.id)


def _sqlite_vec_available() -> bool:
    """Check if sqlite-vec is actually usable at runtime."""
    try:
        from app.core.database.base import SQLITE_VEC_AVAILABLE
        return SQLITE_VEC_AVAILABLE
    except ImportError:
        return False


def _patch_search_for_fuzzy(storage: DirectStorageBackend) -> None:
    """Patch DirectStorageBackend to use fuzzy search instead of hybrid.

    When sqlite-vec is not available, hybrid search fails on vector lookup.
    Fuzzy search uses SequenceMatcher on all memories, which works without
    any native extensions.
    """

    async def _fuzzy_search_wrapper(params: SearchParams) -> SearchResponse:
        if not storage.unified_search_service:
            raise RuntimeError("UnifiedSearchService not initialized")
        return await storage.unified_search_service.search(
            query=params.query,
            project_id=params.project_id,
            category=params.category,
            limit=params.limit,
            recency_weight=params.recency_weight,
            search_mode="fuzzy",
            time_range=params.time_range,
            date_from=params.date_from,
            date_to=params.date_to,
            temporal_mode=params.temporal_mode,
        )

    storage._search_with_unified_service = _fuzzy_search_wrapper  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_index_retrieve_cleanup_flow(tmp_path: Path) -> None:
    """Test the full pipeline: index sessions, retrieve with query, then cleanup."""
    db_path = str(tmp_path / "test.db")
    storage = DirectStorageBackend(db_path)
    await storage.initialize()

    project_id = "lme-test-001"

    try:
        # --- Index ---
        item = make_benchmark_item()
        indexer = SessionIndexer()
        num_indexed = await indexer.index(storage, item, project_id)

        # Should have indexed one memory per session (3 sessions)
        assert num_indexed == 3, f"Expected 3 indexed memories, got {num_indexed}"

        # Verify memories exist via search
        params = SearchParams(query="", project_id=project_id, limit=20)
        response = await storage.search_memories(params)
        assert len(response.results) == 3, (
            f"Expected 3 stored memories, got {len(response.results)}"
        )

        # --- Retrieve ---
        # When sqlite-vec is not available, patch to use fuzzy search
        # so the Retriever pipeline can still be fully exercised.
        if not _sqlite_vec_available():
            _patch_search_for_fuzzy(storage)

        retriever = Retriever(storage, top_k=10)
        results, retrieved_session_ids, metrics = await retriever.retrieve(
            query=item.question,
            project_id=project_id,
            answer_session_ids=item.answer_session_ids,
        )

        # Should return search results
        assert len(results) > 0, "Retriever returned no results"

        # Session IDs should be extracted from tags
        assert len(retrieved_session_ids) > 0, "No session IDs extracted"

        # The answer session (0) should be among retrieved sessions
        assert 0 in retrieved_session_ids, (
            f"Answer session 0 not found in retrieved sessions: {retrieved_session_ids}"
        )

        # Metrics should be computed
        assert metrics.retrieval_time_ms > 0, "Retrieval time not recorded"

        # recall_any at k=10 should be 1.0 since answer session should be retrieved
        assert metrics.recall_any[10] == 1.0, (
            f"Expected recall_any@10=1.0, got {metrics.recall_any[10]}"
        )

        # recall_all at k=10 should also be 1.0 (only 1 answer session)
        assert metrics.recall_all[10] == 1.0, (
            f"Expected recall_all@10=1.0, got {metrics.recall_all[10]}"
        )

        # --- Cleanup ---
        await cleanup_project(storage, project_id)

        # Verify all memories are deleted
        response = await storage.search_memories(params)
        assert len(response.results) == 0, (
            f"Expected 0 results after cleanup, got {len(response.results)}"
        )

    finally:
        await storage.shutdown()


@pytest.mark.asyncio
async def test_project_isolation(tmp_path: Path) -> None:
    """Test that memories from different project_ids are isolated."""
    db_path = str(tmp_path / "test_isolation.db")
    storage = DirectStorageBackend(db_path)
    await storage.initialize()

    project_a = "lme-test-proj-a"
    project_b = "lme-test-proj-b"

    try:
        item = make_benchmark_item()
        indexer = SessionIndexer()

        # Create a second item with different content
        item_b = BenchmarkItem(
            question_id="test_002",
            question_type="single-session-user-centric",
            question="What is Bob's favorite food?",
            answer="Sushi",
            haystack_sessions=[
                [
                    "User: Bob, what's your favorite food?",
                    "Assistant: I absolutely love sushi! Fresh salmon sashimi is the best.",
                    "User: Do you make it at home?",
                    "Assistant: Sometimes! I have a sushi mat and everything.",
                ],
                [
                    "User: What time do you usually wake up?",
                    "Assistant: Around 7 AM on weekdays.",
                    "User: That's early!",
                    "Assistant: I like to have a slow morning with coffee.",
                ],
            ],
            haystack_dates=[
                "2024/04/01 Monday 09:00",
                "2024/04/02 Tuesday 10:00",
            ],
            answer_session_ids=[0],
        )

        # Index both items into separate projects
        num_a = await indexer.index(storage, item, project_a)
        num_b = await indexer.index(storage, item_b, project_b)

        assert num_a == 3, f"Expected 3 memories for project A, got {num_a}"
        assert num_b == 2, f"Expected 2 memories for project B, got {num_b}"

        # Search project A - should only return project A results
        params_a = SearchParams(query="", project_id=project_a, limit=20)
        response_a = await storage.search_memories(params_a)
        assert len(response_a.results) == 3, (
            f"Project A should have 3 results, got {len(response_a.results)}"
        )

        # Search project B - should only return project B results
        params_b = SearchParams(query="", project_id=project_b, limit=20)
        response_b = await storage.search_memories(params_b)
        assert len(response_b.results) == 2, (
            f"Project B should have 2 results, got {len(response_b.results)}"
        )

        # Delete project A only
        await cleanup_project(storage, project_a)

        # Project A should be empty
        response_a = await storage.search_memories(params_a)
        assert len(response_a.results) == 0, (
            f"Project A should be empty after cleanup, got {len(response_a.results)}"
        )

        # Project B should still have its memories
        response_b = await storage.search_memories(params_b)
        assert len(response_b.results) == 2, (
            f"Project B should still have 2 results, got {len(response_b.results)}"
        )

    finally:
        # Cleanup project B as well
        await cleanup_project(storage, project_b)
        await storage.shutdown()
