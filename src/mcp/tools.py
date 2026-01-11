"""
MCP 도구 등록 및 핸들러
mem-mesh의 모든 MCP 도구들을 정의하고 처리
"""

import json
import logging
from typing import Any, Dict, List, Optional

from ..services.memory import MemoryService, MemoryNotFoundError
from ..services.search import SearchService
from ..services.context import ContextService, ContextNotFoundError
from ..services.stats import StatsService
from ..schemas.requests import AddParams, SearchParams, ContextParams, UpdateParams, DeleteParams, StatsParams
from ..schemas.responses import (
    AddResponse, SearchResponse, ContextResponse, 
    UpdateResponse, DeleteResponse, StatsResponse, ErrorResponse
)

logger = logging.getLogger(__name__)


class MCPTools:
    """MCP 도구 관리 클래스"""
    
    def __init__(
        self, 
        memory_service: MemoryService,
        search_service: SearchService,
        context_service: ContextService,
        stats_service: StatsService
    ):
        self.memory_service = memory_service
        self.search_service = search_service
        self.context_service = context_service
        self.stats_service = stats_service
        
        # 도구 스키마 정의
        self.tool_schemas = self._define_tool_schemas()
    
    def _define_tool_schemas(self) -> Dict[str, Dict[str, Any]]:
        """MCP 도구 스키마 정의"""
        return {
            "mem-mesh.add": {
                "name": "mem-mesh.add",
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
                            "pattern": "^[a-z0-9_-]+$"
                        },
                        "category": {
                            "type": "string",
                            "description": "Memory category",
                            "enum": ["task", "bug", "idea", "decision", "incident", "code_snippet"],
                            "default": "task"
                        },
                        "source": {
                            "type": "string",
                            "description": "Memory source (optional)",
                            "default": "mcp"
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Memory tags (optional)"
                        }
                    },
                    "required": ["content"]
                }
            },
            
            "mem-mesh.search": {
                "name": "mem-mesh.search",
                "description": "Search memories using hybrid search (vector + metadata)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                            "minLength": 3
                        },
                        "project_id": {
                            "type": "string",
                            "description": "Project filter (optional)",
                            "pattern": "^[a-z0-9_-]+$"
                        },
                        "category": {
                            "type": "string",
                            "description": "Category filter (optional)",
                            "enum": ["task", "bug", "idea", "decision", "incident", "code_snippet"]
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum results",
                            "minimum": 1,
                            "maximum": 20,
                            "default": 5
                        },
                        "recency_weight": {
                            "type": "number",
                            "description": "Recency weight (0.0-1.0)",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "default": 0.0
                        }
                    },
                    "required": ["query"]
                }
            },
            
            "mem-mesh.context": {
                "name": "mem-mesh.context",
                "description": "Get context around a specific memory",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {
                            "type": "string",
                            "description": "Memory ID to get context for"
                        },
                        "depth": {
                            "type": "integer",
                            "description": "Search depth (1-5)",
                            "minimum": 1,
                            "maximum": 5,
                            "default": 2
                        },
                        "project_id": {
                            "type": "string",
                            "description": "Project filter (optional)",
                            "pattern": "^[a-z0-9_-]+$"
                        }
                    },
                    "required": ["memory_id"]
                }
            },
            
            "mem-mesh.update": {
                "name": "mem-mesh.update",
                "description": "Update an existing memory",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {
                            "type": "string",
                            "description": "Memory ID to update"
                        },
                        "content": {
                            "type": "string",
                            "description": "New content (optional)",
                            "minLength": 10,
                            "maxLength": 10000
                        },
                        "category": {
                            "type": "string",
                            "description": "New category (optional)",
                            "enum": ["task", "bug", "idea", "decision", "incident", "code_snippet"]
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "New tags (optional)"
                        }
                    },
                    "required": ["memory_id"]
                }
            },
            
            "mem-mesh.delete": {
                "name": "mem-mesh.delete",
                "description": "Delete a memory from the store",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {
                            "type": "string",
                            "description": "Memory ID to delete"
                        }
                    },
                    "required": ["memory_id"]
                }
            },
            
            "mem-mesh.stats": {
                "name": "mem-mesh.stats",
                "description": "Get statistics about stored memories",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {
                            "type": "string",
                            "description": "Project filter (optional)",
                            "pattern": "^[a-z0-9_-]+$"
                        },
                        "start_date": {
                            "type": "string",
                            "description": "Start date filter (YYYY-MM-DD, optional)",
                            "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date filter (YYYY-MM-DD, optional)",
                            "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
                        },
                        "group_by": {
                            "type": "string",
                            "description": "Grouping method",
                            "enum": ["overall", "project", "category", "source"],
                            "default": "overall"
                        }
                    },
                    "required": []
                }
            }
        }
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
        """사용 가능한 도구 목록 반환"""
        return list(self.tool_schemas.values())
    
    async def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """도구 호출 처리"""
        logger.info(f"Handling tool call: {tool_name}")
        
        try:
            # 입력 검증
            if tool_name not in self.tool_schemas:
                return self._error_response(
                    "UNKNOWN_TOOL",
                    f"Unknown tool: {tool_name}"
                )
            
            # 도구별 핸들러 호출
            if tool_name == "mem-mesh.add":
                return await self.handle_add(arguments)
            elif tool_name == "mem-mesh.search":
                return await self.handle_search(arguments)
            elif tool_name == "mem-mesh.context":
                return await self.handle_context(arguments)
            elif tool_name == "mem-mesh.update":
                return await self.handle_update(arguments)
            elif tool_name == "mem-mesh.delete":
                return await self.handle_delete(arguments)
            elif tool_name == "mem-mesh.stats":
                return await self.handle_stats(arguments)
            else:
                return self._error_response(
                    "UNIMPLEMENTED_TOOL",
                    f"Tool not implemented: {tool_name}"
                )
                
        except Exception as e:
            logger.error(f"Tool call error: {e}")
            return self._error_response(
                "INTERNAL_ERROR",
                f"Internal server error: {str(e)}"
            )
    
    async def handle_add(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """mem-mesh.add 도구 핸들러"""
        try:
            # 파라미터 검증
            params = AddParams(**arguments)
            
            # 메모리 생성
            response = await self.memory_service.create(
                content=params.content,
                project_id=params.project_id,
                category=params.category,
                source=params.source or "mcp",
                tags=params.tags
            )
            
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(response.model_dump(), ensure_ascii=False, indent=2)
                    }
                ]
            }
            
        except Exception as e:
            logger.error(f"Add tool error: {e}")
            return self._error_response("ADD_FAILED", str(e))
    
    async def handle_search(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """mem-mesh.search 도구 핸들러"""
        try:
            # 파라미터 검증
            params = SearchParams(**arguments)
            
            # 검색 수행
            response = await self.search_service.search(
                query=params.query,
                project_id=params.project_id,
                category=params.category,
                limit=params.limit,
                recency_weight=params.recency_weight
            )
            
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(response.model_dump(), ensure_ascii=False, indent=2)
                    }
                ]
            }
            
        except Exception as e:
            logger.error(f"Search tool error: {e}")
            return self._error_response("SEARCH_FAILED", str(e))
    
    async def handle_context(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """mem-mesh.context 도구 핸들러"""
        try:
            # 파라미터 검증
            params = ContextParams(**arguments)
            
            # 맥락 조회
            response = await self.context_service.get_context(
                memory_id=params.memory_id,
                depth=params.depth,
                project_id=params.project_id
            )
            
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(response.model_dump(), ensure_ascii=False, indent=2)
                    }
                ]
            }
            
        except ContextNotFoundError as e:
            return self._error_response("MEMORY_NOT_FOUND", str(e))
        except Exception as e:
            logger.error(f"Context tool error: {e}")
            return self._error_response("CONTEXT_FAILED", str(e))
    
    async def handle_update(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """mem-mesh.update 도구 핸들러"""
        try:
            # memory_id를 별도로 추출
            memory_id = arguments.get("memory_id")
            if not memory_id:
                return self._error_response("MISSING_MEMORY_ID", "memory_id is required")
            
            # 나머지 파라미터로 UpdateParams 생성
            update_args = {k: v for k, v in arguments.items() if k != "memory_id"}
            params = UpdateParams(**update_args)
            
            # 메모리 업데이트
            response = await self.memory_service.update(
                memory_id=memory_id,
                content=params.content,
                category=params.category,
                tags=params.tags
            )
            
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(response.model_dump(), ensure_ascii=False, indent=2)
                    }
                ]
            }
            
        except MemoryNotFoundError as e:
            return self._error_response("MEMORY_NOT_FOUND", str(e))
        except Exception as e:
            logger.error(f"Update tool error: {e}")
            return self._error_response("UPDATE_FAILED", str(e))
    
    async def handle_delete(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """mem-mesh.delete 도구 핸들러"""
        try:
            # 파라미터 검증
            params = DeleteParams(**arguments)
            
            # 메모리 삭제
            response = await self.memory_service.delete(params.memory_id)
            
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(response.model_dump(), ensure_ascii=False, indent=2)
                    }
                ]
            }
            
        except MemoryNotFoundError as e:
            return self._error_response("MEMORY_NOT_FOUND", str(e))
        except Exception as e:
            logger.error(f"Delete tool error: {e}")
            return self._error_response("DELETE_FAILED", str(e))
    
    async def handle_stats(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """mem-mesh.stats 도구 핸들러"""
        try:
            # 파라미터 검증 (모든 필드가 선택사항)
            params = StatsParams(**arguments)
            
            # 통계 조회
            stats = await self.stats_service.get_overall_stats(
                project_id=params.project_id,
                start_date=params.start_date,
                end_date=params.end_date
            )
            
            response = StatsResponse(**stats)
            
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(response.model_dump(), ensure_ascii=False, indent=2)
                    }
                ]
            }
            
        except Exception as e:
            logger.error(f"Stats tool error: {e}")
            return self._error_response("STATS_FAILED", str(e))
    
    def _error_response(self, error_code: str, message: str) -> Dict[str, Any]:
        """에러 응답 생성"""
        error_response = ErrorResponse(
            error=error_code,
            message=message
        )
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(error_response.model_dump(), ensure_ascii=False, indent=2)
                }
            ],
            "isError": True
        }