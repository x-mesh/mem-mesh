"""
MCP over SSE (Server-Sent Events) 엔드포인트.

HTTP 기반으로 MCP 프로토콜을 사용할 수 있게 해주는 transport입니다.
- 클라이언트 → 서버: HTTP POST /mcp/sse (JSON-RPC 요청)
- 서버 → 클라이언트: SSE 스트림으로 응답

MCP SSE Transport Spec:
https://spec.modelcontextprotocol.io/specification/basic/transports/#http-with-sse
"""

import json
import asyncio
import uuid
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.mcp_common.tools import MCPToolHandlers
from app.mcp_common.schemas import get_all_tool_schemas
from app.mcp_common.dispatcher import MCPDispatcher
from app.mcp_common.transport import format_jsonrpc_response, format_jsonrpc_error
from app.core.version import SERVER_INFO, MCP_PROTOCOL_VERSION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["MCP SSE"])

_sessions: Dict[str, asyncio.Queue] = {}
_tool_handlers: Optional[MCPToolHandlers] = None
_dispatcher: Optional[MCPDispatcher] = None


def set_tool_handlers(handlers: MCPToolHandlers) -> None:
    global _tool_handlers, _dispatcher
    _tool_handlers = handlers
    _dispatcher = MCPDispatcher(handlers)


def get_tool_handlers() -> MCPToolHandlers:
    if _tool_handlers is None:
        raise RuntimeError("MCP SSE tool handlers not initialized")
    return _tool_handlers


def get_dispatcher() -> MCPDispatcher:
    if _dispatcher is None:
        raise RuntimeError("MCP SSE dispatcher not initialized")
    return _dispatcher


async def handle_initialize(params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {
            "name": SERVER_INFO["name"],
            "version": SERVER_INFO["version"],
        },
    }


async def handle_tools_list() -> Dict[str, Any]:
    return {"tools": get_all_tool_schemas()}


async def handle_tools_call(params: Dict[str, Any]) -> Dict[str, Any]:
    name = params.get("name")
    args = params.get("arguments", {}) or {}

    if not name:
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"success": False, "error": "Missing tool name"}
                    ),
                }
            ],
            "isError": True,
        }

    return await get_dispatcher().dispatch(name, args)


async def process_jsonrpc_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params", {})

    if req_id is None:
        logger.debug(f"Received notification: {method}")
        return None

    try:
        if method == "initialize":
            result = await handle_initialize(params)
            return format_jsonrpc_response(result, req_id)

        elif method == "tools/list":
            result = await handle_tools_list()
            return format_jsonrpc_response(result, req_id)

        elif method == "tools/call":
            result = await handle_tools_call(params)
            return format_jsonrpc_response(result, req_id)

        elif method == "ping":
            return format_jsonrpc_response({}, req_id)

        else:
            return format_jsonrpc_error(f"Method not found: {method}", req_id, -32601)

    except Exception as e:
        logger.exception(f"Error processing request: {method}")
        return format_jsonrpc_error(f"Internal error: {str(e)}", req_id)


@router.get("/sse")
async def sse_endpoint(request: Request):
    session_id = str(uuid.uuid4())
    _sessions[session_id] = asyncio.Queue()

    logger.info(f"SSE session created: {session_id}")

    async def event_generator():
        try:
            yield {"event": "endpoint", "data": f"/mcp/message?session_id={session_id}"}

            while True:
                if await request.is_disconnected():
                    break

                try:
                    message = await asyncio.wait_for(
                        _sessions[session_id].get(), timeout=30.0
                    )
                    yield {"event": "message", "data": json.dumps(message)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            if session_id in _sessions:
                del _sessions[session_id]
            logger.info(f"SSE session closed: {session_id}")

    return EventSourceResponse(event_generator())


@router.post("/message")
async def message_endpoint(request: Request, session_id: str, auto_create: bool = True):
    if session_id not in _sessions:
        await asyncio.sleep(0.05)

    if session_id not in _sessions:
        _sessions[session_id] = asyncio.Queue()
        logger.info(f"Auto-created session (server restart recovery): {session_id}")

    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        raise HTTPException(status_code=400, detail="Invalid JSON-RPC request")

    logger.debug(f"Received message for session {session_id}: {body.get('method')}")

    response = await process_jsonrpc_request(body)

    if response:
        await _sessions[session_id].put(response)

    return {"status": "accepted"}


@router.post("/sse")
async def sse_post_endpoint(request: Request):
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        raise HTTPException(status_code=400, detail="Invalid JSON-RPC request")

    response = await process_jsonrpc_request(body)

    if response:
        return response
    else:
        return {"status": "notification received"}


@router.post("/tools/call")
async def stateless_tools_call(request: Request):
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        raise HTTPException(status_code=400, detail="Invalid JSON-RPC request")

    method = body.get("method")
    if method != "tools/call":
        response = await process_jsonrpc_request(body)
        if response:
            return response
        return {"status": "notification received"}

    response = await process_jsonrpc_request(body)
    return response if response else {"status": "processed"}


@router.get("/info")
async def mcp_info():
    return {
        "name": SERVER_INFO["name"],
        "version": SERVER_INFO["version"],
        "protocol_version": MCP_PROTOCOL_VERSION,
        "transports": ["sse", "stateless"],
        "endpoints": {
            "sse": "/mcp/sse",
            "message": "/mcp/message",
            "tools_call": "/mcp/tools/call",
            "info": "/mcp/info",
        },
        "tools": [t["name"] for t in get_all_tool_schemas()],
        "notes": {
            "stateless": "Use POST /mcp/sse or /mcp/tools/call for session-less requests",
            "auto_create": "Add ?auto_create=true to /mcp/message to auto-create sessions",
        },
    }
