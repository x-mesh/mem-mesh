"""
MCP Tool Schemas - JSON Schema 정의.

Pure MCP 구현에서 tools/list 응답에 사용됩니다.
FastMCP는 자동으로 스키마를 생성하지만, 일관성을 위해 여기서 정의합니다.
"""

from typing import List, Dict, Any

# 유효한 카테고리 목록
VALID_CATEGORIES = ["task", "bug", "idea", "decision", "incident", "code_snippet", "git-history"]

# 유효한 검색 모드 목록
VALID_SEARCH_MODES = ["hybrid", "exact", "semantic", "fuzzy"]

# 서버 정보는 중앙 모듈에서 import
from ..core.version import SERVER_INFO, __VERSION__, MCP_PROTOCOL_VERSION


def get_tool_schemas() -> List[Dict[str, Any]]:
    """MCP tools/list 응답용 스키마 반환"""
    return [
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
                        "enum": VALID_CATEGORIES
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
                        "enum": VALID_CATEGORIES
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
                    "response_format": {
                        "type": "string",
                        "description": "Response format: minimal (IDs only), compact (summaries), standard (full), full (complete)",
                        "default": "standard",
                        "enum": ["minimal", "compact", "standard", "full"]
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
                    "response_format": {
                        "type": "string",
                        "description": "Response format: compact (summaries), standard (full)",
                        "default": "standard",
                        "enum": ["compact", "standard", "full"]
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
                        "enum": VALID_CATEGORIES
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


def get_pin_tool_schemas() -> List[Dict[str, Any]]:
    """Pin/Session 관련 MCP tools/list 응답용 스키마 반환"""
    return [
        {
            "name": "pin_add",
            "description": "Add a new pin (short-term task) to the current session. Pins are lightweight work items that can be promoted to permanent memories.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Pin content describing the task or work item",
                        "minLength": 1,
                        "maxLength": 1000
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Project identifier",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100
                    },
                    "importance": {
                        "type": "integer",
                        "description": "Importance score (1-5). Auto-determined if not provided.",
                        "minimum": 1,
                        "maximum": 5
                    },
                    "tags": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 50
                        },
                        "description": "Pin tags",
                        "maxItems": 10
                    },
                },
                "required": ["content", "project_id"],
                "additionalProperties": False
            },
        },
        {
            "name": "pin_complete",
            "description": "Mark a pin as completed. Returns promotion suggestion if importance >= 4.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pin_id": {
                        "type": "string",
                        "description": "Pin ID to complete",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100
                    },
                },
                "required": ["pin_id"],
                "additionalProperties": False
            },
        },
        {
            "name": "pin_promote",
            "description": "Promote a completed pin to a permanent memory. Use this for important work items that should be preserved long-term.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pin_id": {
                        "type": "string",
                        "description": "Pin ID to promote to memory",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100
                    },
                },
                "required": ["pin_id"],
                "additionalProperties": False
            },
        },
        {
            "name": "session_resume",
            "description": "Resume the last session for a project. Returns active pins and session context.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project identifier",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100
                    },
                    "expand": {
                        "type": "boolean",
                        "description": "If true, return full pin contents; if false, return summary only",
                        "default": False
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of pins to return",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50
                    },
                },
                "required": ["project_id"],
                "additionalProperties": False
            },
        },
        {
            "name": "session_end",
            "description": "End the current session for a project. Optionally provide a summary.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project identifier",
                        "pattern": "^[a-zA-Z0-9_-]+$",
                        "maxLength": 100
                    },
                    "summary": {
                        "type": "string",
                        "description": "Session summary (auto-generated if not provided)",
                        "maxLength": 500
                    },
                },
                "required": ["project_id"],
                "additionalProperties": False
            },
        },
    ]


def get_all_tool_schemas() -> List[Dict[str, Any]]:
    """모든 MCP tool 스키마 반환 (memory + pin/session + batch)"""
    return get_tool_schemas() + get_pin_tool_schemas() + get_batch_tool_schemas()


def get_batch_tool_schemas() -> List[Dict[str, Any]]:
    """Batch operations MCP tools/list 응답용 스키마 반환"""
    return [
        {
            "name": "batch_operations",
            "description": "Execute multiple mixed operations in batch for maximum efficiency. Reduces token usage by 30-50% through batch processing.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "operations": {
                        "type": "array",
                        "description": "List of operation dictionaries with 'type' and parameters",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "description": "Operation type",
                                    "enum": ["add", "search"]
                                },
                                "content": {
                                    "type": "string",
                                    "description": "Memory content (for 'add' operations)",
                                    "minLength": 10,
                                    "maxLength": 10000
                                },
                                "query": {
                                    "type": "string",
                                    "description": "Search query (for 'search' operations)",
                                    "minLength": 3,
                                    "maxLength": 500
                                },
                                "project_id": {
                                    "type": "string",
                                    "description": "Project identifier",
                                    "pattern": "^[a-zA-Z0-9_-]+$",
                                    "maxLength": 100
                                },
                                "category": {
                                    "type": "string",
                                    "description": "Category",
                                    "enum": VALID_CATEGORIES
                                },
                                "tags": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 50
                                    },
                                    "description": "Tags",
                                    "maxItems": 20
                                },
                                "limit": {
                                    "type": "integer",
                                    "description": "Maximum results (for 'search' operations)",
                                    "default": 5,
                                    "minimum": 1,
                                    "maximum": 20
                                },
                            },
                            "required": ["type"],
                            "additionalProperties": False
                        },
                        "minItems": 1,
                        "maxItems": 50
                    },
                },
                "required": ["operations"],
                "additionalProperties": False
            },
        },
    ]
