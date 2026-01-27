#!/usr/bin/env python3
"""
mem-mesh Pure MCP Server — stdio (순수 MCP 프로토콜 구현)

mcp_common 모듈을 사용하여 공통 로직을 공유합니다.
FastMCP 대신 직접 MCP 프로토콜을 구현하여 안정성 향상.
"""

import sys
import json
import asyncio
from typing import Optional, Dict, Any

from ..core.version import SERVER_INFO, MCP_PROTOCOL_VERSION
from ..core.utils.logger import setup_logging
from ..mcp_common.storage import StorageManager
from ..mcp_common.tools import MCPToolHandlers
from ..mcp_common.dispatcher import MCPDispatcher
from ..mcp_common.transport import format_tool_error

log = setup_logging("mem-mesh-mcp-pure")

storage_manager = StorageManager()
tool_handlers: Optional[MCPToolHandlers] = None
dispatcher: Optional[MCPDispatcher] = None
batch_handler: Optional["BatchOperationHandler"] = None
_stdin_reader: Optional[asyncio.StreamReader] = None


def write_message(payload: Dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def write_result(id_value: Any, result: Any) -> None:
    write_message({"jsonrpc": "2.0", "id": id_value, "result": result})


def write_error(id_value: Any, code: int, message: str) -> None:
    write_message(
        {"jsonrpc": "2.0", "id": id_value, "error": {"code": code, "message": message}}
    )


async def get_stdin_reader() -> asyncio.StreamReader:
    global _stdin_reader
    if _stdin_reader is None:
        loop = asyncio.get_running_loop()
        _stdin_reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(_stdin_reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    return _stdin_reader


async def read_line_async() -> Optional[str]:
    try:
        reader = await get_stdin_reader()
        line = await reader.readline()
        if not line:
            return None
        return line.decode("utf-8").strip()
    except Exception as e:
        log.error(f"Error reading line: {e}")
        return None


def parse_message(line: str) -> Optional[Dict[str, Any]]:
    if not line:
        return None

    try:
        message = json.loads(line)

        if not isinstance(message, dict):
            log.warning("Invalid message format: not a dictionary")
            return None

        if "jsonrpc" not in message or message["jsonrpc"] != "2.0":
            log.warning("Invalid jsonrpc version")
            return None

        return message
    except json.JSONDecodeError as e:
        log.error(f"Error decoding message: {e}")
        return None


def resp_initialize(params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {
            "name": SERVER_INFO["name"],
            "version": SERVER_INFO["version"],
        },
    }


def list_tools() -> Dict[str, Any]:
    from ..mcp_common.schemas import get_all_tool_schemas

    return {"tools": get_all_tool_schemas()}


async def call_tool(params: Dict[str, Any]) -> Dict[str, Any]:
    name = params.get("name")
    args = params.get("arguments", {}) or {}

    if not name:
        log.error("Missing tool name")
        return format_tool_error("Missing tool name")

    log.info(f"tools/call: {name}")

    if dispatcher is None:
        log.error("Dispatcher not initialized")
        return format_tool_error("Storage not initialized")

    if name == "batch_operations":
        return await _handle_batch_operations(args)

    return await dispatcher.dispatch(name, args)


async def _handle_batch_operations(args: Dict[str, Any]) -> Dict[str, Any]:
    if "operations" not in args:
        return format_tool_error("Missing required argument: operations")

    if batch_handler is None:
        return format_tool_error("Batch handler not initialized")

    result = await batch_handler.batch_operations(operations=args["operations"])
    return {"content": [{"type": "text", "text": json.dumps(result)}], "isError": False}


async def initialize_storage():
    global tool_handlers, dispatcher, batch_handler

    storage = await storage_manager.initialize()
    tool_handlers = MCPToolHandlers(storage)
    dispatcher = MCPDispatcher(tool_handlers)

    from ..core.database.base import Database
    from ..core.embeddings.service import EmbeddingService
    from ..core.services.memory import MemoryService
    from ..core.services.legacy.search import SearchService
    from ..mcp_common.batch_tools import BatchOperationHandler

    db = Database()
    embedding_service = EmbeddingService(preload=False)
    memory_service = MemoryService(db, embedding_service)
    search_service = SearchService(db, embedding_service)

    batch_handler = BatchOperationHandler(
        memory_service=memory_service,
        search_service=search_service,
        embedding_service=embedding_service,
        db=db,
    )

    log.info("Tool handlers and batch handler initialized")


async def main():
    log.info("Starting mem-mesh Pure MCP Server (stdio, NDJSON)")

    await initialize_storage()

    import signal

    shutdown_requested = asyncio.Event()

    def request_shutdown():
        log.info("Received interrupt signal, initiating graceful shutdown...")
        shutdown_requested.set()

    loop = asyncio.get_running_loop()
    if hasattr(signal, "SIGTERM"):
        loop.add_signal_handler(signal.SIGTERM, request_shutdown)
    if hasattr(signal, "SIGINT"):
        loop.add_signal_handler(signal.SIGINT, request_shutdown)

    log.info("Server ready, waiting for messages...")

    while not shutdown_requested.is_set():
        try:
            line = await read_line_async()

            if line is None:
                log.info("EOF received; exiting")
                break

            req = parse_message(line)
            if req is None:
                continue

            method = req.get("method")
            req_id = req.get("id")

            if req_id is None:
                log.debug(f"Notification received: {method}")
                continue

            try:
                if method == "initialize":
                    result = resp_initialize(req.get("params", {}))
                    write_result(req_id, result)
                elif method == "tools/list":
                    result = list_tools()
                    write_result(req_id, result)
                elif method == "tools/call":
                    result = await asyncio.wait_for(
                        call_tool(req.get("params", {})), timeout=60.0
                    )
                    write_result(req_id, result)
                elif method == "ping":
                    write_result(req_id, {})
                elif method == "shutdown":
                    write_result(req_id, {})
                    log.info("Shutdown request received")
                    break
                else:
                    write_error(req_id, -32601, f"Method not found: {method}")
            except asyncio.TimeoutError:
                log.error("Request handling timed out")
                write_error(req_id, -32603, "Request handling timed out")
            except Exception as e:
                log.error(f"Error handling request: {e}")
                write_error(req_id, -32603, f"Internal error: {e}")
        except asyncio.CancelledError:
            log.info("Main loop cancelled")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            continue

    log.info("Performing cleanup...")
    await storage_manager.shutdown()
    log.info("Server shutdown completed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
