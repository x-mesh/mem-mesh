"""Live WebSocket notification tests.

Requires a running mem-mesh server at localhost:8000.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

import httpx
import websockets

from tests.integration.conftest import (
    BASE_URL,
    TEST_PROJECT_ID,
    mcp_stateless_call,
    unique_content,
)


def _ws_url(client_id: str) -> str:
    return BASE_URL.replace("http://", "ws://").replace("https://", "wss://") + (
        f"/ws/realtime?client_id={client_id}"
    )


async def _wait_for_memory_created(websocket, memory_id: str) -> Dict[str, Any]:
    return await _wait_for_memory_event(websocket, "memory_created", memory_id)


async def _wait_for_memory_event(
    websocket, event_type: str, memory_id: str
) -> Dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + 10.0
    while asyncio.get_running_loop().time() < deadline:
        timeout = max(0.1, deadline - asyncio.get_running_loop().time())
        raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
        message = json.loads(raw)
        if message.get("type") != event_type:
            continue
        data = message.get("data", {})
        memory = data.get("memory", {})
        event_memory_id = memory.get("id") or data.get("memory_id")
        if event_memory_id == memory_id:
            return message
    raise AssertionError(f"{event_type} event not received for {memory_id}")


async def test_api_memory_create_broadcasts_websocket_event(
    http: httpx.AsyncClient, cleanup_memories: list[str]
) -> None:
    async with websockets.connect(_ws_url("integration_api_ws")) as websocket:
        await asyncio.wait_for(websocket.recv(), timeout=5.0)

        content = unique_content("WebSocket REST add test")
        response = await http.post(
            "/api/memories",
            json={
                "content": content,
                "project_id": TEST_PROJECT_ID,
                "category": "task",
                "source": "integration-websocket",
                "client": "pytest",
                "tags": ["websocket", "rest"],
            },
        )
        response.raise_for_status()
        memory_id = response.json()["id"]
        cleanup_memories.append(memory_id)

        event = await _wait_for_memory_created(websocket, memory_id)
        memory = event["data"]["memory"]
        assert memory["content"] == content
        assert memory["project_id"] == TEST_PROJECT_ID


async def test_mcp_memory_create_broadcasts_websocket_event(
    http: httpx.AsyncClient, cleanup_memories: list[str]
) -> None:
    async with websockets.connect(_ws_url("integration_mcp_ws")) as websocket:
        await asyncio.wait_for(websocket.recv(), timeout=5.0)

        content = unique_content("WebSocket MCP add test")
        result = await mcp_stateless_call(
            http,
            "add",
            {
                "content": content,
                "project_id": TEST_PROJECT_ID,
                "category": "task",
                "source": "integration-websocket",
                "client": "pytest",
                "tags": ["websocket", "mcp"],
            },
        )
        memory_id = result["id"]
        cleanup_memories.append(memory_id)

        event = await _wait_for_memory_created(websocket, memory_id)
        memory = event["data"]["memory"]
        assert memory["content"] == content
        assert memory["project_id"] == TEST_PROJECT_ID


async def test_api_memory_delete_broadcasts_project_id(
    http: httpx.AsyncClient, cleanup_memories: list[str]
) -> None:
    async with websockets.connect(_ws_url("integration_delete_ws")) as websocket:
        await asyncio.wait_for(websocket.recv(), timeout=5.0)

        content = unique_content("WebSocket REST delete test")
        response = await http.post(
            "/api/memories",
            json={
                "content": content,
                "project_id": TEST_PROJECT_ID,
                "category": "task",
                "source": "integration-websocket",
                "client": "pytest",
                "tags": ["websocket", "delete"],
            },
        )
        response.raise_for_status()
        memory_id = response.json()["id"]
        cleanup_memories.append(memory_id)
        await _wait_for_memory_created(websocket, memory_id)

        delete_response = await http.delete(f"/api/memories/{memory_id}")
        delete_response.raise_for_status()
        cleanup_memories.remove(memory_id)

        event = await _wait_for_memory_event(websocket, "memory_deleted", memory_id)
        assert event["data"]["project_id"] == TEST_PROJECT_ID
