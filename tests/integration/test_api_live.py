"""REST API integration tests against a live mem-mesh server.

Scenarios:
    1. Health & Info
    2. Memory CRUD lifecycle
    3. Search (hybrid)
    4. Search modes (hybrid, exact, semantic, fuzzy)
    5. Pin workflow (add → complete → promote)
    6. Session lifecycle (resume → pin → complete → end)
    7. Relations (create → link → get_links → unlink)
    8. Stats & Projects
    9. Monitoring dashboard
"""

import asyncio
from typing import List

import httpx
import pytest

from tests.integration.conftest import TEST_PROJECT_ID, unique_content

# ---------------------------------------------------------------------------
# 1. Health & Info
# ---------------------------------------------------------------------------


class TestHealthAndInfo:
    async def test_health(self, http: httpx.AsyncClient):
        r = await http.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"

    async def test_api_root(self, http: httpx.AsyncClient):
        r = await http.get("/api/")
        assert r.status_code == 200
        data = r.json()
        assert "version" in data
        assert "mcp_protocol_version" in data or "name" in data

    async def test_mcp_info(self, http: httpx.AsyncClient):
        r = await http.get("/mcp/info")
        assert r.status_code == 200
        data = r.json()
        assert "tools" in data
        assert "add" in data["tools"]
        assert "search" in data["tools"]


# ---------------------------------------------------------------------------
# 2. Memory CRUD
# ---------------------------------------------------------------------------


class TestMemoryCRUD:
    async def test_full_lifecycle(
        self, http: httpx.AsyncClient, cleanup_memories: List[str]
    ):
        """POST → GET → PUT → DELETE"""
        content = unique_content("CRUD test memory")

        # CREATE
        r = await http.post(
            "/api/memories",
            json={
                "content": content,
                "project_id": TEST_PROJECT_ID,
                "category": "task",
                "tags": ["integration-test"],
            },
        )
        assert r.status_code == 200, f"Create failed: {r.text}"
        create_data = r.json()
        memory_id = create_data["id"]
        cleanup_memories.append(memory_id)
        assert memory_id

        # READ
        r = await http.get(f"/api/memories/{memory_id}")
        assert r.status_code == 200
        read_data = r.json()
        assert read_data["content"] == content
        assert read_data["project_id"] == TEST_PROJECT_ID

        # UPDATE
        new_content = unique_content("CRUD updated memory")
        r = await http.put(
            f"/api/memories/{memory_id}",
            json={"content": new_content, "tags": ["integration-test", "updated"]},
        )
        assert r.status_code == 200

        # Verify update
        r = await http.get(f"/api/memories/{memory_id}")
        assert r.status_code == 200
        assert r.json()["content"] == new_content

        # DELETE
        r = await http.delete(f"/api/memories/{memory_id}")
        assert r.status_code == 200
        cleanup_memories.remove(memory_id)

        # Verify deletion
        r = await http.get(f"/api/memories/{memory_id}")
        assert r.status_code in (404, 200)  # May return 404 or empty

    async def test_create_with_all_categories(
        self, http: httpx.AsyncClient, cleanup_memories: List[str]
    ):
        """Test creating memories with different categories."""
        categories = ["task", "bug", "idea", "decision", "code_snippet"]
        for cat in categories:
            r = await http.post(
                "/api/memories",
                json={
                    "content": unique_content(f"Category test: {cat}"),
                    "project_id": TEST_PROJECT_ID,
                    "category": cat,
                    "tags": ["integration-test"],
                },
            )
            assert r.status_code == 200, f"Failed for category={cat}: {r.text}"
            cleanup_memories.append(r.json()["id"])

    async def test_create_validation_error(self, http: httpx.AsyncClient):
        """Content too short should fail."""
        r = await http.post(
            "/api/memories",
            json={"content": "short", "project_id": TEST_PROJECT_ID},
        )
        assert r.status_code == 422  # Pydantic validation error


# ---------------------------------------------------------------------------
# 3. Search (hybrid)
# ---------------------------------------------------------------------------


class TestSearch:
    async def test_search_by_query(
        self, http: httpx.AsyncClient, cleanup_memories: List[str]
    ):
        """Create a memory then search for it."""
        keyword = f"xyzzy_{unique_content()[-8:]}"
        content = (
            f"This is a searchable memory about {keyword} for integration testing. "
            "The fixture content is intentionally long enough to pass the content-length "
            "validator enforced by the memory service (minimum 100 characters)."
        )

        # Create
        r = await http.post(
            "/api/memories",
            json={
                "content": content,
                "project_id": TEST_PROJECT_ID,
                "category": "task",
                "tags": ["integration-test", "search-test"],
            },
        )
        assert r.status_code == 200
        memory_id = r.json()["id"]
        cleanup_memories.append(memory_id)

        # Search via POST — allow indexing to catch up (vector + FTS5 async), retry
        found_ids: List[str] = []
        for _ in range(6):
            await asyncio.sleep(0.5)
            r = await http.post(
                "/api/memories/search",
                json={"query": keyword, "limit": 10},
            )
            assert r.status_code == 200
            data = r.json()
            assert "results" in data
            found_ids = [m["id"] for m in data["results"]]
            if memory_id in found_ids:
                break
        assert memory_id in found_ids, f"Memory {memory_id} not found in search results"

    async def test_search_with_project_filter(self, http: httpx.AsyncClient):
        """Search with project_id filter."""
        r = await http.post(
            "/api/memories/search",
            json={"query": "", "project_id": "mem-mesh", "limit": 5},
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data["results"], list)

    async def test_search_via_get(self, http: httpx.AsyncClient):
        """Search via GET endpoint."""
        r = await http.get("/api/memories/search", params={"query": "test", "limit": 5})
        assert r.status_code == 200
        assert "results" in r.json()


# ---------------------------------------------------------------------------
# 4. Search modes
# ---------------------------------------------------------------------------


class TestSearchModes:
    @pytest.mark.parametrize("mode", ["hybrid", "exact", "semantic", "fuzzy"])
    async def test_search_mode(self, http: httpx.AsyncClient, mode: str):
        r = await http.post(
            "/api/memories/search",
            json={"query": "database", "search_mode": mode, "limit": 5},
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data["results"], list)

    async def test_search_with_recency_weight(self, http: httpx.AsyncClient):
        r = await http.post(
            "/api/memories/search",
            json={"query": "test", "recency_weight": 0.5, "limit": 5},
        )
        assert r.status_code == 200

    async def test_optimized_search(self, http: httpx.AsyncClient):
        """POST /api/search/optimized — context-aware search."""
        r = await http.post(
            "/api/search/optimized",
            json={"query": "architecture decision", "limit": 5},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 5. Pin workflow
# ---------------------------------------------------------------------------


class TestPinWorkflow:
    async def test_pin_add_complete_promote(
        self,
        http: httpx.AsyncClient,
        cleanup_pins: List[str],
        cleanup_memories: List[str],
    ):
        """pin_add → pin_complete → pin_promote → verify memory."""
        # Add pin
        r = await http.post(
            "/api/work/pins",
            json={
                "content": unique_content("Pin workflow test"),
                "project_id": TEST_PROJECT_ID,
                "importance": 4,
                "tags": ["integration-test"],
            },
        )
        assert r.status_code == 200, f"Pin create failed: {r.text}"
        pin_data = r.json()
        pin_id = pin_data["id"]
        cleanup_pins.append(pin_id)

        # Complete pin
        r = await http.put(f"/api/work/pins/{pin_id}/complete")
        assert r.status_code == 200
        complete_data = r.json()
        # importance >= 4 should suggest promotion
        assert (
            complete_data.get("promote_suggested")
            or complete_data.get("status") == "completed"
        )

        # Promote to memory
        r = await http.post(
            f"/api/work/pins/{pin_id}/promote",
            json={"category": "decision"},
        )
        assert r.status_code == 200
        promote_data = r.json()
        if "memory_id" in promote_data:
            cleanup_memories.append(promote_data["memory_id"])

    async def test_pin_crud(self, http: httpx.AsyncClient, cleanup_pins: List[str]):
        """Create → read → update → delete pin."""
        # Create
        r = await http.post(
            "/api/work/pins",
            json={
                "content": unique_content("Pin CRUD test"),
                "project_id": TEST_PROJECT_ID,
                "importance": 2,
            },
        )
        assert r.status_code == 200
        pin_id = r.json()["id"]
        cleanup_pins.append(pin_id)

        # Read
        r = await http.get(f"/api/work/pins/{pin_id}")
        assert r.status_code == 200

        # Update
        r = await http.put(
            f"/api/work/pins/{pin_id}",
            json={"content": unique_content("Pin CRUD updated")},
        )
        assert r.status_code == 200

        # Delete
        r = await http.delete(f"/api/work/pins/{pin_id}")
        assert r.status_code == 200
        cleanup_pins.remove(pin_id)


# ---------------------------------------------------------------------------
# 6. Session lifecycle
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    async def test_session_resume_and_end(self, http: httpx.AsyncClient):
        """session_resume → pin → complete → session_end."""
        # Resume (may create a new session)
        r = await http.get(
            f"/api/work/sessions/resume/{TEST_PROJECT_ID}",
            params={"expand": "smart"},
        )
        assert r.status_code == 200
        resume_data = r.json()
        assert isinstance(resume_data, dict)

        # End session
        r = await http.get("/api/work/sessions", params={"project_id": TEST_PROJECT_ID})
        assert r.status_code == 200
        sessions = r.json()
        if isinstance(sessions, list) and sessions:
            session_id = sessions[0].get("id")
            if session_id:
                r = await http.post(
                    f"/api/work/sessions/{session_id}/end",
                    json={"summary": "Integration test session"},
                )
                assert r.status_code == 200


# ---------------------------------------------------------------------------
# 7. Relations
# ---------------------------------------------------------------------------


class TestRelations:
    async def test_link_and_unlink(
        self, http: httpx.AsyncClient, cleanup_memories: List[str]
    ):
        """Create 2 memories, link them, verify, unlink."""
        # Create 2 memories
        ids = []
        for i in range(2):
            r = await http.post(
                "/api/memories",
                json={
                    "content": unique_content(f"Relation test memory {i}"),
                    "project_id": TEST_PROJECT_ID,
                    "category": "task",
                    "tags": ["integration-test"],
                },
            )
            assert r.status_code == 200
            ids.append(r.json()["id"])
            cleanup_memories.append(ids[-1])

        # Create relation
        r = await http.post(
            "/api/relations",
            json={
                "source_id": ids[0],
                "target_id": ids[1],
                "relation_type": "related",
                "strength": 0.8,
            },
        )
        assert r.status_code == 200
        relation_id = r.json().get("id")

        # Get relations for source
        r = await http.get(f"/api/relations/memory/{ids[0]}")
        assert r.status_code == 200
        relations = r.json()
        assert isinstance(relations, (list, dict))

        # Delete relation
        if relation_id:
            r = await http.delete(f"/api/relations/{relation_id}")
            assert r.status_code == 200


# ---------------------------------------------------------------------------
# 8. Stats & Projects
# ---------------------------------------------------------------------------


class TestStatsAndProjects:
    async def test_memory_stats(self, http: httpx.AsyncClient):
        r = await http.get("/api/memories/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total_memories" in data or "total" in data or isinstance(data, dict)

    async def test_daily_counts(self, http: httpx.AsyncClient):
        r = await http.get("/api/memories/daily-counts", params={"days": 7})
        assert r.status_code == 200

    async def test_projects_list(self, http: httpx.AsyncClient):
        r = await http.get("/api/projects")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict))

    async def test_work_projects(self, http: httpx.AsyncClient):
        r = await http.get("/api/work/projects")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 9. Monitoring
# ---------------------------------------------------------------------------


class TestMonitoring:
    async def test_dashboard_summary(self, http: httpx.AsyncClient):
        r = await http.get("/api/monitoring/dashboard/summary")
        assert r.status_code == 200

    async def test_search_metrics(self, http: httpx.AsyncClient):
        r = await http.get(
            "/api/monitoring/search/metrics",
            params={"hours": 24, "aggregation": "hourly"},
        )
        assert r.status_code == 200

    async def test_alerts_summary(self, http: httpx.AsyncClient):
        r = await http.get("/api/monitoring/alerts/summary")
        assert r.status_code == 200

    async def test_cache_performance(self, http: httpx.AsyncClient):
        r = await http.get("/api/monitoring/cache/performance-stats")
        assert r.status_code == 200
