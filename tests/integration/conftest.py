"""Shared fixtures for live-server integration tests.

Requires a running mem-mesh API server at localhost:8000.
All test-created data uses project_id="__test__" for isolation
and is cleaned up after each test.
"""

import json
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
import pytest

BASE_URL = "http://localhost:8000"
MCP_URL = f"{BASE_URL}/mcp"
TEST_PROJECT_ID = "inttest"

# Server reachability check (cached across the module)
_server_checked = False
_server_available = False


def _check_server_sync() -> bool:
    """Synchronous server check (run once per session)."""
    global _server_checked, _server_available
    if _server_checked:
        return _server_available
    _server_checked = True
    try:
        import urllib.request

        req = urllib.request.Request(f"{BASE_URL}/api/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            _server_available = resp.status == 200
    except Exception:
        _server_available = False
    return _server_available


# ---------------------------------------------------------------------------
# HTTP client fixture (function-scoped to avoid event loop issues)
# ---------------------------------------------------------------------------


@pytest.fixture
async def http() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client with health check gate."""
    if not _check_server_sync():
        pytest.skip("API server not running at localhost:8000")
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        yield client


# ---------------------------------------------------------------------------
# MCP JSON-RPC helpers
# ---------------------------------------------------------------------------


def jsonrpc_body(
    method: str,
    params: Optional[Dict[str, Any]] = None,
    req_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a JSON-RPC 2.0 request body."""
    body: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    if req_id is not None:
        body["id"] = req_id
    else:
        body["id"] = 1
    return body


async def mcp_call(
    client: httpx.AsyncClient,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a JSON-RPC request to MCP endpoint and return the result.

    Returns the JSON-RPC response dict (with result or error).
    """
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    body = jsonrpc_body(method, params)
    r = await client.post(f"{MCP_URL}/sse", json=body, headers=headers)
    r.raise_for_status()

    data = r.json()
    new_session = r.headers.get("Mcp-Session-Id")
    if new_session:
        data["_session_id"] = new_session
    return data


async def mcp_tools_call(
    client: httpx.AsyncClient,
    tool_name: str,
    arguments: Dict[str, Any],
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Call an MCP tool and return the parsed result content."""
    resp = await mcp_call(
        client,
        "tools/call",
        {"name": tool_name, "arguments": arguments},
        session_id=session_id,
    )
    result = resp.get("result", {})
    content_list = result.get("content", [])
    if content_list and content_list[0].get("type") == "text":
        text = content_list[0]["text"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"_raw": text}
    return result


async def mcp_stateless_call(
    client: httpx.AsyncClient,
    tool_name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Call MCP tool via stateless endpoint (no session)."""
    body = jsonrpc_body("tools/call", {"name": tool_name, "arguments": arguments})
    r = await client.post(f"{MCP_URL}/tools/call", json=body)
    r.raise_for_status()
    data = r.json()
    result = data.get("result", {})
    content_list = result.get("content", [])
    if content_list and content_list[0].get("type") == "text":
        text = content_list[0]["text"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"_raw": text}
    return result


# ---------------------------------------------------------------------------
# MCP session fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def mcp_session(http: httpx.AsyncClient) -> AsyncGenerator[str, None]:
    """Initialize an MCP session and return its session_id.

    Cleans up the session on teardown.
    """
    resp = await mcp_call(
        http,
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "integration-test", "version": "1.0"},
        },
    )
    session_id = resp.get("_session_id")
    assert session_id, "Failed to get MCP session ID"
    yield session_id

    # Cleanup
    try:
        await http.delete(
            f"{MCP_URL}/sse",
            headers={"Mcp-Session-Id": session_id},
        )
    except httpx.HTTPError:
        pass


# ---------------------------------------------------------------------------
# Test data cleanup
# ---------------------------------------------------------------------------


@pytest.fixture
async def cleanup_memories(http: httpx.AsyncClient) -> AsyncGenerator[List[str], None]:
    """Collects memory IDs to clean up after the test."""
    ids: List[str] = []
    yield ids
    for memory_id in ids:
        try:
            await http.delete(f"/api/memories/{memory_id}")
        except httpx.HTTPError:
            pass


@pytest.fixture
async def cleanup_pins(http: httpx.AsyncClient) -> AsyncGenerator[List[str], None]:
    """Collects pin IDs to clean up after the test."""
    ids: List[str] = []
    yield ids
    for pin_id in ids:
        try:
            await http.delete(f"/api/work/pins/{pin_id}")
        except httpx.HTTPError:
            pass


def unique_content(prefix: str = "Integration test") -> str:
    """Generate unique content string (min 10 chars for API validation)."""
    return f"{prefix} - {uuid.uuid4().hex[:12]}"
