"""
MCP 서버 기본 구조
stdio transport를 사용한 MCP 서버 구현
"""

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional

from ..database.base import Database
from ..embeddings.service import EmbeddingService
from ..services.memory import MemoryService
from ..services.search import SearchService
from ..services.context import ContextService
from ..services.stats import StatsService
from ..config import Settings
from .tools import MCPTools

logger = logging.getLogger(__name__)


class MCPServer:
    """MCP 서버 메인 클래스"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db: Optional[Database] = None
        self.embedding_service: Optional[EmbeddingService] = None
        self.memory_service: Optional[MemoryService] = None
        self.search_service: Optional[SearchService] = None
        self.context_service: Optional[ContextService] = None
        self.stats_service: Optional[StatsService] = None
        self.tools: Optional[MCPTools] = None
        self.initialized = False
        
    async def initialize(self) -> None:
        """서버 초기화"""
        if self.initialized:
            return
            
        logger.info("Initializing MCP server...")
        
        try:
            # 데이터베이스 연결
            self.db = Database(self.settings.database_path)
            await self.db.connect()
            
            # 임베딩 서비스 초기화
            self.embedding_service = EmbeddingService()
            
            # 비즈니스 서비스들 초기화
            self.memory_service = MemoryService(self.db, self.embedding_service)
            self.search_service = SearchService(self.db, self.embedding_service)
            self.context_service = ContextService(self.db, self.embedding_service)
            self.stats_service = StatsService(self.db)
            
            # MCP 도구들 초기화
            self.tools = MCPTools(
                memory_service=self.memory_service,
                search_service=self.search_service,
                context_service=self.context_service,
                stats_service=self.stats_service
            )
            
            self.initialized = True
            logger.info("MCP server initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize MCP server: {e}")
            raise
    
    async def shutdown(self) -> None:
        """서버 종료"""
        logger.info("Shutting down MCP server...")
        
        if self.db:
            await self.db.close()
        
        logger.info("MCP server shutdown complete")
    
    def send_response(self, response: Dict[str, Any]) -> None:
        """JSON-RPC 응답 전송"""
        try:
            response_json = json.dumps(response, ensure_ascii=False)
            print(response_json, flush=True)
            logger.debug(f"Sent response: {response_json}")
        except Exception as e:
            logger.error(f"Failed to send response: {e}")
    
    def send_error(self, request_id: Any, code: int, message: str) -> None:
        """JSON-RPC 에러 응답 전송"""
        error_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message
            }
        }
        self.send_response(error_response)
    
    async def handle_initialize(self, request_id: Any, params: Dict[str, Any]) -> None:
        """initialize 요청 처리"""
        try:
            await self.initialize()
            
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "mem-mesh",
                        "version": "1.0.0"
                    }
                }
            }
            self.send_response(response)
            
        except Exception as e:
            logger.error(f"Initialize error: {e}")
            self.send_error(request_id, -32603, f"Internal error: {str(e)}")
    
    async def handle_tools_list(self, request_id: Any, params: Dict[str, Any]) -> None:
        """tools/list 요청 처리"""
        try:
            if not self.initialized:
                await self.initialize()
            
            tools = self.tools.get_available_tools()
            
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": tools
                }
            }
            self.send_response(response)
            
        except Exception as e:
            logger.error(f"Tools list error: {e}")
            self.send_error(request_id, -32603, f"Internal error: {str(e)}")
    
    async def handle_tools_call(self, request_id: Any, params: Dict[str, Any]) -> None:
        """tools/call 요청 처리"""
        try:
            if not self.initialized:
                await self.initialize()
            
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            if not tool_name:
                self.send_error(request_id, -32602, "Missing tool name")
                return
            
            # 도구 호출
            result = await self.tools.handle_tool_call(tool_name, arguments)
            
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
            self.send_response(response)
            
        except Exception as e:
            logger.error(f"Tools call error: {e}")
            self.send_error(request_id, -32603, f"Internal error: {str(e)}")
    
    async def handle_request(self, request: Dict[str, Any]) -> None:
        """JSON-RPC 요청 처리"""
        try:
            method = request.get("method")
            request_id = request.get("id")
            params = request.get("params", {})
            
            logger.debug(f"Handling request: {method}")
            
            if method == "initialize":
                await self.handle_initialize(request_id, params)
            elif method == "tools/list":
                await self.handle_tools_list(request_id, params)
            elif method == "tools/call":
                await self.handle_tools_call(request_id, params)
            else:
                self.send_error(request_id, -32601, f"Method not found: {method}")
                
        except Exception as e:
            logger.error(f"Request handling error: {e}")
            request_id = request.get("id") if isinstance(request, dict) else None
            self.send_error(request_id, -32603, f"Internal error: {str(e)}")
    
    async def run(self) -> None:
        """서버 실행 (stdio transport)"""
        try:
            logger.info("MCP server starting on stdio transport...")
            
            # stdin에서 JSON-RPC 메시지 읽기
            loop = asyncio.get_event_loop()
            
            while True:
                try:
                    # stdin에서 한 줄 읽기
                    line = await loop.run_in_executor(None, sys.stdin.readline)
                    
                    if not line:
                        # EOF 도달
                        break
                    
                    line = line.strip()
                    if not line:
                        continue
                    
                    # JSON 파싱
                    try:
                        request = json.loads(line)
                        await self.handle_request(request)
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON: {e}")
                        # 잘못된 JSON에 대한 에러 응답
                        self.send_error(None, -32700, "Parse error")
                        
                except Exception as e:
                    logger.error(f"Error reading from stdin: {e}")
                    break
                    
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        except Exception as e:
            logger.error(f"MCP server error: {e}")
            raise
        finally:
            await self.shutdown()


async def main():
    """MCP 서버 진입점"""
    settings = Settings()
    server = MCPServer(settings)
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())