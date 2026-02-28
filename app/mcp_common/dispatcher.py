"""Unified MCP tool dispatcher - eliminates duplicated dispatch logic."""

import json
from typing import Dict, Any, Optional
from pydantic import ValidationError

from .tools import MCPToolHandlers
from .transport import format_tool_response, format_tool_error
from ..core.utils.logger import get_logger

logger = get_logger("mcp-dispatcher")


class MCPDispatcher:
    """Unified dispatcher for all MCP tools.

    Centralizes tool dispatch logic previously duplicated in:
    - app/mcp_stdio_pure/server.py
    - app/web/mcp/sse.py
    """

    def __init__(self, tool_handlers: MCPToolHandlers, batch_handler=None):
        self._tool_handlers = tool_handlers
        self._batch_handler = batch_handler

    @property
    def tool_handlers(self) -> MCPToolHandlers:
        return self._tool_handlers

    async def dispatch(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Dispatch tool call to appropriate handler.

        Returns MCP-formatted response with content array and isError flag.
        """
        args = arguments or {}

        try:
            if tool_name == "add":
                return await self._dispatch_add(args)
            elif tool_name == "search":
                return await self._dispatch_search(args)
            elif tool_name == "context":
                return await self._dispatch_context(args)
            elif tool_name == "update":
                return await self._dispatch_update(args)
            elif tool_name == "delete":
                return await self._dispatch_delete(args)
            elif tool_name == "stats":
                return await self._dispatch_stats(args)
            elif tool_name == "pin_add":
                return await self._dispatch_pin_add(args)
            elif tool_name == "pin_complete":
                return await self._dispatch_pin_complete(args)
            elif tool_name == "pin_promote":
                return await self._dispatch_pin_promote(args)
            elif tool_name == "session_resume":
                return await self._dispatch_session_resume(args)
            elif tool_name == "session_end":
                return await self._dispatch_session_end(args)
            elif tool_name == "link":
                return await self._dispatch_link(args)
            elif tool_name == "unlink":
                return await self._dispatch_unlink(args)
            elif tool_name == "get_links":
                return await self._dispatch_get_links(args)
            elif tool_name == "batch_operations":
                return await self._dispatch_batch_operations(args)
            elif tool_name == "weekly_review":
                return await self._dispatch_weekly_review(args)
            else:
                logger.warning(f"Unknown tool: {tool_name}")
                return format_tool_error(f"Unknown tool: {tool_name}")

        except ValidationError as ve:
            logger.error(f"Validation error in tool {tool_name}: {ve}")
            return format_tool_error(f"Validation error: {str(ve)}")
        except Exception as e:
            logger.error(f"Error in tool {tool_name}", error=str(e))
            return format_tool_error(str(e))

    async def _dispatch_add(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "content" not in args:
            return format_tool_error("Missing required argument: content")

        result = await self._tool_handlers.add(
            content=args["content"],
            project_id=args.get("project_id"),
            category=args.get("category", "task"),
            source=args.get("source", "mcp"),
            tags=args.get("tags"),
        )
        return format_tool_response(result)

    async def _dispatch_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "query" not in args:
            return format_tool_error("Missing required argument: query")

        result = await self._tool_handlers.search(
            query=args["query"],
            project_id=args.get("project_id"),
            category=args.get("category"),
            limit=args.get("limit", 5),
            recency_weight=args.get("recency_weight", 0.0),
            response_format=args.get("response_format", "standard"),
            time_range=args.get("time_range"),
            date_from=args.get("date_from"),
            date_to=args.get("date_to"),
            temporal_mode=args.get("temporal_mode", "boost"),
        )
        return format_tool_response(result)

    async def _dispatch_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "memory_id" not in args:
            return format_tool_error("Missing required argument: memory_id")

        result = await self._tool_handlers.context(
            memory_id=args["memory_id"],
            depth=args.get("depth", 2),
            project_id=args.get("project_id"),
            response_format=args.get("response_format", "standard"),
        )
        return format_tool_response(result)

    async def _dispatch_update(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "memory_id" not in args:
            return format_tool_error("Missing required argument: memory_id")

        result = await self._tool_handlers.update(
            memory_id=args["memory_id"],
            content=args.get("content"),
            category=args.get("category"),
            tags=args.get("tags"),
        )
        return format_tool_response(result)

    async def _dispatch_delete(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "memory_id" not in args:
            return format_tool_error("Missing required argument: memory_id")

        result = await self._tool_handlers.delete(memory_id=args["memory_id"])
        return format_tool_response(result)

    async def _dispatch_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        result = await self._tool_handlers.stats(
            project_id=args.get("project_id"),
            start_date=args.get("start_date"),
            end_date=args.get("end_date"),
        )
        return format_tool_response(result)

    async def _dispatch_pin_add(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "content" not in args or "project_id" not in args:
            return format_tool_error("Missing required arguments: content, project_id")

        result = await self._tool_handlers.pin_add(
            content=args["content"],
            project_id=args["project_id"],
            importance=args.get("importance"),
            tags=args.get("tags"),
        )
        return format_tool_response(result)

    async def _dispatch_pin_complete(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "pin_id" not in args:
            return format_tool_error("Missing required argument: pin_id")

        result = await self._tool_handlers.pin_complete(pin_id=args["pin_id"])
        return format_tool_response(result)

    async def _dispatch_pin_promote(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "pin_id" not in args:
            return format_tool_error("Missing required argument: pin_id")

        result = await self._tool_handlers.pin_promote(
            pin_id=args["pin_id"],
            category=args.get("category", "task"),
        )
        return format_tool_response(result)

    async def _dispatch_session_resume(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "project_id" not in args:
            return format_tool_error("Missing required argument: project_id")

        result = await self._tool_handlers.session_resume(
            project_id=args["project_id"],
            expand=args.get("expand", False),
            limit=args.get("limit", 10),
        )
        return format_tool_response(result)

    async def _dispatch_session_end(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "project_id" not in args:
            return format_tool_error("Missing required argument: project_id")

        result = await self._tool_handlers.session_end(
            project_id=args["project_id"],
            summary=args.get("summary"),
        )
        return format_tool_response(result)

    # ===== Memory Relations Dispatchers =====

    async def _dispatch_link(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "source_id" not in args or "target_id" not in args:
            return format_tool_error("Missing required arguments: source_id, target_id")

        result = await self._tool_handlers.link(
            source_id=args["source_id"],
            target_id=args["target_id"],
            relation_type=args.get("relation_type", "related"),
            strength=args.get("strength", 1.0),
            metadata=args.get("metadata"),
        )
        return format_tool_response(result)

    async def _dispatch_unlink(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "source_id" not in args or "target_id" not in args:
            return format_tool_error("Missing required arguments: source_id, target_id")

        result = await self._tool_handlers.unlink(
            source_id=args["source_id"],
            target_id=args["target_id"],
            relation_type=args.get("relation_type"),
        )
        return format_tool_response(result)

    async def _dispatch_get_links(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "memory_id" not in args:
            return format_tool_error("Missing required argument: memory_id")

        result = await self._tool_handlers.get_links(
            memory_id=args["memory_id"],
            relation_type=args.get("relation_type"),
            direction=args.get("direction", "both"),
            limit=args.get("limit", 20),
        )
        return format_tool_response(result)

    async def _dispatch_weekly_review(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "project_id" not in args:
            return format_tool_error("Missing required argument: project_id")

        result = await self._tool_handlers.weekly_review(
            project_id=args["project_id"],
            days=args.get("days", 7),
        )
        return format_tool_response(result)

    async def _dispatch_batch_operations(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if "operations" not in args:
            return format_tool_error("Missing required argument: operations")

        operations = args["operations"]

        # BatchOperationHandler가 있으면 사용 (배치 임베딩/캐시 최적화)
        if self._batch_handler is not None:
            try:
                result = await self._batch_handler.batch_operations(operations=operations)
                return format_tool_response(result)
            except Exception as e:
                logger.error(f"Batch operations failed: {e}")
                return format_tool_error(f"Batch operations failed: {str(e)}")

        # Fallback: 개별 도구 순차 호출 (BatchOperationHandler 미초기화 시)
        try:
            results = []

            for i, op in enumerate(operations):
                op_type = op.get("type")

                if op_type == "add":
                    add_result = await self._dispatch_add({
                        "content": op.get("content"),
                        "project_id": op.get("project_id"),
                        "category": op.get("category", "task"),
                        "source": op.get("source", "mcp_batch"),
                        "tags": op.get("tags"),
                    })
                    if not add_result.get("isError"):
                        content_text = add_result["content"][0]["text"]
                        parsed = json.loads(content_text)
                        results.append({
                            "index": i, "type": "add", "success": True,
                            "memory_id": parsed.get("id"),
                        })
                    else:
                        results.append({
                            "index": i, "type": "add", "success": False,
                            "error": add_result["content"][0]["text"],
                        })

                elif op_type == "search":
                    search_result = await self._dispatch_search({
                        "query": op.get("query"),
                        "project_id": op.get("project_id"),
                        "category": op.get("category"),
                        "limit": op.get("limit", 5),
                    })
                    if not search_result.get("isError"):
                        content_text = search_result["content"][0]["text"]
                        parsed = json.loads(content_text)
                        results.append({
                            "index": i, "type": "search", "success": True,
                            "results": parsed.get("results", []),
                            "total": parsed.get("total"),
                        })
                    else:
                        results.append({
                            "index": i, "type": "search", "success": False,
                            "error": search_result["content"][0]["text"],
                        })
                elif op_type == "pin_add":
                    pin_result = await self._dispatch_pin_add({
                        "content": op.get("content"),
                        "project_id": op.get("project_id"),
                        "importance": op.get("importance"),
                        "tags": op.get("tags"),
                    })
                    if not pin_result.get("isError"):
                        content_text = pin_result["content"][0]["text"]
                        parsed = json.loads(content_text)
                        results.append({
                            "index": i, "type": "pin_add", "success": True,
                            "pin_id": parsed.get("id"),
                        })
                    else:
                        results.append({
                            "index": i, "type": "pin_add", "success": False,
                            "error": pin_result["content"][0]["text"],
                        })
                else:
                    results.append({
                        "index": i, "type": op_type, "success": False,
                        "error": f"Unknown operation type: {op_type}",
                    })

            add_count = sum(1 for op in operations if op.get("type") == "add")
            search_count = sum(1 for op in operations if op.get("type") == "search")
            pin_add_count = sum(1 for op in operations if op.get("type") == "pin_add")

            batch_result = {
                "status": "success",
                "total_operations": len(operations),
                "results": results,
                "batch_stats": {
                    "add_operations": add_count,
                    "search_operations": search_count,
                    "pin_add_operations": pin_add_count,
                },
                "tokens_saved": add_count * 10 + search_count * 30 + pin_add_count * 5,
            }
            return format_tool_response(batch_result)

        except Exception as e:
            logger.error(f"Batch operations failed: {e}")
            return format_tool_error(f"Batch operations failed: {str(e)}")
