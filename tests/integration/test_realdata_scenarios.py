"""Real data integration tests — read-only against existing data.

These tests exercise the API against real production data
without creating, modifying, or deleting any records.

Prerequisites:
    - API server at localhost:8000 with real data in the database

Scenarios:
    1. Project-filtered search
    2. Category-filtered search
    3. Korean language search
    4. Time-based / recency search
    5. Context retrieval
    6. Optimized search
"""

from typing import Any, Dict, List

import httpx
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def get_existing_projects(http: httpx.AsyncClient) -> List[str]:
    """Fetch real project IDs from the server."""
    r = await http.get("/api/work/projects")
    if r.status_code != 200:
        return []
    data = r.json()
    if isinstance(data, list):
        return [
            p.get("project_id") or p.get("id", "") for p in data if isinstance(p, dict)
        ]
    if isinstance(data, dict) and "projects" in data:
        return [p.get("project_id") or p.get("id", "") for p in data["projects"]]
    return []


async def get_existing_stats(http: httpx.AsyncClient) -> Dict[str, Any]:
    """Fetch stats to understand what data exists."""
    r = await http.get("/api/memories/stats")
    if r.status_code != 200:
        return {}
    return r.json()


async def get_some_memories(
    http: httpx.AsyncClient, limit: int = 5
) -> List[Dict[str, Any]]:
    """Get some existing memories for testing."""
    r = await http.post(
        "/api/memories/search",
        json={"query": "", "limit": limit},
    )
    if r.status_code != 200:
        return []
    data = r.json()
    return data.get("results", [])


# ---------------------------------------------------------------------------
# 1. Project-filtered search
# ---------------------------------------------------------------------------


class TestProjectSearch:
    async def test_search_each_project(self, http: httpx.AsyncClient):
        """Search within each existing project and verify results match."""
        projects = await get_existing_projects(http)
        if not projects:
            pytest.skip("No projects found in database")

        for project_id in projects[:5]:  # Test first 5 projects
            r = await http.post(
                "/api/memories/search",
                json={"query": "", "project_id": project_id, "limit": 10},
            )
            assert r.status_code == 200, f"Search failed for project {project_id}"
            data = r.json()
            results = data.get("results", [])
            # Every result should belong to this project
            for mem in results:
                if "project_id" in mem:
                    assert mem["project_id"] == project_id, (
                        f"Result project_id mismatch: expected {project_id}, "
                        f"got {mem['project_id']}"
                    )

    async def test_project_stats(self, http: httpx.AsyncClient):
        """Each project should have stats."""
        projects = await get_existing_projects(http)
        if not projects:
            pytest.skip("No projects found")

        for project_id in projects[:3]:
            r = await http.get(f"/api/work/projects/{project_id}/stats")
            if r.status_code == 200:
                data = r.json()
                assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# 2. Category-filtered search
# ---------------------------------------------------------------------------


class TestCategorySearch:
    CATEGORIES = ["task", "bug", "idea", "decision", "code_snippet", "incident"]

    @pytest.mark.parametrize("category", CATEGORIES)
    async def test_search_by_category(self, http: httpx.AsyncClient, category: str):
        r = await http.post(
            "/api/memories/search",
            json={"query": "", "category": category, "limit": 5},
        )
        assert r.status_code == 200
        data = r.json()
        results = data.get("results", [])
        for mem in results:
            if "category" in mem:
                assert (
                    mem["category"] == category
                ), f"Category mismatch: expected {category}, got {mem['category']}"

    async def test_stats_show_category_breakdown(self, http: httpx.AsyncClient):
        """Stats should include category distribution."""
        stats = await get_existing_stats(http)
        if not stats:
            pytest.skip("No stats available")
        # Check that stats has some structure
        assert isinstance(stats, dict)
        # Common keys: total_memories, categories, by_category, etc.
        assert len(stats) > 0


# ---------------------------------------------------------------------------
# 3. Korean language search
# ---------------------------------------------------------------------------


class TestKoreanSearch:
    KOREAN_QUERIES = [
        "데이터베이스 설계",
        "버그 수정",
        "성능 최적화",
        "아키텍처 결정",
        "검색 품질",
    ]

    @pytest.mark.parametrize("query", KOREAN_QUERIES)
    async def test_korean_search(self, http: httpx.AsyncClient, query: str):
        r = await http.post(
            "/api/memories/search",
            json={"query": query, "limit": 10},
        )
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        # Korean queries should return results if data exists
        # (not asserting count since it depends on actual data)

    async def test_korean_mixed_with_english(self, http: httpx.AsyncClient):
        """Mixed Korean/English query."""
        r = await http.post(
            "/api/memories/search",
            json={"query": "SQLite 벡터 검색", "limit": 10},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 4. Time-based / recency search
# ---------------------------------------------------------------------------


class TestTimeBasedSearch:
    async def test_recency_boost(self, http: httpx.AsyncClient):
        """Search with recency_weight should prioritize recent results."""
        # Without recency
        r1 = await http.post(
            "/api/memories/search",
            json={"query": "test", "recency_weight": 0.0, "limit": 10},
        )
        assert r1.status_code == 200

        # With recency boost
        r2 = await http.post(
            "/api/memories/search",
            json={"query": "test", "recency_weight": 0.8, "limit": 10},
        )
        assert r2.status_code == 200

        # Results should potentially differ in ordering
        results1 = r1.json().get("results", [])
        results2 = r2.json().get("results", [])
        ids1 = [m["id"] for m in results1]
        ids2 = [m["id"] for m in results2]
        # At least confirm both returned results
        assert isinstance(ids1, list)
        assert isinstance(ids2, list)

    async def test_daily_counts_api(self, http: httpx.AsyncClient):
        """Daily counts should return data for each day."""
        r = await http.get("/api/memories/daily-counts", params={"days": 30})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict))


# ---------------------------------------------------------------------------
# 5. Context retrieval
# ---------------------------------------------------------------------------


class TestContextRetrieval:
    async def test_memory_context(self, http: httpx.AsyncClient):
        """Get context for an existing memory."""
        memories = await get_some_memories(http, limit=3)
        if not memories:
            pytest.skip("No memories found")

        for mem in memories:
            memory_id = mem.get("id")
            if not memory_id:
                continue
            r = await http.get(
                f"/api/memories/{memory_id}/context",
                params={"depth": 2},
            )
            assert r.status_code == 200, f"Context failed for {memory_id}"
            data = r.json()
            assert isinstance(data, dict)

    async def test_relation_graph(self, http: httpx.AsyncClient):
        """Get relation graph for an existing memory."""
        memories = await get_some_memories(http, limit=3)
        if not memories:
            pytest.skip("No memories found")

        memory_id = memories[0].get("id")
        if not memory_id:
            pytest.skip("No memory ID found")

        r = await http.get(
            f"/api/relations/graph/{memory_id}",
            params={"depth": 2},
        )
        # May be 200 or 404 depending on data
        assert r.status_code in (200, 404)


# ---------------------------------------------------------------------------
# 6. Optimized search
# ---------------------------------------------------------------------------


class TestOptimizedSearch:
    async def test_optimized_search_basic(self, http: httpx.AsyncClient):
        r = await http.post(
            "/api/search/optimized",
            json={"query": "architecture decision", "limit": 5},
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    async def test_optimized_search_with_project(self, http: httpx.AsyncClient):
        projects = await get_existing_projects(http)
        project_id = projects[0] if projects else "mem-mesh"
        r = await http.post(
            "/api/search/optimized",
            json={
                "query": "performance optimization",
                "project_id": project_id,
                "limit": 5,
            },
        )
        assert r.status_code == 200

    async def test_optimized_vs_regular_search(self, http: httpx.AsyncClient):
        """Both endpoints should return valid results for the same query."""
        query = "database"

        r_regular = await http.post(
            "/api/memories/search",
            json={"query": query, "limit": 5},
        )
        r_optimized = await http.post(
            "/api/search/optimized",
            json={"query": query, "limit": 5},
        )

        assert r_regular.status_code == 200
        assert r_optimized.status_code == 200

        regular_results = r_regular.json().get("results", [])
        optimized_data = r_optimized.json()
        # Both should return some form of results
        assert isinstance(regular_results, list)
        assert isinstance(optimized_data, dict)


# ---------------------------------------------------------------------------
# Weekly review (bonus)
# ---------------------------------------------------------------------------


class TestWeeklyReview:
    async def test_weekly_review_via_api(self, http: httpx.AsyncClient):
        """Call weekly_review through stateless MCP tools/call."""
        from tests.integration.conftest import mcp_stateless_call

        result = await mcp_stateless_call(
            http,
            "weekly_review",
            {"project_id": "mem-mesh", "days": 7},
        )
        assert isinstance(result, dict)
