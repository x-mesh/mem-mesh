"""
Storage Manager - MCP 서버들이 공유하는 스토리지 초기화/종료 로직.
"""

from typing import Optional, Union
from ..core.config import Settings
from ..core.storage.base import StorageBackend
from ..core.storage.direct import DirectStorageBackend
from ..core.storage.api import APIStorageBackend
from ..core.utils.logger import get_logger

logger = get_logger("mcp-storage")


class StorageManager:
    """스토리지 백엔드 관리자"""
    
    def __init__(self):
        self._storage: Optional[StorageBackend] = None
    
    @property
    def storage(self) -> Optional[StorageBackend]:
        """현재 스토리지 백엔드 반환"""
        return self._storage
    
    @property
    def is_initialized(self) -> bool:
        """스토리지 초기화 여부"""
        return self._storage is not None
    
    async def initialize(self, settings: Optional[Settings] = None) -> StorageBackend:
        """스토리지 백엔드 초기화
        
        Args:
            settings: 설정 객체. None이면 기본 설정 사용
            
        Returns:
            초기화된 StorageBackend 인스턴스
        """
        if settings is None:
            settings = Settings()
        
        logger.info("Initializing storage backend", storage_mode=settings.storage_mode)
        
        try:
            if settings.storage_mode == "direct":
                self._storage = DirectStorageBackend(settings.database_path)
                logger.info("Using DirectStorageBackend", database_path=settings.database_path)
            else:
                self._storage = APIStorageBackend(settings.api_base_url)
                logger.info("Using APIStorageBackend", api_base_url=settings.api_base_url)
            
            await self._storage.initialize()
            logger.info("Storage backend initialized successfully")
            return self._storage
        except Exception as e:
            logger.error("Failed to initialize storage", error=str(e), error_type=type(e).__name__)
            raise
    
    async def shutdown(self) -> None:
        """스토리지 백엔드 종료"""
        if self._storage:
            logger.info("Shutting down storage backend")
            await self._storage.shutdown()
            self._storage = None
            logger.info("Storage backend shutdown complete")
    
    def require_storage(self) -> StorageBackend:
        """스토리지가 초기화되었는지 확인하고 반환
        
        Returns:
            StorageBackend 인스턴스
            
        Raises:
            RuntimeError: 스토리지가 초기화되지 않은 경우
        """
        if self._storage is None:
            raise RuntimeError("Storage not initialized. Call initialize() first.")
        return self._storage


# 전역 스토리지 매니저 인스턴스 (선택적 사용)
_global_manager: Optional[StorageManager] = None


def get_storage_manager() -> StorageManager:
    """전역 스토리지 매니저 반환 (lazy initialization)"""
    global _global_manager
    if _global_manager is None:
        _global_manager = StorageManager()
    return _global_manager
