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
