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
from typing import Optional, Dict, Any, List

# 프로젝트 루트를 Python path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.core.config import Settings
from app.core.storage.direct import DirectStorageBackend
from app.core.storage.api import APIStorageBackend
from app.core.storage.base import StorageBackend
from app.core.schemas.requests import AddParams, SearchParams, UpdateParams, StatsParams

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
storage: Optional[StorageBackend] = None

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

def read_message() -> Optional[Dict[str, Any]]:
    """Read message from stdin as NDJSON"""
    try:
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line.strip())
    except (json.JSONDecodeError, EOFError):
        return None

# -------------------------
# MCP Protocol Handlers
# -------------------------
def resp_initialize(params: Dict[str, Any]) -> Dict[str, Any]:
    """Handle initialize request"""
    # protocolVersion은 클라이언트 호환성 확인용 (현재는 사용하지 않음)
    _ = params.get("protocolVersion", "2024-11-05")
    
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
    """List available tools"""
    tools: List[Dict[str, Any]] = [
        {
            "name": "add",
            "description": "Add a new memory to the memory store",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Memory content (10-10000 characters)"},
                    "project_id": {"type": "string", "description": "Project identifier (optional)"},
                    "category": {
                        "type": "string", 
                        "description": "Memory category", 
                        "default": "task",
                        "enum": ["task", "bug", "idea", "decision", "incident", "code_snippet", "git-history"]
                    },
                    "source": {"type": "string", "description": "Memory source", "default": "mcp"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Memory tags"},
                },
                "required": ["content"],
            },
        },
        {
            "name": "search",
            "description": "Search memories using hybrid search (vector + metadata)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (min 3 characters)"},
                    "project_id": {"type": "string", "description": "Project filter"},
                    "category": {
                        "type": "string", 
                        "description": "Category filter",
                        "enum": ["task", "bug", "idea", "decision", "incident", "code_snippet", "git-history"]
                    },
                    "limit": {"type": "integer", "description": "Maximum results (1-20)", "default": 5},
                    "recency_weight": {"type": "number", "description": "Recency weight (0.0-1.0)", "default": 0.0},
                },
                "required": ["query"],
            },
        },
        {
            "name": "context",
            "description": "Get context around a specific memory",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "Memory ID to get context for"},
                    "depth": {"type": "integer", "description": "Search depth (1-5)", "default": 2},
                    "project_id": {"type": "string", "description": "Project filter"},
                },
                "required": ["memory_id"],
            },
        },
        {
            "name": "update",
            "description": "Update an existing memory",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "Memory ID to update"},
                    "content": {"type": "string", "description": "New content"},
                    "category": {
                        "type": "string", 
                        "description": "New category",
                        "enum": ["task", "bug", "idea", "decision", "incident", "code_snippet", "git-history"]
                    },
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "New tags"},
                },
                "required": ["memory_id"],
            },
        },
        {
            "name": "delete",
            "description": "Delete a memory from the store",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "Memory ID to delete"},
                },
                "required": ["memory_id"],
            },
        },
        {
            "name": "stats",
            "description": "Get statistics about stored memories",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project filter"},
                    "start_date": {"type": "string", "description": "Start date filter (YYYY-MM-DD)"},
                    "end_date": {"type": "string", "description": "End date filter (YYYY-MM-DD)"},
                },
            },
        },
    ]
    return {"tools": tools}

async def call_tool(params: Dict[str, Any]) -> Dict[str, Any]:
    """Handle tool call"""
    name = params.get("name")
    args = params.get("arguments", {}) or {}
    log.info(f"tools/call: {name} with args: {args}")

    if storage is None:
        return {
            "content": [{"type": "text", "text": json.dumps({"success": False, "error": "Storage not initialized"})}],
            "isError": True,
        }

    try:
        if name == "add":
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
            result = await storage.get_context(
                args["memory_id"],
                args.get("depth", 2),
                args.get("project_id")
            )
            return {
                "content": [{"type": "text", "text": json.dumps(result.model_dump())}],
            }
        
        elif name == "update":
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
            return {
                "content": [{"type": "text", "text": json.dumps({"success": False, "error": f"Unknown tool: {name}"})}],
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
# Main loop
# -------------------------
async def main():
    log.info("Starting mem-mesh Pure MCP Server (stdio, NDJSON)")
    
    # Initialize storage
    await initialize_storage()
    
    while True:
        req = read_message()
        if req is None:
            log.info("EOF / invalid; exiting")
            break

        method = req.get("method")
        req_id = req.get("id")

        # Notifications: no response
        if req_id is None:
            continue

        try:
            if method == "initialize":
                params = req.get("params", {}) or {}
                result = resp_initialize(params)
                write_result(req_id, result)
            elif method == "tools/list":
                write_result(req_id, list_tools())
            elif method == "tools/call":
                params = req.get("params", {}) or {}
                result = await call_tool(params)
                write_result(req_id, result)
            elif method == "ping":
                write_result(req_id, {})
            elif method == "shutdown":
                write_result(req_id, {})
                break
            else:
                write_error(req_id, -32601, f"Method not found: {method}")
        except Exception as e:
            log.exception("Error handling request")
            write_error(req_id, -32603, f"Internal error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass