"""스토리지 백엔드 추상 인터페이스"""

from abc import ABC, abstractmethod
from typing import Optional
from ..schemas.requests import AddParams, SearchParams, UpdateParams, StatsParams
from ..schemas.responses import (
    AddResponse, SearchResponse, ContextResponse, 
    UpdateResponse, DeleteResponse, StatsResponse
)


class StorageBackend(ABC):
    """스토리지 백엔드 추상 인터페이스
    
    이 인터페이스는 다양한 스토리지 구현체(Direct SQLite, API 클라이언트 등)가
    공통으로 구현해야 하는 메서드들을 정의합니다.
    """
    
    @abstractmethod
    async def initialize(self) -> None:
        """스토리지 백엔드 초기화
        
        데이터베이스 연결, HTTP 클라이언트 설정 등 필요한 초기화 작업을 수행합니다.
        """
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """스토리지 백엔드 종료
        
        연결 해제, 리소스 정리 등 종료 작업을 수행합니다.
        """
        pass
    
    @abstractmethod
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
        pass
    
    @abstractmethod
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
        pass
    
    @abstractmethod
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
        pass
    
    @abstractmethod
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
        pass
    
    @abstractmethod
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
        pass
    
    @abstractmethod
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
        pass