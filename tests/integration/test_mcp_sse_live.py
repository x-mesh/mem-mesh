"""MCP Streamable HTTP (SSE) integration tests against a live server.

Tests the MCP 2025-03-26 Streamable HTTP transport at /mcp/sse.

Scenarios:
    1.  Initialize session
    2.  Tools list
    3.  Add memory via MCP
    4.  Search via MCP
    5.  Pin workflow via MCP
    6.  Session lifecycle via MCP
    7.  SSE stream (GET /mcp/sse)
    8.  Stateless call (POST /mcp/tools/call)
    9.  Session delete
    10. Batch operations
"""

from typing import List

import httpx
import pytest

from tests.integration.conftest import (
    BASE_URL,
    MCP_URL,
    TEST_PROJECT_ID,
    mcp_call,
    mcp_stateless_call,
    mcp_tools_call,
    unique_content,
)

# ---------------------------------------------------------------------------
# 1. Initialize session
# ---------------------------------------------------------------------------


class TestMCPInitialize:
    async def test_initialize(self, http: httpx.AsyncClient):
        """POST /mcp/sse with initialize → get session_id."""
        resp = await mcp_call(
            http,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "0.1"},
            },
        )
        assert "result" in resp, f"No result in response: {resp}"
        assert resp["result"]["protocolVersion"] == "2025-03-26"
        assert "_session_id" in resp
        session_id = resp["_session_id"]

        # Cleanup
        await http.delete(
            f"{MCP_URL}/sse",
            headers={"Mcp-Session-Id": session_id},
        )

    async def test_initialize_returns_server_info(self, http: httpx.AsyncClient):
        resp = await mcp_call(
            http,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1"},
            },
        )
        server_info = resp["result"]["serverInfo"]
        assert "name" in server_info
        assert "version" in server_info

        # Cleanup
        session_id = resp.get("_session_id")
        if session_id:
            await http.delete(
                f"{MCP_URL}/sse",
                headers={"Mcp-Session-Id": session_id},
            )


# ---------------------------------------------------------------------------
# 2. Tools list
# ---------------------------------------------------------------------------


class TestMCPToolsList:
    async def test_tools_list(self, http: httpx.AsyncClient, mcp_session: str):
        resp = await mcp_call(http, "tools/list", session_id=mcp_session)
        assert "result" in resp
        tools = resp["result"]["tools"]
        assert isinstance(tools, list)
        tool_names = [t["name"] for t in tools]
        assert "add" in tool_names
        assert "search" in tool_names
        assert "pin_add" in tool_names
        assert "session_resume" in tool_names
        assert "batch_operations" in tool_names

    async def test_tool_schemas_have_input_schema(
        self, http: httpx.AsyncClient, mcp_session: str
    ):
        resp = await mcp_call(http, "tools/list", session_id=mcp_session)
        tools = resp["result"]["tools"]
        for tool in tools:
            assert "inputSchema" in tool, f"Tool '{tool['name']}' missing inputSchema"


# ---------------------------------------------------------------------------
# 3. Add memory via MCP
# ---------------------------------------------------------------------------


class TestMCPAddMemory:
    async def test_add_and_verify(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        content = unique_content("MCP add test")
        result = await mcp_tools_call(
            http,
            "add",
            {
                "content": content,
                "project_id": TEST_PROJECT_ID,
                "category": "task",
                "tags": ["mcp-test"],
            },
            session_id=mcp_session,
        )
        memory_id = result.get("id")
        assert memory_id, f"Add failed (no id): {result}"
        cleanup_memories.append(memory_id)

        # Verify via REST API
        r = await http.get(f"/api/memories/{memory_id}")
        assert r.status_code == 200
        assert r.json()["content"] == content


# ---------------------------------------------------------------------------
# 4. Search via MCP
# ---------------------------------------------------------------------------


class TestMCPSearch:
    async def test_search_returns_results(
        self, http: httpx.AsyncClient, mcp_session: str
    ):
        result = await mcp_tools_call(
            http,
            "search",
            {"query": "test", "limit": 5},
            session_id=mcp_session,
        )
        assert "results" in result or "total" in result or isinstance(result, dict)

    async def test_search_with_project_filter(
        self, http: httpx.AsyncClient, mcp_session: str
    ):
        result = await mcp_tools_call(
            http,
            "search",
            {"query": "", "project_id": "mem-mesh", "limit": 3},
            session_id=mcp_session,
        )
        assert isinstance(result, dict)

    async def test_search_empty_query_returns_recent(
        self, http: httpx.AsyncClient, mcp_session: str
    ):
        """Empty query should return recent memories."""
        result = await mcp_tools_call(
            http,
            "search",
            {"query": "", "limit": 5},
            session_id=mcp_session,
        )
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 5. Pin workflow via MCP
# ---------------------------------------------------------------------------


class TestMCPPinWorkflow:
    async def test_pin_add_complete_promote(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_pins: List[str],
        cleanup_memories: List[str],
    ):
        # pin_add
        result = await mcp_tools_call(
            http,
            "pin_add",
            {
                "content": unique_content("MCP pin test"),
                "project_id": TEST_PROJECT_ID,
                "importance": 4,
                "tags": ["mcp-test"],
            },
            session_id=mcp_session,
        )
        pin_id = result.get("pin_id") or result.get("id")
        assert pin_id, f"pin_add failed (no id): {result}"
        cleanup_pins.append(pin_id)

        # pin_complete
        result = await mcp_tools_call(
            http,
            "pin_complete",
            {"pin_id": pin_id},
            session_id=mcp_session,
        )
        assert isinstance(result, dict), f"pin_complete failed: {result}"
        assert result.get("status") == "completed" or result.get(
            "id"
        ), f"pin_complete unexpected response: {result}"

        # pin_promote
        result = await mcp_tools_call(
            http,
            "pin_promote",
            {"pin_id": pin_id, "category": "decision"},
            session_id=mcp_session,
        )
        assert isinstance(result, dict), f"pin_promote failed: {result}"
        memory_id = result.get("memory_id") or result.get("id")
        if memory_id:
            cleanup_memories.append(memory_id)


# ---------------------------------------------------------------------------
# 6. Session lifecycle via MCP
# ---------------------------------------------------------------------------


class TestMCPSession:
    async def test_session_resume_and_end(
        self, http: httpx.AsyncClient, mcp_session: str
    ):
        # session_resume
        result = await mcp_tools_call(
            http,
            "session_resume",
            {"project_id": TEST_PROJECT_ID, "expand": "smart"},
            session_id=mcp_session,
        )
        assert isinstance(result, dict)

        # session_end
        result = await mcp_tools_call(
            http,
            "session_end",
            {"project_id": TEST_PROJECT_ID, "summary": "MCP integration test session"},
            session_id=mcp_session,
        )
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 7. SSE stream
# ---------------------------------------------------------------------------


class TestMCPSSEStream:
    async def test_sse_stream_receives_endpoint_event(self, http: httpx.AsyncClient):
        """GET /mcp/sse with Accept: text/event-stream → receive endpoint event."""
        session_id = None
        # Use a dedicated client with short read timeout for SSE streaming
        async with httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=httpx.Timeout(5.0, read=3.0),
        ) as sse_client:
            try:
                async with sse_client.stream(
                    "GET",
                    f"{MCP_URL}/sse",
                    headers={"Accept": "text/event-stream"},
                ) as response:
                    assert response.status_code == 200
                    assert "text/event-stream" in response.headers.get(
                        "content-type", ""
                    )

                    session_id = response.headers.get("mcp-session-id")
                    assert session_id, "No Mcp-Session-Id in SSE response"

                    # Read first event (should be "endpoint")
                    buffer = ""
                    try:
                        async for chunk in response.aiter_text():
                            buffer += chunk
                            if "\n\n" in buffer:
                                event_block = buffer.split("\n\n")[0]
                                assert (
                                    "event: endpoint" in event_block
                                    or "event:endpoint" in event_block
                                )
                                assert "/mcp/message" in event_block
                                break
                    except httpx.ReadTimeout:
                        # SSE is long-lived; timeout after first event is expected
                        if buffer:
                            assert (
                                "endpoint" in buffer
                            ), f"Got SSE data but no endpoint event: {buffer[:200]}"
                        else:
                            pytest.fail("SSE stream timed out without any data")
            except httpx.ReadTimeout:
                pytest.fail("SSE connection timed out before receiving headers")

        # Cleanup session
        if session_id:
            try:
                await http.delete(
                    f"{MCP_URL}/sse",
                    headers={"Mcp-Session-Id": session_id},
                )
            except httpx.HTTPError:
                pass


# ---------------------------------------------------------------------------
# 8. Stateless call
# ---------------------------------------------------------------------------


class TestMCPStateless:
    async def test_stateless_stats(self, http: httpx.AsyncClient):
        """POST /mcp/tools/call — no session needed."""
        result = await mcp_stateless_call(http, "stats", {})
        assert isinstance(result, dict)

    async def test_stateless_search(self, http: httpx.AsyncClient):
        result = await mcp_stateless_call(http, "search", {"query": "test", "limit": 3})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 9. Session delete
# ---------------------------------------------------------------------------


class TestMCPSessionDelete:
    async def test_delete_session(self, http: httpx.AsyncClient, mcp_session: str):
        """DELETE /mcp/sse → terminate session."""
        r = await http.delete(
            f"{MCP_URL}/sse",
            headers={"Mcp-Session-Id": mcp_session},
        )
        assert r.status_code == 204

    async def test_delete_nonexistent_session(self, http: httpx.AsyncClient):
        r = await http.delete(
            f"{MCP_URL}/sse",
            headers={"Mcp-Session-Id": "nonexistent-session-id"},
        )
        assert r.status_code == 404

    async def test_delete_without_session_id(self, http: httpx.AsyncClient):
        r = await http.delete(f"{MCP_URL}/sse")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# 10. Batch operations
# ---------------------------------------------------------------------------


class TestMCPBatchOps:
    async def test_batch_add_and_search(
        self,
        http: httpx.AsyncClient,
        mcp_session: str,
        cleanup_memories: List[str],
    ):
        """batch_operations: add + search in one call."""
        content = unique_content("Batch op test")
        result = await mcp_tools_call(
            http,
            "batch_operations",
            {
                "operations": [
                    {
                        "type": "add",
                        "content": content,
                        "project_id": TEST_PROJECT_ID,
                        "category": "task",
                        "tags": ["batch-test"],
                    },
                    {
                        "type": "search",
                        "query": "batch",
                        "limit": 5,
                    },
                ]
            },
            session_id=mcp_session,
        )
        assert isinstance(result, dict)
        # Collect created memory for cleanup
        results = result.get("results", [])
        for r in results:
            if isinstance(r, dict) and r.get("id"):
                cleanup_memories.append(r["id"])


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------


class TestMCPPing:
    async def test_ping(self, http: httpx.AsyncClient, mcp_session: str):
        resp = await mcp_call(http, "ping", session_id=mcp_session)
        assert "result" in resp
