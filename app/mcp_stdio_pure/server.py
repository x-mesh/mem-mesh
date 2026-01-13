#!/usr/bin/env python3
"""
mem-mesh Pure MCP Server — stdio (순수 MCP 프로토콜 구현)

mcp_common 모듈을 사용하여 공통 로직을 공유합니다.
FastMCP 대신 직접 MCP 프로토콜을 구현하여 안정성 향상.
"""

import sys
import os
import json
import logging
import asyncio
from typing import Optional, Dict, Any
from pydantic import ValidationError

from ..core.config import Settings
from ..mcp_common.storage import StorageManager
from ..mcp_common.tools import MCPToolHandlers
from ..mcp_common.schemas import get_tool_schemas, SERVER_INFO


# -------------------------
# Logging (stderr + optional file)
# -------------------------
def setup_logging():
    """환경변수 기반 로깅 설정"""
    log_level_str = os.environ.get("MCP_LOG_LEVEL", "INFO").upper()
    log_file = os.environ.get("MCP_LOG_FILE", "")
    
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    log_level = level_map.get(log_level_str, logging.INFO)
    
    logger = logging.getLogger("mem-mesh-mcp-pure")
    logger.setLevel(log_level)
    logger.handlers.clear()
    
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(log_level)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)
    
    if log_file:
        try:
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(log_level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logger.info(f"File logging enabled: {log_file}")
        except Exception as e:
            logger.warning(f"Could not create log file {log_file}: {e}")
    
    logger.info(f"Logging initialized: level={log_level_str}, file={log_file or 'none'}")
    return logger


log = setup_logging()

# -------------------------
# Global instances
# -------------------------
storage_manager = StorageManager()
tool_handlers: Optional[MCPToolHandlers] = None

# Global stdin reader for reuse
_stdin_reader: Optional[asyncio.StreamReader] = None


# -------------------------
# Transport: NDJSON
# -------------------------
def write_message(payload: Dict[str, Any]) -> None:
    """Write message to stdout as NDJSON"""
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def write_result(id_value: Any, result: Any) -> None:
    write_message({"jsonrpc": "2.0", "id": id_value, "result": result})


def write_error(id_value: Any, code: int, message: str) -> None:
    write_message({"jsonrpc": "2.0", "id": id_value, "error": {"code": code, "message": message}})


async def get_stdin_reader() -> asyncio.StreamReader:
    """Get or create async stdin reader"""
    global _stdin_reader
    if _stdin_reader is None:
        loop = asyncio.get_running_loop()
        _stdin_reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(_stdin_reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    return _stdin_reader


async def read_line_async() -> Optional[str]:
    """Read a single line from stdin asynchronously"""
    try:
        reader = await get_stdin_reader()
        line = await reader.readline()
        if not line:
            return None
        return line.decode('utf-8').strip()
    except Exception as e:
        log.error(f"Error reading line: {e}")
        return None


def parse_message(line: str) -> Optional[Dict[str, Any]]:
    """Parse and validate a JSON-RPC message"""
    if not line:
        return None
    
    try:
        message = json.loads(line)
        
        if not isinstance(message, dict):
            log.warning(f"Invalid message format: not a dictionary")
            return None
        
        if "jsonrpc" not in message or message["jsonrpc"] != "2.0":
            log.warning(f"Invalid jsonrpc version")
            return None
        
        return message
    except json.JSONDecodeError as e:
        log.error(f"Error decoding message: {e}")
        return None


# -------------------------
# MCP Protocol Handlers
# -------------------------
def resp_initialize(params: Dict[str, Any]) -> Dict[str, Any]:
    """Handle initialize request"""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {
            "name": SERVER_INFO["name"],
            "version": SERVER_INFO["version"],
        },
    }


def list_tools() -> Dict[str, Any]:
    """List available tools"""
    return {"tools": get_tool_schemas()}


async def call_tool(params: Dict[str, Any]) -> Dict[str, Any]:
    """Handle tool call using shared MCPToolHandlers"""
    name = params.get("name")
    args = params.get("arguments", {}) or {}
    
    if not name:
        log.error("Missing tool name")
        return {
            "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing tool name"})}],
            "isError": True,
        }
    
    log.info(f"tools/call: {name}")
    
    if tool_handlers is None:
        log.error("Tool handlers not initialized")
        return {
            "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Storage not initialized"})}],
            "isError": True,
        }
    
    try:
        if name == "add":
            if "content" not in args:
                return {
                    "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing required argument: content"})}],
                    "isError": True,
                }
            result = await tool_handlers.add(
                content=args["content"],
                project_id=args.get("project_id"),
                category=args.get("category", "task"),
                source=args.get("source", "mcp"),
                tags=args.get("tags")
            )
        
        elif name == "search":
            if "query" not in args:
                return {
                    "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing required argument: query"})}],
                    "isError": True,
                }
            result = await tool_handlers.search(
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
            result = await tool_handlers.context(
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
            result = await tool_handlers.update(
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
            result = await tool_handlers.delete(memory_id=args["memory_id"])
        
        elif name == "stats":
            result = await tool_handlers.stats(
                project_id=args.get("project_id"),
                start_date=args.get("start_date"),
                end_date=args.get("end_date")
            )
        
        else:
            log.warning(f"Unknown tool: {name}")
            return {
                "content": [{"type": "text", "text": json.dumps({"success": False, "error": f"Unknown tool: {name}"})}],
                "isError": True,
            }
        
        return {"content": [{"type": "text", "text": json.dumps(result)}]}
    
    except ValidationError as ve:
        log.error(f"Validation error in tool {name}: {ve}")
        return {
            "content": [{"type": "text", "text": json.dumps({"success": False, "error": f"Validation error: {str(ve)}"})}],
            "isError": True,
        }
    except Exception as e:
        log.exception(f"Error in tool {name}")
        return {
            "content": [{"type": "text", "text": json.dumps({"success": False, "error": str(e)})}],
            "isError": True,
        }


# -------------------------
# Storage initialization
# -------------------------
async def initialize_storage():
    """Initialize storage backend"""
    global tool_handlers
    
    storage = await storage_manager.initialize()
    tool_handlers = MCPToolHandlers(storage)
    log.info("Tool handlers initialized")


# -------------------------
# Main loop
# -------------------------
async def main():
    log.info("Starting mem-mesh Pure MCP Server (stdio, NDJSON)")
    
    await initialize_storage()
    
    import signal
    shutdown_requested = asyncio.Event()
    
    def request_shutdown():
        log.info("Received interrupt signal, initiating graceful shutdown...")
        shutdown_requested.set()
    
    loop = asyncio.get_running_loop()
    if hasattr(signal, 'SIGTERM'):
        loop.add_signal_handler(signal.SIGTERM, request_shutdown)
    if hasattr(signal, 'SIGINT'):
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
            
            # Notifications: no response
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
                    result = await asyncio.wait_for(call_tool(req.get("params", {})), timeout=60.0)
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
                log.exception("Error handling request")
                write_error(req_id, -32603, f"Internal error: {e}")
        except asyncio.CancelledError:
            log.info("Main loop cancelled")
            break
        except Exception as e:
            log.exception(f"Unexpected error: {e}")
            continue
    
    log.info("Performing cleanup...")
    await storage_manager.shutdown()
    log.info("Server shutdown completed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
