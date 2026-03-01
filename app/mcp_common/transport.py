"""JSON-RPC and MCP transport formatting utilities."""

import json
from typing import Any, Dict

from ..core.config import get_settings
from .token_estimator import add_token_metadata


def format_tool_response(
    result: Dict[str, Any], include_meta: bool = None
) -> Dict[str, Any]:
    """Format successful tool result as MCP content structure.

    Args:
        result: Tool result dictionary
        include_meta: Whether to include token estimation metadata.
                     If None, uses settings.enable_token_metadata

    Returns:
        MCP-formatted response with content array
    """
    if include_meta is None:
        include_meta = get_settings().enable_token_metadata

    if include_meta:
        result = add_token_metadata(result)

    return {
        "content": [{"type": "text", "text": json.dumps(result)}],
        "isError": False,
    }


def format_tool_error(error_message: str) -> Dict[str, Any]:
    """Format tool error as MCP content structure."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"success": False, "error": error_message}),
            }
        ],
        "isError": True,
    }


def format_jsonrpc_response(result: Any, request_id: Any) -> Dict[str, Any]:
    """Format successful JSON-RPC 2.0 response."""
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def format_jsonrpc_error(
    message: str, request_id: Any, code: int = -32603
) -> Dict[str, Any]:
    """Format JSON-RPC 2.0 error response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
