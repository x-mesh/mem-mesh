#!/usr/bin/env python3
"""
mem-mesh Pure MCP Server — stdio (순수 MCP 프로토콜 구현)

upnote MCP 서버를 참조하여 순수 MCP 프로토콜로 구현
FastMCP 대신 직접 MCP 프로토콜을 구현하여 안정성 향상
"""

import sys
import os
import json
import logging
import asyncio
from typing import Optional, Dict, Any, List, Union
from pydantic import ValidationError

from ..core.config import Settings
from ..core.storage.direct import DirectStorageBackend
from ..core.storage.api import APIStorageBackend
from ..core.schemas.requests import AddParams, SearchParams, UpdateParams, StatsParams

# -------------------------
# Logging (stderr + optional file)
# -------------------------
def setup_logging():
    """환경변수 기반 로깅 설정"""
    log_level_str = os.environ.get("MCP_LOG_LEVEL", "INFO").upper()
    log_file = os.environ.get("MCP_LOG_FILE", "")
    
    # 로그 레벨 매핑
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    log_level = level_map.get(log_level_str, logging.INFO)
    
    # 로거 생성
    logger = logging.getLogger("mem-mesh-mcp-server")
    logger.setLevel(log_level)
    
    # 기존 핸들러 제거
    logger.handlers.clear()
    
    # 포맷터 설정
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    
    # stderr 핸들러 추가
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(log_level)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)
    
    # 파일 로깅 추가
    if log_file:
        try:
            # 디렉토리 생성
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
# Server Info
# -------------------------
SERVER_INFO = {
    "name": "mem-mesh",
    "version": "1.0.0",
    "description": "MCP server for mem-mesh memory management (stdio)",
}

# -------------------------
# Global storage
# -------------------------
storage: Optional[Union[DirectStorageBackend, APIStorageBackend]] = None

# -------------------------
# Transport: NDJSON only (simplified)
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

async def read_message_async() -> Optional[Dict[str, Any]]:
    """Read message from stdin as NDJSON with validation (async version)"""
    try:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        
        line = await reader.readline()
        if not line:
            return None

        # Strip whitespace and validate it's a valid JSON object
        stripped_line = line.decode('utf-8').strip()
        if not stripped_line:
            return None

        message = json.loads(stripped_line)

        # Validate basic JSON-RPC structure
        if not isinstance(message, dict):
            log.warning(f"Invalid message format: not a dictionary - {stripped_line[:100]}")
            return None

        # Check for required fields
        if "jsonrpc" not in message:
            log.warning(f"Invalid message: missing jsonrpc field - {stripped_line[:100]}")
            return None

        if message["jsonrpc"] != "2.0":
            log.warning(f"Invalid message: unsupported jsonrpc version - {message['jsonrpc']}")
            return None

        return message
    except (json.JSONDecodeError, EOFError) as e:
        log.error(f"Error decoding message: {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error reading message: {e}")
        return None


# Global stdin reader for reuse
_stdin_reader: Optional[asyncio.StreamReader] = None


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

        # Validate basic JSON-RPC structure
        if not isinstance(message, dict):
            log.warning(f"Invalid message format: not a dictionary - {line[:100]}")
            return None

        # Check for required fields
        if "jsonrpc" not in message:
            log.warning(f"Invalid message: missing jsonrpc field - {line[:100]}")
            return None

        if message["jsonrpc"] != "2.0":
            log.warning(f"Invalid message: unsupported jsonrpc version - {message['jsonrpc']}")
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
    client_protocol = params.get("protocolVersion", "2024-11-05")
    
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {},
        },
        "serverInfo": {
            "name": SERVER_INFO["name"],
            "version": SERVER_INFO["version"],
        },
    }

def list_tools() -> Dict[str, Any]:
    """List available tools with enhanced schema validation"""
    tools: List[Dict[str, Any]] = [
        {
            "name": "add",
            "description": "Add a new memory to the memory store",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Memory content (10-10000 characters)",
                        "minLength": 10,
                        "maxLength": 10000
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Project identifier (optional)",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100
                    },
                    "category": {
                        "type": "string",
                        "description": "Memory category",
                        "default": "task",
                        "enum": ["task", "bug", "idea", "decision", "incident", "code_snippet", "git-history"]
                    },
                    "source": {
                        "type": "string",
                        "description": "Memory source",
                        "default": "mcp",
                        "maxLength": 50
                    },
                    "tags": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 50
                        },
                        "description": "Memory tags",
                        "maxItems": 20
                    },
                },
                "required": ["content"],
                "additionalProperties": False
            },
        },
        {
            "name": "search",
            "description": "Search memories using hybrid search (vector + metadata)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (min 3 characters)",
                        "minLength": 3,
                        "maxLength": 500
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Project filter",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100
                    },
                    "category": {
                        "type": "string",
                        "description": "Category filter",
                        "enum": ["task", "bug", "idea", "decision", "incident", "code_snippet", "git-history"]
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (1-20)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20
                    },
                    "recency_weight": {
                        "type": "number",
                        "description": "Recency weight (0.0-1.0)",
                        "default": 0.0,
                        "minimum": 0.0,
                        "maximum": 1.0
                    },
                },
                "required": ["query"],
                "additionalProperties": False
            },
        },
        {
            "name": "context",
            "description": "Get context around a specific memory",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "Memory ID to get context for",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Search depth (1-5)",
                        "default": 2,
                        "minimum": 1,
                        "maximum": 5
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Project filter",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100
                    },
                },
                "required": ["memory_id"],
                "additionalProperties": False
            },
        },
        {
            "name": "update",
            "description": "Update an existing memory",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "Memory ID to update",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100
                    },
                    "content": {
                        "type": "string",
                        "description": "New content",
                        "minLength": 10,
                        "maxLength": 10000
                    },
                    "category": {
                        "type": "string",
                        "description": "New category",
                        "enum": ["task", "bug", "idea", "decision", "incident", "code_snippet", "git-history"]
                    },
                    "tags": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 50
                        },
                        "description": "New tags",
                        "maxItems": 20
                    },
                },
                "required": ["memory_id"],
                "additionalProperties": False
            },
        },
        {
            "name": "delete",
            "description": "Delete a memory from the store",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "Memory ID to delete",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100
                    },
                },
                "required": ["memory_id"],
                "additionalProperties": False
            },
        },
        {
            "name": "stats",
            "description": "Get statistics about stored memories",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project filter",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date filter (YYYY-MM-DD)",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date filter (YYYY-MM-DD)",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$"
                    },
                },
                "additionalProperties": False
            },
        },
    ]
    return {"tools": tools}

async def call_tool(params: Dict[str, Any]) -> Dict[str, Any]:
    """Handle tool call with enhanced validation and error handling"""
    name = params.get("name")
    args = params.get("arguments", {}) or {}

    # Validate required parameters
    if not name:
        log.error("Missing tool name in call_tool request")
        return {
            "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing tool name"})}],
            "isError": True,
        }

    log.info(f"tools/call: {name} with args: {args}")

    if storage is None:
        log.error("Storage not initialized when calling tool")
        return {
            "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Storage not initialized"})}],
            "isError": True,
        }

    try:
        if name == "add":
            # Validate required arguments for add
            if "content" not in args:
                return {
                    "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing required argument: content"})}],
                    "isError": True,
                }

            params_obj = AddParams(
                content=args["content"],
                project_id=args.get("project_id"),
                category=args.get("category", "task"),
                source=args.get("source", "mcp"),
                tags=args.get("tags")
            )
            result = await storage.add_memory(params_obj)
            return {
                "content": [{"type": "text", "text": json.dumps(result.model_dump())}],
            }

        elif name == "search":
            # Validate required arguments for search
            if "query" not in args:
                return {
                    "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing required argument: query"})}],
                    "isError": True,
                }

            params_obj = SearchParams(
                query=args["query"],
                project_id=args.get("project_id"),
                category=args.get("category"),
                limit=args.get("limit", 5),
                recency_weight=args.get("recency_weight", 0.0)
            )
            result = await storage.search_memories(params_obj)
            return {
                "content": [{"type": "text", "text": json.dumps(result.model_dump())}],
            }

        elif name == "context":
            # Validate required arguments for context
            if "memory_id" not in args:
                return {
                    "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing required argument: memory_id"})}],
                    "isError": True,
                }

            result = await storage.get_context(
                args["memory_id"],
                args.get("depth", 2),
                args.get("project_id")
            )
            return {
                "content": [{"type": "text", "text": json.dumps(result.model_dump())}],
            }

        elif name == "update":
            # Validate required arguments for update
            if "memory_id" not in args:
                return {
                    "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing required argument: memory_id"})}],
                    "isError": True,
                }

            params_obj = UpdateParams(
                content=args.get("content"),
                category=args.get("category"),
                tags=args.get("tags")
            )
            result = await storage.update_memory(args["memory_id"], params_obj)
            return {
                "content": [{"type": "text", "text": json.dumps(result.model_dump())}],
            }

        elif name == "delete":
            # Validate required arguments for delete
            if "memory_id" not in args:
                return {
                    "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Missing required argument: memory_id"})}],
                    "isError": True,
                }

            result = await storage.delete_memory(args["memory_id"])
            return {
                "content": [{"type": "text", "text": json.dumps(result.model_dump())}],
            }

        elif name == "stats":
            params_obj = StatsParams(
                project_id=args.get("project_id"),
                start_date=args.get("start_date"),
                end_date=args.get("end_date")
            )
            result = await storage.get_stats(params_obj)
            return {
                "content": [{"type": "text", "text": json.dumps(result.model_dump())}],
            }

        else:
            log.warning(f"Unknown tool called: {name}")
            return {
                "content": [{"type": "text", "text": json.dumps({"success": False, "error": f"Unknown tool: {name}"})}],
                "isError": True,
            }

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
    global storage
    settings = Settings()
    
    log.info(f"Initializing storage with mode: {settings.storage_mode}")
    
    if settings.storage_mode == "direct":
        storage = DirectStorageBackend(settings.database_path)
        await storage.initialize()
        log.info("Direct storage initialized successfully")
    elif settings.storage_mode == "api":
        storage = APIStorageBackend(settings.api_base_url)
        await storage.initialize()
        log.info("API storage initialized successfully")
    else:
        raise ValueError(f"Unsupported storage mode: {settings.storage_mode}. Use 'direct' or 'api'.")

# -------------------------
# Main loop with graceful shutdown (no timeout on stdin)
# -------------------------
async def main():
    log.info("Starting mem-mesh Pure MCP Server (stdio, NDJSON)")

    # Initialize storage
    await initialize_storage()

    # Register signal handlers for graceful shutdown
    import signal

    # Use a flag to control the main loop
    shutdown_requested = asyncio.Event()

    def request_shutdown():
        log.info("Received interrupt signal, initiating graceful shutdown...")
        shutdown_requested.set()

    # Handle SIGTERM and SIGINT for graceful shutdown
    loop = asyncio.get_running_loop()
    if hasattr(signal, 'SIGTERM'):
        loop.add_signal_handler(signal.SIGTERM, request_shutdown)
    if hasattr(signal, 'SIGINT'):
        loop.add_signal_handler(signal.SIGINT, request_shutdown)

    log.info("Server ready, waiting for messages...")

    while not shutdown_requested.is_set():
        try:
            # Read line asynchronously without timeout
            # MCP clients may not send messages for long periods, that's normal
            line = await read_line_async()

            if line is None:
                log.info("EOF received; exiting")
                break

            # Parse the message
            req = parse_message(line)
            if req is None:
                log.debug("Invalid message received, skipping")
                continue

            method = req.get("method")
            req_id = req.get("id")

            # Log the incoming request for debugging
            log.debug(f"Incoming request - ID: {req_id}, Method: {method}")
            if method == "tools/call":
                tool_params = req.get("params", {})
                tool_name = tool_params.get("name") if isinstance(tool_params, dict) else "unknown"
                log.debug(f"Tool call - Name: {tool_name}")

            # Notifications: no response
            if req_id is None:
                log.debug(f"Notification received: {method}")
                continue

            try:
                if method == "initialize":
                    params = req.get("params", {}) or {}
                    result = resp_initialize(params)
                    write_result(req_id, result)
                    log.info("Initialize request handled successfully")
                elif method == "tools/list":
                    result = list_tools()
                    write_result(req_id, result)
                    log.debug("Tools list request handled successfully")
                elif method == "tools/call":
                    params = req.get("params", {}) or {}
                    # Add timeout to tool calls to prevent hanging
                    result = await asyncio.wait_for(call_tool(params), timeout=60.0)
                    write_result(req_id, result)
                    log.debug(f"Tool call '{params.get('name', 'unknown')}' handled successfully")
                elif method == "ping":
                    write_result(req_id, {})
                    log.debug("Ping request handled successfully")
                elif method == "health":
                    # Health check endpoint
                    import time
                    health_status = {
                        "status": "healthy",
                        "timestamp": time.time(),
                        "storage_initialized": storage is not None
                    }
                    write_result(req_id, health_status)
                    log.debug("Health check request handled successfully")
                elif method == "shutdown":
                    write_result(req_id, {})
                    log.info("Shutdown request received, exiting...")
                    break
                else:
                    write_error(req_id, -32601, f"Method not found: {method}")
                    log.warning(f"Unknown method requested: {method}")
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
            log.exception(f"Unexpected error in main loop: {e}")
            # Continue the loop to try reading again
            continue

    # Perform cleanup operations
    log.info("Performing cleanup before shutdown...")
    if storage:
        # If storage has a cleanup method, call it
        if hasattr(storage, 'cleanup') and callable(getattr(storage, 'cleanup')):
            try:
                if asyncio.iscoroutinefunction(getattr(storage, 'cleanup')):
                    await storage.cleanup()
                else:
                    storage.cleanup()
            except Exception as e:
                log.error(f"Error during storage cleanup: {e}")

    log.info("Server shutdown completed")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass