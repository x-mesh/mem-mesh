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
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from ..mcp_common.tools import MCPToolHandlers
from ..mcp_common.schemas import get_tool_schemas
from ..core.version import SERVER_INFO, MCP_PROTOCOL_VERSION
from ..core.storage.base import StorageBackend

logger = logging.getLogger(__name__)

# SSE MCP Router
router = APIRouter(prefix="/mcp", tags=["MCP SSE"])

# 세션별 메시지 큐 (SSE 스트림용)
_sessions: Dict[str, asyncio.Queue] = {}

# Tool handlers (main.py에서 초기화됨)
_tool_handlers: Optional[MCPToolHandlers] = None


def set_tool_handlers(handlers: MCPToolHandlers) -> None:
    """Tool handlers 설정 (main.py에서 호출)"""
    global _tool_handlers
    _tool_handlers = handlers


def get_tool_handlers() -> MCPToolHandlers:
    """Tool handlers 반환"""
    if _tool_handlers is None:
        raise RuntimeError("MCP SSE tool handlers not initialized")
    return _tool_handlers


# -------------------------
# MCP Protocol Handlers
# -------------------------

def create_jsonrpc_response(id: Any, result: Any) -> Dict[str, Any]:
    """JSON-RPC 성공 응답 생성"""
    return {
        "jsonrpc": "2.0",
        "id": id,
        "result": result
    }


def create_jsonrpc_error(id: Any, code: int, message: str) -> Dict[str, Any]:
    """JSON-RPC 에러 응답 생성"""
    return {
        "jsonrpc": "2.0",
        "id": id,
        "error": {
            "code": code,
            "message": message
        }
    }


async def handle_initialize(params: Dict[str, Any]) -> Dict[str, Any]:
    """initialize 요청 처리"""
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {
            "tools": {},
        },
        "serverInfo": {
            "name": SERVER_INFO["name"],
            "version": SERVER_INFO["version"],
        },
    }


async def handle_tools_list() -> Dict[str, Any]:
    """tools/list 요청 처리"""
    return {"tools": get_tool_schemas()}


async def handle_tools_call(params: Dict[str, Any]) -> Dict[str, Any]:
    """tools/call 요청 처리"""
    name = params.get("name")
    args = params.get("arguments", {}) or {}
    
    if not name:
        return {
            "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing tool name"})}],
            "isError": True,
        }
    
    handlers = get_tool_handlers()
    
    try:
        if name == "add":
            if "content" not in args:
                return {
                    "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing required argument: content"})}],
                    "isError": True,
                }
            result = await handlers.add(
                content=args["content"],
                project_id=args.get("project_id"),
                category=args.get("category", "task"),
                source=args.get("source", "mcp-sse"),
                tags=args.get("tags")
            )
        
        elif name == "search":
            if "query" not in args:
                return {
                    "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing required argument: query"})}],
                    "isError": True,
                }
            result = await handlers.search(
                query=args["query"],
                project_id=args.get("project_id"),
                category=args.get("category"),
                limit=args.get("limit", 5),
                recency_weight=args.get("recency_weight", 0.0)
            )
        
        elif name == "context":
            if "memory_id" not in args:
                return {
                    "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing required argument: memory_id"})}],
                    "isError": True,
                }
            result = await handlers.context(
                memory_id=args["memory_id"],
                depth=args.get("depth", 2),
                project_id=args.get("project_id")
            )
        
        elif name == "update":
            if "memory_id" not in args:
                return {
                    "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing required argument: memory_id"})}],
                    "isError": True,
                }
            result = await handlers.update(
                memory_id=args["memory_id"],
                content=args.get("content"),
                category=args.get("category"),
                tags=args.get("tags")
            )
        
        elif name == "delete":
            if "memory_id" not in args:
                return {
                    "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing required argument: memory_id"})}],
                    "isError": True,
                }
            result = await handlers.delete(memory_id=args["memory_id"])
        
        elif name == "stats":
            result = await handlers.stats(
                project_id=args.get("project_id"),
                start_date=args.get("start_date"),
                end_date=args.get("end_date")
            )
        
        else:
            return {
                "content": [{"type": "text", "text": json.dumps({"success": False, "error": f"Unknown tool: {name}"})}],
                "isError": True,
            }
        
        return {"content": [{"type": "text", "text": json.dumps(result)}]}
    
    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return {
            "content": [{"type": "text", "text": json.dumps({"success": False, "error": str(e)})}],
            "isError": True,
        }


async def process_jsonrpc_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """JSON-RPC 요청 처리"""
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params", {})
    
    # Notification (id가 없으면 응답 불필요)
    if req_id is None:
        logger.debug(f"Received notification: {method}")
        return None
    
    try:
        if method == "initialize":
            result = await handle_initialize(params)
            return create_jsonrpc_response(req_id, result)
        
        elif method == "tools/list":
            result = await handle_tools_list()
            return create_jsonrpc_response(req_id, result)
        
        elif method == "tools/call":
            result = await handle_tools_call(params)
            return create_jsonrpc_response(req_id, result)
        
        elif method == "ping":
            return create_jsonrpc_response(req_id, {})
        
        else:
            return create_jsonrpc_error(req_id, -32601, f"Method not found: {method}")
    
    except Exception as e:
        logger.exception(f"Error processing request: {method}")
        return create_jsonrpc_error(req_id, -32603, f"Internal error: {str(e)}")


# -------------------------
# SSE Endpoints
# -------------------------

@router.get("/sse")
async def sse_endpoint(request: Request):
    """
    SSE 연결 엔드포인트.
    
    클라이언트가 이 엔드포인트에 연결하면 세션 ID를 받고,
    서버로부터 메시지를 SSE 스트림으로 수신합니다.
    """
    session_id = str(uuid.uuid4())
    _sessions[session_id] = asyncio.Queue()
    
    logger.info(f"SSE session created: {session_id}")
    
    async def event_generator():
        try:
            # 연결 시 세션 ID 전송
            yield {
                "event": "endpoint",
                "data": f"/mcp/message?session_id={session_id}"
            }
            
            # 메시지 대기 및 전송
            while True:
                if await request.is_disconnected():
                    break
                
                try:
                    # 타임아웃으로 연결 상태 확인
                    message = await asyncio.wait_for(
                        _sessions[session_id].get(),
                        timeout=30.0
                    )
                    yield {
                        "event": "message",
                        "data": json.dumps(message)
                    }
                except asyncio.TimeoutError:
                    # Keep-alive ping
                    yield {
                        "event": "ping",
                        "data": ""
                    }
        finally:
            # 세션 정리
            if session_id in _sessions:
                del _sessions[session_id]
            logger.info(f"SSE session closed: {session_id}")
    
    return EventSourceResponse(event_generator())


@router.post("/message")
async def message_endpoint(request: Request, session_id: str):
    """
    메시지 수신 엔드포인트.
    
    클라이언트가 JSON-RPC 요청을 POST로 전송하면,
    처리 결과를 해당 세션의 SSE 스트림으로 전송합니다.
    """
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # JSON-RPC 요청 검증
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        raise HTTPException(status_code=400, detail="Invalid JSON-RPC request")
    
    logger.debug(f"Received message for session {session_id}: {body.get('method')}")
    
    # 요청 처리
    response = await process_jsonrpc_request(body)
    
    # 응답이 있으면 SSE 스트림으로 전송
    if response:
        await _sessions[session_id].put(response)
    
    # HTTP 응답은 202 Accepted (실제 응답은 SSE로 전송)
    return {"status": "accepted"}


@router.post("/sse")
async def sse_post_endpoint(request: Request):
    """
    단일 요청-응답 방식의 MCP 엔드포인트.
    
    SSE 스트림 없이 단일 JSON-RPC 요청을 처리하고 응답합니다.
    간단한 테스트나 단발성 요청에 유용합니다.
    """
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


@router.get("/info")
async def mcp_info():
    """MCP 서버 정보 반환"""
    return {
        "name": SERVER_INFO["name"],
        "version": SERVER_INFO["version"],
        "protocol_version": MCP_PROTOCOL_VERSION,
        "transports": ["sse"],
        "endpoints": {
            "sse": "/mcp/sse",
            "message": "/mcp/message",
            "info": "/mcp/info"
        },
        "tools": [t["name"] for t in get_tool_schemas()]
    }
