"""
MCP Streamable HTTP Transport 엔드포인트.

MCP 2025-03-26 스펙의 Streamable HTTP transport 구현.
- 단일 엔드포인트에서 GET/POST 모두 지원
- Mcp-Session-Id 헤더로 세션 관리
- Accept 헤더에 따라 JSON 또는 SSE 응답

Spec: https://modelcontextprotocol.io/specification/2025-03-26/basic/transports
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.core.version import MCP_PROTOCOL_VERSION, SERVER_INFO
from app.mcp_common.dispatcher import MCPDispatcher
from app.mcp_common.schemas import get_all_tool_schemas
from app.mcp_common.tools import MCPToolHandlers
from app.mcp_common.transport import format_jsonrpc_error, format_jsonrpc_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["MCP Streamable HTTP"])

# 세션 저장소: session_id -> {"queue": Queue, "client_info": {...}}
_sessions: Dict[str, Dict[str, Any]] = {}
_tool_handlers: Optional[MCPToolHandlers] = None
_dispatcher: Optional[MCPDispatcher] = None


def _get_session_queue(session_id: str) -> asyncio.Queue:
    """세션의 Queue를 반환. dict/Queue 양쪽 호환."""
    s = _sessions.get(session_id)
    if s is None:
        raise KeyError(f"Session not found: {session_id}")
    return s["queue"] if isinstance(s, dict) else s


def _create_session(session_id: str, client_info: Optional[Dict] = None) -> None:
    """새 세션을 dict 형태로 생성."""
    _sessions[session_id] = {
        "queue": asyncio.Queue(),
        "client_info": client_info or {},
    }


def _detect_client_from_request(request: Request) -> str:
    """User-Agent 헤더에서 MCP 클라이언트 감지 (fallback).

    순서 중요: 구체적인 패턴을 먼저 매칭해야 오탐 방지.
    예) "cursor" 보다 "antigravity"가 먼저 와야 함 (일부 UA에 여러 키워드 포함 가능).
    """
    ua = (request.headers.get("user-agent") or "").lower()
    if not ua:
        return ""

    # --- AI coding agents / IDE extensions ---
    # 구체적 → 일반적 순서
    _CLIENT_PATTERNS: list[tuple[list[str], str]] = [
        # AI coding agents
        (["antigravity"], "antigravity"),
        (["kiro"], "kiro"),
        (["cline"], "cline"),
        (["continue.dev", "continue/"], "continue"),
        (["aider"], "aider"),
        (["copilot"], "copilot"),
        (["cody"], "cody"),
        (["tabnine"], "tabnine"),
        (["supermaven"], "supermaven"),
        (["double.bot", "double-bot"], "double"),
        (["sourcegraph"], "sourcegraph"),
        (["codium", "windsurf"], "windsurf"),
        # IDEs / Editors
        (["cursor"], "cursor"),
        (["zed.dev", "zed/"], "zed"),
        (["neovim", "nvim"], "neovim"),
        (["emacs"], "emacs"),
        (["jetbrains", "intellij", "pycharm", "webstorm", "goland", "rider", "phpstorm", "rubymine", "clion", "datagrip"], "jetbrains"),
        (["vscode", "visual studio code", "vs code"], "vscode"),
        (["visual studio"], "visual-studio"),
        (["sublime"], "sublime"),
        (["eclipse"], "eclipse"),
        (["xcode"], "xcode"),
        # AI platforms (web / API)
        (["claude-code", "claudecode"], "claude-code"),
        (["claude", "anthropic"], "claude"),
        (["chatgpt", "openai"], "chatgpt"),
        (["gemini"], "gemini"),
        (["perplexity"], "perplexity"),
    ]

    for patterns, client_name in _CLIENT_PATTERNS:
        if any(p in ua for p in patterns):
            return client_name

    return ""


def set_tool_handlers(handlers: MCPToolHandlers, batch_handler=None) -> None:
    global _tool_handlers, _dispatcher
    _tool_handlers = handlers
    _dispatcher = MCPDispatcher(handlers, batch_handler=batch_handler)


def get_tool_handlers() -> MCPToolHandlers:
    if _tool_handlers is None:
        raise RuntimeError("MCP tool handlers not initialized")
    return _tool_handlers


def get_dispatcher() -> MCPDispatcher:
    if _dispatcher is None:
        raise RuntimeError("MCP dispatcher not initialized")
    return _dispatcher


async def handle_initialize(params: Dict[str, Any]) -> Dict[str, Any]:
    """Initialize 요청 처리 - 새 세션 생성"""
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {
            "name": SERVER_INFO["name"],
            "version": SERVER_INFO["version"],
        },
    }


async def handle_tools_list() -> Dict[str, Any]:
    """tools/list 요청 처리"""
    return {"tools": get_all_tool_schemas()}


async def handle_tools_call(params: Dict[str, Any]) -> Dict[str, Any]:
    """tools/call 요청 처리"""
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


async def process_jsonrpc_request(
    request: Dict[str, Any],
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    JSON-RPC 요청 처리

    Returns:
        tuple: (response, new_session_id)
        - response: JSON-RPC 응답 (notification인 경우 None)
        - new_session_id: initialize 요청 시 새로 생성된 세션 ID
    """
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params", {})
    new_session_id = None

    # Notification (id가 없음) - 응답 불필요
    if req_id is None:
        logger.debug(f"Received notification: {method}")
        return None, None

    try:
        if method == "initialize":
            result = await handle_initialize(params)
            # 새 세션 ID 생성 + clientInfo 저장
            new_session_id = str(uuid.uuid4())
            client_info = params.get("clientInfo", {}) if params else {}
            _create_session(new_session_id, client_info)
            logger.info(f"New session created: {new_session_id}, client: {client_info.get('name', 'unknown')}")
            return format_jsonrpc_response(result, req_id), new_session_id

        elif method == "tools/list":
            result = await handle_tools_list()
            return format_jsonrpc_response(result, req_id), None

        elif method == "tools/call":
            result = await handle_tools_call(params)
            return format_jsonrpc_response(result, req_id), None

        elif method == "ping":
            return format_jsonrpc_response({}, req_id), None

        else:
            return (
                format_jsonrpc_error(f"Method not found: {method}", req_id, -32601),
                None,
            )

    except Exception as e:
        logger.exception(f"Error processing request: {method}")
        return format_jsonrpc_error(f"Internal error: {str(e)}", req_id), None


def accepts_sse(accept_header: Optional[str]) -> bool:
    """Accept 헤더가 SSE를 지원하는지 확인"""
    if not accept_header:
        return False
    return "text/event-stream" in accept_header


def accepts_json(accept_header: Optional[str]) -> bool:
    """Accept 헤더가 JSON을 지원하는지 확인"""
    if not accept_header:
        return True  # 기본값
    return "application/json" in accept_header or "*/*" in accept_header


@router.get("/sse")
async def streamable_http_get(
    request: Request,
    accept: Optional[str] = Header(None),
    mcp_session_id: Optional[str] = Header(None, alias="Mcp-Session-Id"),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
):
    """
    Streamable HTTP GET - SSE 스트림 연결

    클라이언트가 서버로부터 메시지를 받기 위한 SSE 스트림을 엽니다.
    """
    # SSE를 지원하지 않으면 405
    if not accepts_sse(accept):
        raise HTTPException(
            status_code=405, detail="This endpoint requires Accept: text/event-stream"
        )

    # 세션 ID가 없으면 새 세션 생성 (backwards compatibility)
    session_id = mcp_session_id
    if not session_id:
        session_id = str(uuid.uuid4())
        _create_session(session_id)
        logger.info(f"SSE stream opened with new session: {session_id}")
    elif session_id not in _sessions:
        # 세션이 만료됨
        raise HTTPException(status_code=404, detail="Session not found")
    else:
        logger.info(f"SSE stream opened for existing session: {session_id}")

    async def event_generator():
        event_id = 0
        try:
            # 기존 SSE transport 호환성: endpoint 이벤트 전송
            yield {
                "event": "endpoint",
                "data": f"/mcp/message?session_id={session_id}",
                "id": str(event_id),
            }
            event_id += 1

            while True:
                if await request.is_disconnected():
                    break

                try:
                    message = await asyncio.wait_for(
                        _get_session_queue(session_id).get(), timeout=30.0
                    )
                    yield {
                        "event": "message",
                        "data": json.dumps(message),
                        "id": str(event_id),
                    }
                    event_id += 1
                except asyncio.TimeoutError:
                    # Keep-alive ping
                    yield {"event": "ping", "data": "", "id": str(event_id)}
                    event_id += 1
        finally:
            logger.info(f"SSE stream closed: {session_id}")

    response = EventSourceResponse(event_generator())
    if session_id:
        response.headers["Mcp-Session-Id"] = session_id
    return response


@router.post("/sse")
async def streamable_http_post(
    request: Request,
    accept: Optional[str] = Header(None),
    mcp_session_id: Optional[str] = Header(None, alias="Mcp-Session-Id"),
):
    """
    Streamable HTTP POST - JSON-RPC 요청 처리

    클라이언트가 서버로 JSON-RPC 메시지를 보냅니다.
    Accept 헤더에 따라 JSON 또는 SSE로 응답합니다.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        # ClientDisconnect — 클라이언트가 요청 중간에 연결 해제
        if "Disconnect" in type(e).__name__:
            logger.debug(f"Client disconnected during request read: {type(e).__name__}")
            return Response(status_code=499)
        raise

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        raise HTTPException(status_code=400, detail="Invalid JSON-RPC request")

    method = body.get("method")
    logger.debug(f"POST request: method={method}, session={mcp_session_id}")

    # 세션 검증 (initialize 제외)
    if method != "initialize" and mcp_session_id:
        if mcp_session_id not in _sessions:
            # 세션 자동 복구 (서버 재시작 등)
            _create_session(mcp_session_id)
            logger.info(f"Session auto-recovered: {mcp_session_id}")

    # tools/call: 세션의 clientInfo 또는 User-Agent에서 client 자동 주입
    if method == "tools/call":
        client_name = ""
        if mcp_session_id:
            session_data = _sessions.get(mcp_session_id, {})
            client_name = session_data.get("client_info", {}).get("name", "")
        if not client_name:
            client_name = _detect_client_from_request(request)
            # 감지된 client를 세션에 저장 (이후 요청에서 재감지 불필요)
            if client_name and mcp_session_id and mcp_session_id in _sessions:
                _sessions[mcp_session_id]["client_info"]["name"] = client_name
        if client_name:
            params = body.get("params", {})
            args = params.get("arguments", {})
            if not args.get("client"):
                args["client"] = client_name
                logger.debug(f"Auto-injected client={client_name}")

    # 요청 처리
    response, new_session_id = await process_jsonrpc_request(body)

    # Notification인 경우 (응답 없음)
    if response is None:
        return Response(status_code=202)

    # SSE 스트림으로 응답할지 JSON으로 응답할지 결정
    # Streamable HTTP에서는 기본적으로 JSON 응답
    # (SSE는 여러 응답이 필요한 경우에만 사용)

    # JSON 응답 생성
    json_response = JSONResponse(content=response)

    # initialize 응답에 세션 ID 포함
    if new_session_id:
        json_response.headers["Mcp-Session-Id"] = new_session_id

    return json_response


@router.delete("/sse")
async def streamable_http_delete(
    mcp_session_id: Optional[str] = Header(None, alias="Mcp-Session-Id"),
):
    """
    Streamable HTTP DELETE - 세션 종료

    클라이언트가 세션을 명시적으로 종료합니다.
    """
    if not mcp_session_id:
        raise HTTPException(status_code=400, detail="Mcp-Session-Id header required")

    if mcp_session_id in _sessions:
        del _sessions[mcp_session_id]
        logger.info(f"Session terminated: {mcp_session_id}")
        return Response(status_code=204)
    else:
        raise HTTPException(status_code=404, detail="Session not found")


# ============================================================
# 기존 HTTP+SSE transport 호환성 엔드포인트 (deprecated)
# ============================================================


@router.post("/message")
async def legacy_message_endpoint(
    request: Request, session_id: str, auto_create: bool = True
):
    """
    [DEPRECATED] 기존 HTTP+SSE transport의 message 엔드포인트

    새 클라이언트는 POST /mcp/sse를 사용하세요.
    """
    if session_id not in _sessions:
        await asyncio.sleep(0.05)

    if session_id not in _sessions:
        if auto_create:
            _create_session(session_id)
            logger.info(f"Auto-created session (legacy): {session_id}")
        else:
            raise HTTPException(status_code=404, detail="Session not found")

    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        if "Disconnect" in type(e).__name__:
            logger.debug(f"Client disconnected during legacy request: {type(e).__name__}")
            return Response(status_code=499)
        raise

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        raise HTTPException(status_code=400, detail="Invalid JSON-RPC request")

    logger.debug(f"Legacy message for session {session_id}: {body.get('method')}")

    response, _ = await process_jsonrpc_request(body)

    if response:
        await _get_session_queue(session_id).put(response)

    return {"status": "accepted"}


@router.post("/tools/call")
async def stateless_tools_call(request: Request):
    """Stateless tools/call 엔드포인트 (세션 불필요)"""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        if "Disconnect" in type(e).__name__:
            logger.debug(f"Client disconnected during tools/call: {type(e).__name__}")
            return Response(status_code=499)
        raise

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        raise HTTPException(status_code=400, detail="Invalid JSON-RPC request")

    # User-Agent에서 client 자동 주입
    if body.get("method") == "tools/call":
        client_name = _detect_client_from_request(request)
        if client_name:
            args = body.get("params", {}).get("arguments", {})
            if not args.get("client"):
                args["client"] = client_name

    response, _ = await process_jsonrpc_request(body)
    return response if response else {"status": "processed"}


@router.get("/info")
async def mcp_info():
    """MCP 서버 정보"""
    return {
        "name": SERVER_INFO["name"],
        "version": SERVER_INFO["version"],
        "protocol_version": MCP_PROTOCOL_VERSION,
        "transports": ["streamable-http", "sse"],
        "endpoints": {
            "streamable_http": "/mcp/sse",
            "sse": "/mcp/sse",
            "message": "/mcp/message",
            "tools_call": "/mcp/tools/call",
            "info": "/mcp/info",
        },
        "tools": [t["name"] for t in get_all_tool_schemas()],
        "notes": {
            "streamable_http": "MCP 2025-03-26 Streamable HTTP transport",
            "sse": "Legacy HTTP+SSE transport (deprecated)",
            "stateless": "Use POST /mcp/tools/call for session-less requests",
        },
    }
