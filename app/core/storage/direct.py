"""Direct SQLite 스토리지 백엔드 구현"""

import logging
from typing import Optional

from .base import StorageBackend
from ..database.base import Database
from ..embeddings.service import EmbeddingService
from ..services.memory import MemoryService
from ..services.search import SearchService
from ..services.context import ContextService
from ..services.stats import StatsService
from ..schemas.requests import AddParams, SearchParams, UpdateParams, StatsParams
from ..schemas.responses import (
    AddResponse, SearchResponse, ContextResponse, 
    UpdateResponse, DeleteResponse, StatsResponse
)
from ..config import get_settings

logger = logging.getLogger(__name__)


class DirectStorageBackend(StorageBackend):
    """SQLite 직접 접근 스토리지 백엔드
    
    이 구현체는 FastAPI 서버를 거치지 않고 직접 SQLite 데이터베이스에 접근하여
    메모리 저장/검색/업데이트/삭제 작업을 수행합니다.
    """
    
    def __init__(self, db_path: str, busy_timeout: int = 5000):
        """
        DirectStorageBackend 초기화
        
        Args:
            db_path: SQLite 데이터베이스 파일 경로
            busy_timeout: SQLite busy timeout (밀리초)
        """
        self.db_path = db_path
        self.busy_timeout = busy_timeout
        
        # 서비스 인스턴스들
        self.db: Optional[Database] = None
        self.embedding_service: Optional[EmbeddingService] = None
        self.memory_service: Optional[MemoryService] = None
        self.search_service: Optional[SearchService] = None
        self.context_service: Optional[ContextService] = None
        self.stats_service: Optional[StatsService] = None
        
        logger.info(f"DirectStorageBackend initialized with db_path: {db_path}")
    
    async def initialize(self) -> None:
        """스토리지 백엔드 초기화
        
        데이터베이스 연결을 설정하고 모든 서비스 인스턴스를 생성합니다.
        """
        try:
            # 데이터베이스 연결
            self.db = Database(self.db_path, busy_timeout=self.busy_timeout)
            await self.db.connect()
            
            # 임베딩 서비스 초기화 (MCP 서버에서는 preload 하지 않음)
            settings = get_settings()
            self.embedding_service = EmbeddingService(
                model_name=settings.embedding_model,
                preload=False  # MCP 서버에서는 lazy loading 사용
            )
            
            # 임베딩 모델 일관성 검증
            model_check = await self.db.check_embedding_model_consistency(
                current_model=self.embedding_service.model_name,
                current_dim=self.embedding_service.dimension
            )
            
            if model_check["needs_migration"]:
                logger.warning(model_check["message"])
                logger.warning("검색 결과가 부정확할 수 있습니다. 마이그레이션을 실행하세요:")
                logger.warning("  python scripts/migrate_embeddings.py")
            else:
                logger.info(model_check["message"])
            
            # 비즈니스 서비스들 초기화
            self.memory_service = MemoryService(self.db, self.embedding_service)
            self.search_service = SearchService(self.db, self.embedding_service)
            self.context_service = ContextService(self.db, self.embedding_service)
            self.stats_service = StatsService(self.db)
            
            logger.info("DirectStorageBackend initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize DirectStorageBackend: {e}")
            raise RuntimeError(f"Failed to initialize storage backend: {e}")
    
    async def shutdown(self) -> None:
        """스토리지 백엔드 종료
        
        데이터베이스 연결을 해제하고 리소스를 정리합니다.
        """
        try:
            if self.db:
                await self.db.close()
                self.db = None
            
            # 서비스 인스턴스들 정리
            self.embedding_service = None
            self.memory_service = None
            self.search_service = None
            self.context_service = None
            self.stats_service = None
            
            logger.info("DirectStorageBackend shutdown successfully")
            
        except Exception as e:
            logger.error(f"Error during DirectStorageBackend shutdown: {e}")
            raise RuntimeError(f"Failed to shutdown storage backend: {e}")
    
    async def add_memory(self, params: AddParams) -> AddResponse:
        """메모리 추가
        
        Args:
            params: 메모리 추가 요청 파라미터
            
        Returns:
            AddResponse: 추가된 메모리 정보
            
        Raises:
            ValueError: 잘못된 파라미터
            RuntimeError: 스토리지 오류
        """
        if not self.memory_service:
            raise RuntimeError("Storage backend not initialized")
        
        try:
            logger.debug(f"Adding memory with content length: {len(params.content)}")
            
            result = await self.memory_service.create(
                content=params.content,
                project_id=params.project_id,
                category=params.category,
                source=params.source or "mcp",
                tags=params.tags
            )
            
            logger.info(f"Memory added successfully: {result.id}")
            return result
            
        except ValueError as e:
            logger.warning(f"Invalid parameters for add_memory: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to add memory: {e}")
            raise RuntimeError(f"Failed to add memory: {e}")
    
    async def search_memories(self, params: SearchParams) -> SearchResponse:
        """메모리 검색
        
        Args:
            params: 메모리 검색 요청 파라미터
            
        Returns:
            SearchResponse: 검색 결과
            
        Raises:
            ValueError: 잘못된 파라미터
            RuntimeError: 스토리지 오류
        """
        if not self.search_service:
            raise RuntimeError("Storage backend not initialized")
        
        try:
            logger.debug(f"Searching memories with query: '{params.query}'")
            
            result = await self.search_service.search(
                query=params.query,
                project_id=params.project_id,
                category=params.category,
                limit=params.limit,
                recency_weight=params.recency_weight
            )
            
            logger.info(f"Search completed, found {len(result.results)} results")
            return result
            
        except ValueError as e:
            logger.warning(f"Invalid parameters for search_memories: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to search memories: {e}")
            raise RuntimeError(f"Failed to search memories: {e}")
    
    async def get_context(
        self, 
        memory_id: str, 
        depth: int, 
        project_id: Optional[str]
    ) -> ContextResponse:
        """컨텍스트 조회
        
        Args:
            memory_id: 조회할 메모리 ID
            depth: 검색 깊이 (1-5)
            project_id: 프로젝트 ID 필터 (선택사항)
            
        Returns:
            ContextResponse: 컨텍스트 정보
            
        Raises:
            ValueError: 잘못된 파라미터
            RuntimeError: 스토리지 오류
        """
        if not self.context_service:
            raise RuntimeError("Storage backend not initialized")
        
        try:
            logger.debug(f"Getting context for memory_id: {memory_id}, depth: {depth}")
            
            result = await self.context_service.get_context(
                memory_id=memory_id,
                depth=depth,
                project_id=project_id
            )
            
            logger.info(f"Context retrieved for memory {memory_id}, found {len(result.related_memories)} related memories")
            return result
            
        except ValueError as e:
            logger.warning(f"Invalid parameters for get_context: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get context: {e}")
            raise RuntimeError(f"Failed to get context: {e}")
    
    async def update_memory(self, memory_id: str, params: UpdateParams) -> UpdateResponse:
        """메모리 업데이트
        
        Args:
            memory_id: 업데이트할 메모리 ID
            params: 업데이트 파라미터
            
        Returns:
            UpdateResponse: 업데이트 결과
            
        Raises:
            ValueError: 잘못된 파라미터
            RuntimeError: 스토리지 오류
        """
        if not self.memory_service:
            raise RuntimeError("Storage backend not initialized")
        
        try:
            logger.debug(f"Updating memory: {memory_id}")
            
            result = await self.memory_service.update(
                memory_id=memory_id,
                content=params.content,
                category=params.category,
                tags=params.tags
            )
            
            logger.info(f"Memory updated successfully: {memory_id}")
            return result
            
        except ValueError as e:
            logger.warning(f"Invalid parameters for update_memory: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to update memory: {e}")
            raise RuntimeError(f"Failed to update memory: {e}")
    
    async def delete_memory(self, memory_id: str) -> DeleteResponse:
        """메모리 삭제
        
        Args:
            memory_id: 삭제할 메모리 ID
            
        Returns:
            DeleteResponse: 삭제 결과
            
        Raises:
            ValueError: 잘못된 파라미터
            RuntimeError: 스토리지 오류
        """
        if not self.memory_service:
            raise RuntimeError("Storage backend not initialized")
        
        try:
            logger.debug(f"Deleting memory: {memory_id}")
            
            result = await self.memory_service.delete(memory_id)
            
            logger.info(f"Memory deleted successfully: {memory_id}")
            return result
            
        except ValueError as e:
            logger.warning(f"Invalid parameters for delete_memory: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            raise RuntimeError(f"Failed to delete memory: {e}")
    
    async def get_stats(self, params: StatsParams) -> StatsResponse:
        """통계 조회
        
        Args:
            params: 통계 조회 요청 파라미터
            
        Returns:
            StatsResponse: 통계 정보
            
        Raises:
            ValueError: 잘못된 파라미터
            RuntimeError: 스토리지 오류
        """
        if not self.stats_service:
            raise RuntimeError("Storage backend not initialized")
        
        try:
            logger.debug(f"Getting stats with group_by: {params.group_by}")
            
            # StatsService의 get_overall_stats 메서드 사용
            stats_data = await self.stats_service.get_overall_stats(
                project_id=params.project_id,
                start_date=params.start_date,
                end_date=params.end_date
            )
            
            # StatsResponse 형태로 변환
            result = StatsResponse(
                total_memories=stats_data["total_memories"],
                unique_projects=stats_data["unique_projects"],
                categories_breakdown=stats_data["categories_breakdown"],
                sources_breakdown=stats_data["sources_breakdown"],
                projects_breakdown=stats_data["projects_breakdown"],
                date_range=stats_data["date_range"],
                query_time_ms=stats_data["query_time_ms"]
            )
            
            logger.info(f"Stats retrieved successfully, total memories: {result.total_memories}")
            return result
            
        except ValueError as e:
            logger.warning(f"Invalid parameters for get_stats: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            raise RuntimeError(f"Failed to get stats: {e}")
    
    async def get_all_memories(self, limit: int = 1000) -> list:
        """모든 메모리 조회 (테스트용)
        
        Args:
            limit: 조회할 최대 메모리 수
            
        Returns:
            list: 메모리 객체 리스트
        """
        if not self.db:
            raise RuntimeError("Storage backend not initialized")
        
        try:
            # 데이터베이스에서 직접 메모리 조회
            query = """
                SELECT id, content, category, project_id, source, tags, created_at, updated_at
                FROM memories 
                ORDER BY created_at DESC 
                LIMIT ?
            """
            
            rows = await self.db.fetchall(query, (limit,))
            
            # 간단한 메모리 객체로 변환
            memories = []
            for row in rows:
                memory = type('Memory', (), {
                    'id': row[0],
                    'content': row[1],
                    'category': row[2],
                    'project_id': row[3],
                    'source': row[4],
                    'tags': row[5].split(',') if row[5] else [],
                    'created_at': row[6],
                    'updated_at': row[7]
                })()
                memories.append(memory)
            
            return memories
            
        except Exception as e:
            logger.error(f"Failed to get all memories: {e}")
            raise RuntimeError(f"Failed to get all memories: {e}")