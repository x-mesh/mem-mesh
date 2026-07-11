"""별표 MCP 도구(star/unstar) 전 트랜스포트 배선 테스트.

파라미터/도구가 5개 사이트에 동기화되지 않으면 조용히 누락된다 (anchored_path에서
실증된 드리프트). 여기서 각 사이트를 못 박는다:
  1. schemas.py   — get_all_tool_schemas() 노출
  2. descriptions — TOOL_DESCRIPTIONS 엔트리
  3. tools.py     — MCPToolHandlers.star / unstar
  4. dispatcher   — 라우팅 + 필수 인자 검증 (Pure stdio + HTTP/SSE 커버)
  5. FastMCP      — mcp_stdio/server.py (dispatcher가 커버하지 않음)
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mcp_common.descriptions import TOOL_DESCRIPTIONS
from app.mcp_common.dispatcher import MCPDispatcher
from app.mcp_common.schemas import get_all_tool_schemas
from app.mcp_common.tools import MCPToolHandlers


class TestStarSchemaExposure:
    """사이트 1·2: JSON 스키마 + 설명"""

    def test_star_and_unstar_registered(self):
        by_name = {t["name"]: t for t in get_all_tool_schemas()}
        assert "star" in by_name, "star tool not registered"
        assert "unstar" in by_name, "unstar tool not registered"

    @pytest.mark.parametrize("name", ["star", "unstar"])
    def test_star_schema_shape(self, name):
        by_name = {t["name"]: t for t in get_all_tool_schemas()}
        schema = by_name[name]["inputSchema"]
        assert schema["required"] == ["memory_id"]
        assert "memory_id" in schema["properties"]
        # strict clients reject unknown args — keep the surface closed
        assert schema["additionalProperties"] is False

    @pytest.mark.parametrize("name", ["star", "unstar"])
    def test_description_present(self, name):
        assert name in TOOL_DESCRIPTIONS
        assert TOOL_DESCRIPTIONS[name].strip()

    def test_star_schemas_share_no_mutable_state(self):
        """star/unstar가 같은 properties dict 객체를 공유하면 한쪽 수정이 번진다"""
        by_name = {t["name"]: t for t in get_all_tool_schemas()}
        star_props = by_name["star"]["inputSchema"]["properties"]
        unstar_props = by_name["unstar"]["inputSchema"]["properties"]
        assert star_props is not unstar_props


class TestStarHandlers:
    """사이트 3: MCPToolHandlers"""

    def _handlers(self):
        storage = MagicMock()
        memory_service = MagicMock()
        memory_service.set_starred = AsyncMock(
            side_effect=lambda mid, starred: {"memory_id": mid, "is_starred": starred}
        )
        storage.memory_service = memory_service
        handlers = MCPToolHandlers(storage, notifier=None, enable_compression=False)
        return handlers, memory_service

    @pytest.mark.asyncio
    async def test_star_calls_service_with_true(self):
        handlers, svc = self._handlers()
        result = await handlers.star("mem-1")
        assert result == {"memory_id": "mem-1", "is_starred": True}
        svc.set_starred.assert_awaited_once_with("mem-1", True)

    @pytest.mark.asyncio
    async def test_unstar_calls_service_with_false(self):
        handlers, svc = self._handlers()
        result = await handlers.unstar("mem-1")
        assert result == {"memory_id": "mem-1", "is_starred": False}
        svc.set_starred.assert_awaited_once_with("mem-1", False)

    @pytest.mark.asyncio
    async def test_api_backend_without_memory_service_raises(self):
        """APIStorageBackend에는 memory_service가 없다 — 조용히 성공하면 안 된다"""
        storage = MagicMock(spec=[])  # no memory_service attribute
        handlers = MCPToolHandlers(storage, notifier=None, enable_compression=False)
        with pytest.raises(RuntimeError, match="local memory service"):
            await handlers.star("mem-1")


class TestStarDispatcher:
    """사이트 4: dispatcher (Pure stdio + HTTP/SSE 트랜스포트가 이걸 탄다)"""

    @pytest.fixture
    def mock_handlers(self):
        handlers = MagicMock(spec=MCPToolHandlers)
        handlers.star = AsyncMock(
            return_value={"memory_id": "mem-1", "is_starred": True}
        )
        handlers.unstar = AsyncMock(
            return_value={"memory_id": "mem-1", "is_starred": False}
        )
        return handlers

    @pytest.fixture
    def dispatcher(self, mock_handlers):
        return MCPDispatcher(mock_handlers)

    @pytest.mark.asyncio
    async def test_dispatch_star(self, dispatcher, mock_handlers):
        result = await dispatcher.dispatch("star", {"memory_id": "mem-1"})
        assert result["isError"] is False
        mock_handlers.star.assert_awaited_once_with(memory_id="mem-1")

    @pytest.mark.asyncio
    async def test_dispatch_unstar(self, dispatcher, mock_handlers):
        result = await dispatcher.dispatch("unstar", {"memory_id": "mem-1"})
        assert result["isError"] is False
        mock_handlers.unstar.assert_awaited_once_with(memory_id="mem-1")

    @pytest.mark.asyncio
    async def test_dispatch_star_missing_memory_id(self, dispatcher):
        result = await dispatcher.dispatch("star", {})
        assert result["isError"] is True
        body = json.loads(result["content"][0]["text"])
        assert "memory_id" in body["error"].lower()


class TestStarFastMCP:
    """사이트 5: FastMCP — dispatcher가 커버하지 않는 별도 등록면.

    ``@mcp.tool()``은 함수를 FunctionTool로 감싸므로 모듈 속성은 더 이상 호출 가능한
    함수가 아니다. 레지스트리 조회 API(get_tools 등)는 fastmcp 버전마다 다르므로
    (CI에서 AttributeError로 실측), 버전에 따라 흔들리지 않는 표면 — 데코레이트된
    객체가 광고하는 이름 — 으로 검증한다.
    """

    @pytest.mark.parametrize("name", ["star", "unstar"])
    def test_fastmcp_registers_star_tools(self, name):
        import inspect

        from app.mcp_stdio import server

        tool = getattr(server, name, None)
        assert tool is not None, f"FastMCP {name} tool missing"
        # 데코레이터가 함수를 FunctionTool로 바꿔친다 — 여기 남아 있는 게 맨 함수라면
        # @mcp.tool()이 빠진 것이고, 그 도구는 FastMCP에 등록되지 않는다.
        assert not inspect.isfunction(tool), f"{name} is missing @mcp.tool()"
        assert getattr(tool, "name", None) == name
