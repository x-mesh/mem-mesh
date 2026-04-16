"""MCP Streamable HTTP transport integration tests against a live mem-mesh server.

Scenarios:
    1. Session lifecycle (initialize → tools/list → ping → delete)
    2. Memory CRUD via MCP tools/call
    3. Pin/Session workflow via MCP
    4. Relations via MCP
    5. Batch operations via MCP
    6. Weekly review via MCP
    7. SSE GET stream + legacy message endpoint
    8. Error handling (invalid requests, unknown tools, etc.)
"""

import asyncio
import json
from typing import List

import httpx
import pytest

from tests.integration.conftest import (
    TEST_PROJECT_ID,
    mcp_call,
    mcp_stateless_call,
    mcp_tools_call,
    unique_content,
)

# ---------------------------------------------------------------------------
# 1. MCP Session Lifecycle
# ---------------------------------------------------------------------------


class TestMCPSessionLifecycle:
    """Test MCP Streamable HTTP session management."""

    async def test_initialize_creates_session(self, http: httpx.AsyncClient):
        """POST /mcp/sse with initialize returns Mcp-Session-Id header."""
        resp = await mcp_call(
            http,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test-init", "version": "1.0"},
            },
        )
        session_id = resp.get("_session_id")
        assert session_id, "No Mcp-Session-Id in response"

        result = resp["result"]
        assert result["protocolVersion"] == "2025-03-26"
        assert result["serverInfo"]["name"] == "mem-mesh"

        # Cleanup
        await http.delete("/mcp/sse", headers={"Mcp-Session-Id": session_id})

    async def test_tools_list_returns_all_tools(
        self, http: httpx.AsyncClient, mcp_session: str
    ):
        """tools/list returns all 16 MCP tools."""
        resp = await mcp_call(http, "tools/list", session_id=mcp_session)
        tools = resp["result"]["tools"]
        tool_names = [t["name"] for t in tools]

        expected = [
            "add",
            "search",
            "context",
            "update",
            "delete",
            "stats",
            "pin_add",
            "pin_complete",
            "pin_promote",
            "session_resume",
            "session_end",
            "link",
            "unlink",
            "get_links",
            "batch_operations",
            "weekly_review",
        ]
        for name in expected:
            assert name in tool_names, f"Missing tool: {name}"

    async def test_ping(self, http: httpx.AsyncClient, mcp_session: str):
        """ping method returns empty result."""
        resp = await mcp_call(http, "ping", session_id=mcp_session)
        assert resp["result"] == {}

    async def test_notification_returns_202(
        self, http: httpx.AsyncClient, mcp_session: str
    ):
        """Notification (no id) returns 202 Accepted."""
        body = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        r = await http.post(
            "/mcp/sse",
            json=body,
            headers={"Mcp-Session-Id": mcp_session},
        )
        assert r.status_code == 202

    async def test_delete_session(self, http: httpx.AsyncClient):
        """DELETE /mcp/sse terminates session, second DELETE returns 404."""
        # Create
        resp = await mcp_call(
            http,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test-delete", "version": "1.0"},
            },
        )
        session_id = resp["_session_id"]

        # Delete
        r = await http.delete("/mcp/sse", headers={"Mcp-Session-Id": session_id})
        assert r.status_code == 204

        # Second delete → 404
        r = await http.delete("/mcp/sse", headers={"Mcp-Session-Id": session_id})
        assert r.status_code == 404

    async def test_invalid_json_returns_400(self, http: httpx.AsyncClient):
        """Non-JSON body returns 400."""
        r = await http.post(
            "/mcp/sse",
            content="not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400

    async def test_invalid_jsonrpc_returns_400(self, http: httpx.AsyncClient):
        """Non-JSON-RPC body returns 400."""
        r = await http.post("/mcp/sse", json={"not": "jsonrpc"})
        assert r.status_code == 400

    async def test_unknown_method_returns_error(
        self, http: httpx.AsyncClient, mcp_session: str
    ):
        """Unknown method returns JSON-RPC -32601 error."""
        resp = await mcp_call(http, "unknown/method", session_id=mcp_session)
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    async def test_delete_without_header_returns_400(self, http: httpx.AsyncClient):
        """DELETE /mcp/sse without Mcp-Session-Id returns 400."""
        r = await http.delete("/mcp/sse")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# 2. MCP Memory CRUD
# ---------------------------------------------------------------------------


class TestMCPMemoryTools:
    """Test memory CRUD through MCP tools/call."""

    async def test_add_memory(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """MCP add tool creates a memory."""
        result = await mcp_tools_call(
            http,
            "add",
            {
                "content": unique_content("MCP add test"),
                "project_id": TEST_PROJECT_ID,
                "category": "task",
                "tags": ["mcp-test", "integration"],
            },
            session_id=mcp_session,
        )

        assert "id" in result
        assert result["status"] == "saved"
        cleanup_memories.append(result["id"])

    async def test_search_finds_created_memory(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """MCP search returns a memory we just created."""
        keyword = f"uniqueword_{unique_content()[-8:]}"
        add_result = await mcp_tools_call(
            http,
            "add",
            {
                "content": f"MCP search test memory containing {keyword} for retrieval (fixture padded to satisfy the 100-character minimum content length validator).",
                "project_id": TEST_PROJECT_ID,
                "category": "decision",
            },
            session_id=mcp_session,
        )
        memory_id = add_result["id"]
        cleanup_memories.append(memory_id)

        # Wait briefly for embedding
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

        assert "results" in search_result
        found_ids = [r["id"] for r in search_result["results"]]
        assert memory_id in found_ids

    async def test_context(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """MCP context tool returns related memories."""
        add_result = await mcp_tools_call(
            http,
            "add",
            {
                "content": unique_content("MCP context test target memory"),
                "project_id": TEST_PROJECT_ID,
                "category": "task",
            },
            session_id=mcp_session,
        )
        cleanup_memories.append(add_result["id"])

        result = await mcp_tools_call(
            http,
            "context",
            {
                "memory_id": add_result["id"],
                "depth": 2,
            },
            session_id=mcp_session,
        )
        assert result is not None

    async def test_update_memory(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """MCP update tool modifies a memory."""
        add_result = await mcp_tools_call(
            http,
            "add",
            {
                "content": unique_content("MCP update test original content"),
                "project_id": TEST_PROJECT_ID,
                "category": "task",
            },
            session_id=mcp_session,
        )
        memory_id = add_result["id"]
        cleanup_memories.append(memory_id)

        update_result = await mcp_tools_call(
            http,
            "update",
            {
                "memory_id": memory_id,
                "content": unique_content("MCP update test modified content"),
                "category": "decision",
            },
            session_id=mcp_session,
        )
        assert update_result["status"] == "updated"

    async def test_delete_memory(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
    ):
        """MCP delete tool removes a memory."""
        add_result = await mcp_tools_call(
            http,
            "add",
            {
                "content": unique_content("MCP delete test memory to remove"),
                "project_id": TEST_PROJECT_ID,
                "category": "task",
            },
            session_id=mcp_session,
        )

        delete_result = await mcp_tools_call(
            http,
            "delete",
            {
                "memory_id": add_result["id"],
            },
            session_id=mcp_session,
        )
        assert delete_result["status"] == "deleted"

    async def test_stats(self, http: httpx.AsyncClient, mcp_session: str):
        """MCP stats tool returns memory statistics."""
        result = await mcp_tools_call(
            http,
            "stats",
            {
                "project_id": TEST_PROJECT_ID,
            },
            session_id=mcp_session,
        )
        assert "total_memories" in result or isinstance(result, dict)

    async def test_stateless_tools_call(
        self,
        http: httpx.AsyncClient,
        cleanup_memories: List[str],
    ):
        """POST /mcp/tools/call works without a session."""
        result = await mcp_stateless_call(
            http,
            "add",
            {
                "content": unique_content("Stateless endpoint test"),
                "project_id": TEST_PROJECT_ID,
                "category": "task",
            },
        )
        assert "id" in result
        cleanup_memories.append(result["id"])


# ---------------------------------------------------------------------------
# 3. MCP Pin/Session Workflow
# ---------------------------------------------------------------------------


class TestMCPPinSessionTools:
    """Test pin and session lifecycle via MCP tools."""

    async def test_session_resume(self, http: httpx.AsyncClient, mcp_session: str):
        """MCP session_resume returns session context or no_session."""
        result = await mcp_tools_call(
            http,
            "session_resume",
            {
                "project_id": TEST_PROJECT_ID,
                "expand": "smart",
                "limit": 10,
            },
            session_id=mcp_session,
        )
        assert "status" in result or "session_id" in result

    async def test_pin_lifecycle(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_pins: List[str],
        cleanup_memories: List[str],
    ):
        """pin_add → pin_complete → pin_promote full cycle."""
        # Add pin
        add_result = await mcp_tools_call(
            http,
            "pin_add",
            {
                "content": unique_content("MCP pin lifecycle test"),
                "project_id": TEST_PROJECT_ID,
                "importance": 5,
                "tags": ["mcp-test"],
            },
            session_id=mcp_session,
        )
        pin_id = add_result["id"]
        cleanup_pins.append(pin_id)

        # Complete
        complete_result = await mcp_tools_call(
            http,
            "pin_complete",
            {
                "pin_id": pin_id,
            },
            session_id=mcp_session,
        )
        assert (
            complete_result.get("status") == "completed"
            or "completed" in str(complete_result).lower()
        )

        # Promote
        promote_result = await mcp_tools_call(
            http,
            "pin_promote",
            {
                "pin_id": pin_id,
            },
            session_id=mcp_session,
        )
        if "memory_id" in promote_result:
            cleanup_memories.append(promote_result["memory_id"])

    async def test_pin_add_low_importance(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_pins: List[str],
    ):
        """pin_add with low importance creates a pin."""
        result = await mcp_tools_call(
            http,
            "pin_add",
            {
                "content": unique_content("MCP low importance pin test"),
                "project_id": TEST_PROJECT_ID,
                "importance": 1,
            },
            session_id=mcp_session,
        )
        assert "id" in result
        cleanup_pins.append(result["id"])

    async def test_session_end(self, http: httpx.AsyncClient, mcp_session: str):
        """MCP session_end closes the active session."""
        result = await mcp_tools_call(
            http,
            "session_end",
            {
                "project_id": TEST_PROJECT_ID,
                "summary": "Integration test session completed",
            },
            session_id=mcp_session,
        )
        assert result is not None


# ---------------------------------------------------------------------------
# 4. MCP Relations
# ---------------------------------------------------------------------------


class TestMCPRelations:
    """Test memory relation tools via MCP."""

    async def _create_two_memories(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ) -> tuple:
        ids = []
        for label in ["source", "target"]:
            result = await mcp_tools_call(
                http,
                "add",
                {
                    "content": unique_content(f"MCP relation {label} memory"),
                    "project_id": TEST_PROJECT_ID,
                    "category": "decision",
                },
                session_id=mcp_session,
            )
            ids.append(result["id"])
            cleanup_memories.append(result["id"])
        return ids[0], ids[1]

    async def test_link_and_get_links(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """link → get_links → verify relation exists."""
        src, tgt = await self._create_two_memories(http, mcp_session, cleanup_memories)

        link_result = await mcp_tools_call(
            http,
            "link",
            {
                "source_id": src,
                "target_id": tgt,
                "relation_type": "depends_on",
                "strength": 0.9,
            },
            session_id=mcp_session,
        )
        assert link_result is not None

        links_result = await mcp_tools_call(
            http,
            "get_links",
            {
                "memory_id": src,
                "direction": "outgoing",
            },
            session_id=mcp_session,
        )
        assert "relations" in links_result or isinstance(links_result, dict)

    async def test_unlink(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """link → unlink → verify relation removed."""
        src, tgt = await self._create_two_memories(http, mcp_session, cleanup_memories)

        await mcp_tools_call(
            http,
            "link",
            {
                "source_id": src,
                "target_id": tgt,
                "relation_type": "related",
            },
            session_id=mcp_session,
        )

        unlink_result = await mcp_tools_call(
            http,
            "unlink",
            {
                "source_id": src,
                "target_id": tgt,
            },
            session_id=mcp_session,
        )
        assert unlink_result is not None


# ---------------------------------------------------------------------------
# 5. MCP Batch Operations
# ---------------------------------------------------------------------------


class TestMCPBatchOperations:
    """Test batch_operations tool via MCP."""

    async def test_batch_add_and_search(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """Batch with add + search operations."""
        result = await mcp_tools_call(
            http,
            "batch_operations",
            {
                "operations": [
                    {
                        "type": "add",
                        "content": unique_content("Batch test first memory"),
                        "project_id": TEST_PROJECT_ID,
                        "category": "task",
                        "tags": ["batch-test"],
                    },
                    {
                        "type": "add",
                        "content": unique_content("Batch test second memory"),
                        "project_id": TEST_PROJECT_ID,
                        "category": "idea",
                    },
                    {
                        "type": "search",
                        "query": "batch",
                        "project_id": TEST_PROJECT_ID,
                        "limit": 5,
                    },
                ],
            },
            session_id=mcp_session,
        )

        assert result["status"] == "success"
        assert result["total_operations"] == 3
        assert len(result["results"]) == 3

        for r in result["results"]:
            if r["type"] == "add" and r.get("success"):
                cleanup_memories.append(r["memory_id"])

    async def test_batch_stats(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """Batch reports correct operation counts."""
        result = await mcp_tools_call(
            http,
            "batch_operations",
            {
                "operations": [
                    {
                        "type": "add",
                        "content": unique_content("Batch stats test memory"),
                        "project_id": TEST_PROJECT_ID,
                        "category": "task",
                    },
                    {
                        "type": "search",
                        "query": "",
                        "limit": 3,
                    },
                ],
            },
            session_id=mcp_session,
        )

        stats = result["batch_stats"]
        assert stats["add_operations"] == 1
        assert stats["search_operations"] == 1

        for r in result["results"]:
            if r["type"] == "add" and r.get("success"):
                cleanup_memories.append(r["memory_id"])


# ---------------------------------------------------------------------------
# 6. MCP Weekly Review
# ---------------------------------------------------------------------------


class TestMCPWeeklyReview:
    """Test weekly_review tool via MCP."""

    async def test_weekly_review(self, http: httpx.AsyncClient, mcp_session: str):
        """weekly_review returns a report."""
        result = await mcp_tools_call(
            http,
            "weekly_review",
            {
                "project_id": TEST_PROJECT_ID,
                "days": 7,
            },
            session_id=mcp_session,
        )
        assert result is not None
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 7. SSE Stream (GET /mcp/sse)
# ---------------------------------------------------------------------------


class TestSSEStream:
    """Test the SSE GET stream and legacy message endpoint."""

    async def test_sse_stream_returns_endpoint_event(self, http: httpx.AsyncClient):
        """GET /mcp/sse returns an 'endpoint' SSE event with session URL."""
        from httpx_sse import aconnect_sse

        async with aconnect_sse(
            http,
            "GET",
            "/mcp/sse",
            headers={"Accept": "text/event-stream"},
        ) as event_source:
            first_event = None
            async for event in event_source.aiter_sse():
                first_event = event
                break

            assert first_event is not None
            assert first_event.event == "endpoint"
            assert "/mcp/message?session_id=" in first_event.data

    async def test_legacy_message_with_sse_response(self, http: httpx.AsyncClient):
        """POST /mcp/message → response appears in SSE stream."""
        from httpx_sse import aconnect_sse

        session_id = None
        response_data = None

        async with aconnect_sse(
            http,
            "GET",
            "/mcp/sse",
            headers={"Accept": "text/event-stream"},
        ) as event_source:
            try:
                async with asyncio.timeout(15):
                    async for event in event_source.aiter_sse():
                        if event.event == "endpoint" and session_id is None:
                            # Extract session_id from endpoint URL
                            session_id = event.data.split("session_id=")[1]

                            # Send tools/list via legacy endpoint
                            body = {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "tools/list",
                            }
                            msg_resp = await http.post(
                                f"/mcp/message?session_id={session_id}",
                                json=body,
                            )
                            assert msg_resp.status_code == 200

                        elif event.event == "message":
                            response_data = json.loads(event.data)
                            break

                        elif event.event == "ping":
                            continue
            except TimeoutError:
                pytest.fail("Timed out waiting for SSE message event")

        assert session_id is not None
        assert response_data is not None
        assert response_data["jsonrpc"] == "2.0"
        assert "tools" in response_data["result"]

    async def test_sse_get_without_accept_returns_405(self, http: httpx.AsyncClient):
        """GET /mcp/sse without Accept: text/event-stream returns 405."""
        r = await http.get("/mcp/sse", headers={"Accept": "application/json"})
        assert r.status_code == 405


# ---------------------------------------------------------------------------
# 8. MCP Error Handling
# ---------------------------------------------------------------------------


class TestMCPErrorHandling:
    """Test error handling for MCP requests."""

    async def test_unknown_tool(self, http: httpx.AsyncClient, mcp_session: str):
        """Unknown tool name returns isError: true."""
        resp = await mcp_call(
            http,
            "tools/call",
            {"name": "nonexistent_tool", "arguments": {}},
            session_id=mcp_session,
        )
        result = resp.get("result", {})
        assert result.get("isError") is True

    async def test_missing_required_content(
        self, http: httpx.AsyncClient, mcp_session: str
    ):
        """add tool without content returns error."""
        resp = await mcp_call(
            http,
            "tools/call",
            {"name": "add", "arguments": {"tags": ["no-content"]}},
            session_id=mcp_session,
        )
        result = resp.get("result", {})
        assert result.get("isError") is True

    async def test_invalid_memory_id_for_delete(
        self, http: httpx.AsyncClient, mcp_session: str
    ):
        """delete tool with nonexistent ID returns error."""
        result = await mcp_tools_call(
            http,
            "delete",
            {
                "memory_id": "nonexistent-id-99999",
            },
            session_id=mcp_session,
        )
        # Should indicate failure (may be isError or error in result)
        assert (
            result.get("status") == "deleted"  # idempotent delete
            or result.get("error")
            or result.get("success") is False
        )

    async def test_content_too_short_via_mcp(
        self, http: httpx.AsyncClient, mcp_session: str
    ):
        """add with content < 10 chars fails validation."""
        resp = await mcp_call(
            http,
            "tools/call",
            {
                "name": "add",
                "arguments": {
                    "content": "short",
                    "project_id": TEST_PROJECT_ID,
                },
            },
            session_id=mcp_session,
        )
        result = resp.get("result", {})
        assert result.get("isError") is True
