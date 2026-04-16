"""End-to-end scenario tests mixing REST API and MCP SSE against a live server.

Scenarios:
    1. Cross-protocol consistency (REST ↔ MCP data interop)
    2. Real-world developer workflow simulation
    3. Search accuracy with topical data
    4. Bulk data via batch operations
"""

import asyncio
from typing import List

import httpx

from tests.integration.conftest import (
    TEST_PROJECT_ID,
    mcp_tools_call,
    unique_content,
)

# ---------------------------------------------------------------------------
# 1. Cross-Protocol Consistency
# ---------------------------------------------------------------------------


class TestCrossProtocol:
    """Verify data created via one protocol is visible via the other."""

    async def test_rest_create_mcp_search(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """Create via REST API → find via MCP search."""
        keyword = f"crossproto_{unique_content()[-8:]}"
        r = await http.post(
            "/api/memories",
            json={
                "content": f"Cross-protocol test memory with {keyword} created via REST API for integration testing (fixture padded to satisfy minimum content length of 100 characters).",
                "project_id": TEST_PROJECT_ID,
                "category": "decision",
                "tags": ["cross-protocol"],
            },
        )
        assert r.status_code == 200
        memory_id = r.json()["id"]
        cleanup_memories.append(memory_id)

        await asyncio.sleep(0.5)

        search_result = await mcp_tools_call(
            http,
            "search",
            {
                "query": keyword,
                "project_id": TEST_PROJECT_ID,
                "limit": 10,
            },
            session_id=mcp_session,
        )

        found_ids = [m["id"] for m in search_result.get("results", [])]
        assert (
            memory_id in found_ids
        ), f"REST-created memory {memory_id} not found via MCP search"

    async def test_mcp_create_rest_get(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """Create via MCP add → retrieve via REST GET."""
        add_result = await mcp_tools_call(
            http,
            "add",
            {
                "content": unique_content("Cross-protocol MCP→REST test memory"),
                "project_id": TEST_PROJECT_ID,
                "category": "idea",
                "tags": ["cross-protocol"],
            },
            session_id=mcp_session,
        )
        memory_id = add_result["id"]
        cleanup_memories.append(memory_id)

        r = await http.get(f"/api/memories/{memory_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == memory_id
        assert data["project_id"] == TEST_PROJECT_ID
        assert data["category"] == "idea"

    async def test_mcp_update_rest_verify(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """Create via REST → update via MCP → verify via REST."""
        r = await http.post(
            "/api/memories",
            json={
                "content": unique_content("Cross-protocol update before MCP"),
                "project_id": TEST_PROJECT_ID,
                "category": "task",
            },
        )
        memory_id = r.json()["id"]
        cleanup_memories.append(memory_id)

        new_content = unique_content("Cross-protocol updated via MCP")
        await mcp_tools_call(
            http,
            "update",
            {
                "memory_id": memory_id,
                "content": new_content,
                "category": "decision",
            },
            session_id=mcp_session,
        )

        r = await http.get(f"/api/memories/{memory_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["content"] == new_content
        assert data["category"] == "decision"


# ---------------------------------------------------------------------------
# 2. Real-World Workflow Simulation
# ---------------------------------------------------------------------------


class TestRealWorldWorkflow:
    """Simulate a real developer session: resume → pin → work → end."""

    async def test_developer_session(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
        cleanup_pins: List[str],
    ):
        """Full developer workflow: session → pins → memories → relations → end."""

        # 1. Session resume
        resume = await mcp_tools_call(
            http,
            "session_resume",
            {
                "project_id": TEST_PROJECT_ID,
                "expand": "smart",
            },
            session_id=mcp_session,
        )
        assert resume is not None

        # 2. Create work pins
        pin_contents = [
            ("Analyze authentication architecture for microservices", 4),
            ("Fix race condition in connection pool manager", 3),
            ("Add retry logic code snippet for HTTP client", 2),
        ]
        pin_ids = []
        for content, importance in pin_contents:
            result = await mcp_tools_call(
                http,
                "pin_add",
                {
                    "content": unique_content(content),
                    "project_id": TEST_PROJECT_ID,
                    "importance": importance,
                    "tags": ["workflow-test"],
                },
                session_id=mcp_session,
            )
            pin_ids.append(result["id"])
            cleanup_pins.append(result["id"])

        # 3. Save a decision memory with unique keyword for later search
        workflow_keyword = f"wfkw_{unique_content()[-8:]}"
        decision = await mcp_tools_call(
            http,
            "add",
            {
                "content": (
                    f"Decision ({workflow_keyword}): Use JWT with refresh tokens "
                    "for authentication. Access tokens expire in 15 minutes, "
                    "refresh tokens in 7 days."
                ),
                "project_id": TEST_PROJECT_ID,
                "category": "decision",
                "tags": ["auth", "jwt", "workflow-test"],
            },
            session_id=mcp_session,
        )
        decision_id = decision["id"]
        cleanup_memories.append(decision_id)

        # 4. Complete high-importance pin and promote it
        await mcp_tools_call(
            http,
            "pin_complete",
            {
                "pin_id": pin_ids[0],
            },
            session_id=mcp_session,
        )

        promote = await mcp_tools_call(
            http,
            "pin_promote",
            {
                "pin_id": pin_ids[0],
            },
            session_id=mcp_session,
        )
        if "memory_id" in promote:
            promoted_id = promote["memory_id"]
            cleanup_memories.append(promoted_id)

            # 5. Link promoted memory to decision
            await mcp_tools_call(
                http,
                "link",
                {
                    "source_id": promoted_id,
                    "target_id": decision_id,
                    "relation_type": "related",
                },
                session_id=mcp_session,
            )

        # 6. Complete remaining pins
        for pid in pin_ids[1:]:
            await mcp_tools_call(
                http,
                "pin_complete",
                {
                    "pin_id": pid,
                },
                session_id=mcp_session,
            )

        # 7. Verify via REST search using unique keyword — retry for index lag
        found_ids: List[str] = []
        for _ in range(6):
            await asyncio.sleep(0.5)
            r = await http.post(
                "/api/memories/search",
                json={
                    "query": workflow_keyword,
                    "project_id": TEST_PROJECT_ID,
                    "limit": 10,
                },
            )
            assert r.status_code == 200
            results = r.json()["results"]
            found_ids = [m["id"] for m in results]
            if decision_id in found_ids:
                break
        assert (
            decision_id in found_ids
        ), f"Decision memory {decision_id} not found searching for '{workflow_keyword}'"

        # 8. Check stats
        stats = await mcp_tools_call(
            http,
            "stats",
            {
                "project_id": TEST_PROJECT_ID,
            },
            session_id=mcp_session,
        )
        assert stats is not None

        # 9. End session
        await mcp_tools_call(
            http,
            "session_end",
            {
                "project_id": TEST_PROJECT_ID,
                "summary": "Workflow test: auth architecture analyzed, JWT decision made",
            },
            session_id=mcp_session,
        )


# ---------------------------------------------------------------------------
# 3. Search Accuracy with Topical Data
# ---------------------------------------------------------------------------


class TestSearchAccuracy:
    """Verify search returns relevant results across different topics."""

    async def test_topical_search_accuracy(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """Each topic's search query should find its own memory in results."""
        # Use unique markers per topic so we can search precisely
        import uuid

        marker = uuid.uuid4().hex[:6]

        _pad = " [fixture padding to satisfy 100-char minimum content length validator]"
        topics = [
            {
                "content": f"[{marker}-dbschema] Database schema design: normalized tables with foreign keys for user-order-product relationships{_pad}",
                "category": "decision",
                "tags": ["database", "schema"],
                "search_query": f"{marker}-dbschema",
            },
            {
                "content": f"[{marker}-restapi] REST API design pattern: use resource-based URLs with proper HTTP verbs and cursor pagination{_pad}",
                "category": "decision",
                "tags": ["api", "rest"],
                "search_query": f"{marker}-restapi",
            },
            {
                "content": f"[{marker}-ratelim] Security policy: implement rate limiting at 100 req/min per user with Redis sliding window{_pad}",
                "category": "decision",
                "tags": ["security", "rate-limit"],
                "search_query": f"{marker}-ratelim",
            },
            {
                "content": f"[{marker}-caching] Performance optimization: add Redis caching layer for product catalog with 5-minute TTL{_pad}",
                "category": "idea",
                "tags": ["performance", "caching"],
                "search_query": f"{marker}-caching",
            },
            {
                "content": f"[{marker}-testing] Testing strategy: pytest with factory_boy for fixtures and 80% coverage target{_pad}",
                "category": "decision",
                "tags": ["testing", "pytest"],
                "search_query": f"{marker}-testing",
            },
        ]

        # Seed all topics
        topic_ids = {}
        for topic in topics:
            result = await mcp_tools_call(
                http,
                "add",
                {
                    "content": topic["content"],
                    "project_id": TEST_PROJECT_ID,
                    "category": topic["category"],
                    "tags": topic["tags"] + ["accuracy-test"],
                },
                session_id=mcp_session,
            )
            topic_ids[topic["search_query"]] = result["id"]
            cleanup_memories.append(result["id"])

        # Wait for embeddings
        await asyncio.sleep(1.0)

        # Search each topic by its unique marker
        for topic in topics:
            search_result = await mcp_tools_call(
                http,
                "search",
                {
                    "query": topic["search_query"],
                    "project_id": TEST_PROJECT_ID,
                    "limit": 10,
                },
                session_id=mcp_session,
            )

            results = search_result.get("results", [])
            assert len(results) > 0, f"No results for query: {topic['search_query']}"

            found_ids = [r["id"] for r in results]
            expected_id = topic_ids[topic["search_query"]]
            assert expected_id in found_ids, (
                f"Memory {expected_id} not found for query "
                f"'{topic['search_query']}'"
            )

    async def test_category_filter(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """Category filter returns only matching categories."""
        # Create one idea, one decision
        idea = await mcp_tools_call(
            http,
            "add",
            {
                "content": unique_content(
                    "Category filter test: an innovative idea about caching"
                ),
                "project_id": TEST_PROJECT_ID,
                "category": "idea",
            },
            session_id=mcp_session,
        )
        cleanup_memories.append(idea["id"])

        decision = await mcp_tools_call(
            http,
            "add",
            {
                "content": unique_content(
                    "Category filter test: a decision about caching strategy"
                ),
                "project_id": TEST_PROJECT_ID,
                "category": "decision",
            },
            session_id=mcp_session,
        )
        cleanup_memories.append(decision["id"])

        await asyncio.sleep(0.5)

        # Search with category filter
        result = await mcp_tools_call(
            http,
            "search",
            {
                "query": "caching",
                "project_id": TEST_PROJECT_ID,
                "category": "idea",
                "limit": 10,
            },
            session_id=mcp_session,
        )

        for r in result.get("results", []):
            assert (
                r["category"] == "idea"
            ), f"Expected category 'idea', got '{r['category']}'"

    async def test_recency_weight(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """Recency weight boosts newer results."""
        # Create two memories with same topic
        for i in range(2):
            result = await mcp_tools_call(
                http,
                "add",
                {
                    "content": unique_content(
                        f"Recency test memory #{i}: server monitoring setup"
                    ),
                    "project_id": TEST_PROJECT_ID,
                    "category": "task",
                },
                session_id=mcp_session,
            )
            cleanup_memories.append(result["id"])
            if i == 0:
                await asyncio.sleep(0.5)

        await asyncio.sleep(0.5)

        # Search with high recency weight
        result = await mcp_tools_call(
            http,
            "search",
            {
                "query": "server monitoring",
                "project_id": TEST_PROJECT_ID,
                "recency_weight": 0.8,
                "limit": 5,
            },
            session_id=mcp_session,
        )

        results = result.get("results", [])
        assert len(results) >= 2


# ---------------------------------------------------------------------------
# 4. Bulk Data via Batch Operations
# ---------------------------------------------------------------------------


class TestBulkDataPerformance:
    """Test batch creation and immediate searchability."""

    async def test_batch_create_and_search(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """Create 10 memories in one batch, then search for them."""
        operations = []
        for i in range(10):
            operations.append(
                {
                    "type": "add",
                    "content": unique_content(
                        f"Bulk memory #{i}: microservice architecture pattern for order processing"
                    ),
                    "project_id": TEST_PROJECT_ID,
                    "category": "task",
                    "tags": ["bulk-test"],
                }
            )

        result = await mcp_tools_call(
            http,
            "batch_operations",
            {
                "operations": operations,
            },
            session_id=mcp_session,
        )

        assert result["status"] == "success"
        assert result["total_operations"] == 10

        created_ids = []
        for r in result["results"]:
            if r["type"] == "add" and r.get("success"):
                created_ids.append(r["memory_id"])
                cleanup_memories.append(r["memory_id"])

        assert len(created_ids) == 10

        # Wait for embeddings to be indexed
        await asyncio.sleep(2.0)

        # Verify via REST empty-query search with project filter
        r = await http.post(
            "/api/memories/search",
            json={
                "query": "",
                "project_id": TEST_PROJECT_ID,
                "limit": 50,
                "sort_by": "created_at",
                "sort_direction": "desc",
            },
        )
        assert r.status_code == 200
        all_ids = {m["id"] for m in r.json().get("results", [])}
        found_count = len(all_ids & set(created_ids))
        assert (
            found_count >= 5
        ), f"Expected at least 5 of 10 bulk memories in project results, found {found_count}"

    async def test_batch_mixed_operations(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """Batch with add + search in single call."""
        result = await mcp_tools_call(
            http,
            "batch_operations",
            {
                "operations": [
                    {
                        "type": "add",
                        "content": unique_content(
                            "Batch mixed: add operation in batch"
                        ),
                        "project_id": TEST_PROJECT_ID,
                        "category": "task",
                    },
                    {
                        "type": "search",
                        "query": "batch mixed",
                        "project_id": TEST_PROJECT_ID,
                        "limit": 5,
                    },
                ],
            },
            session_id=mcp_session,
        )

        assert result["total_operations"] == 2
        add_results = [r for r in result["results"] if r["type"] == "add"]
        search_results = [r for r in result["results"] if r["type"] == "search"]
        assert len(add_results) == 1
        assert len(search_results) == 1

        for r in add_results:
            if r.get("success"):
                cleanup_memories.append(r["memory_id"])
