"""API 기반 스토리지 백엔드 구현"""

import asyncio
import logging
from typing import Optional

import httpx

from ..schemas.requests import AddParams, SearchParams, StatsParams, UpdateParams
from ..schemas.responses import (
    AddResponse,
    ContextResponse,
    DeleteResponse,
    SearchResponse,
    StatsResponse,
    UpdateResponse,
)
from .base import StorageBackend

logger = logging.getLogger(__name__)


class APIStorageBackend(StorageBackend):
    """FastAPI REST API를 통한 스토리지 백엔드

    이 구현체는 FastAPI 서버의 REST API를 호출하여 메모리 저장/검색/업데이트/삭제
    작업을 수행합니다. 네트워크 오류에 대한 재시도 로직을 포함합니다.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        APIStorageBackend 초기화

        Args:
            base_url: FastAPI 서버 기본 URL
            timeout: HTTP 요청 타임아웃 (초)
            max_retries: 최대 재시도 횟수
            retry_delay: 재시도 간격 (초)
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self.client: Optional[httpx.AsyncClient] = None

        logger.info(f"APIStorageBackend initialized with base_url: {base_url}")

    async def initialize(self) -> None:
        """스토리지 백엔드 초기화

        HTTP 클라이언트를 생성하고 서버 연결을 확인합니다.
        """
        try:
            # Create HTTP client
            self.client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )

            # Verify server connection (health check)
            await self._check_server_health()

            logger.info("APIStorageBackend initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize APIStorageBackend: {e}")
            if self.client:
                await self.client.aclose()
                self.client = None
            raise RuntimeError(f"Failed to initialize API storage backend: {e}")

    async def shutdown(self) -> None:
        """스토리지 백엔드 종료

        HTTP 클라이언트를 해제하고 리소스를 정리합니다.
        """
        try:
            if self.client:
                await self.client.aclose()
                self.client = None

            logger.info("APIStorageBackend shutdown successfully")

        except Exception as e:
            logger.error(f"Error during APIStorageBackend shutdown: {e}")
            raise RuntimeError(f"Failed to shutdown API storage backend: {e}")

    async def add_memory(self, params: AddParams) -> AddResponse:
        """메모리 추가

        Args:
            params: 메모리 추가 요청 파라미터

        Returns:
            AddResponse: 추가된 메모리 정보

        Raises:
            ValueError: 잘못된 파라미터
            RuntimeError: API 호출 오류
        """
        if not self.client:
            raise RuntimeError("Storage backend not initialized")

        try:
            logger.debug(
                f"Adding memory via API with content length: {len(params.content)}"
            )

            response_data = await self._make_request_with_retry(
                method="POST",
                url="/api/memories",
                json_data=params.model_dump(exclude_none=True),
            )

            result = AddResponse(**response_data)
            logger.info(f"Memory added successfully via API: {result.id}")
            return result

        except ValueError as e:
            logger.warning(f"Invalid parameters for add_memory: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to add memory via API: {e}")
            raise RuntimeError(f"Failed to add memory via API: {e}")

    async def search_memories(self, params: SearchParams) -> SearchResponse:
        """메모리 검색

        Args:
            params: 메모리 검색 요청 파라미터

        Returns:
            SearchResponse: 검색 결과

        Raises:
            ValueError: 잘못된 파라미터
            RuntimeError: API 호출 오류
        """
        if not self.client:
            raise RuntimeError("Storage backend not initialized")

        try:
            logger.debug(f"Searching memories via API with query: '{params.query}'")

            # Build query parameters for GET request
            query_params = {}
            if params.query:
                query_params["query"] = params.query
            if params.project_id:
                query_params["project_id"] = params.project_id
            if params.category:
                query_params["category"] = params.category
            if params.limit != 5:  # Only when not default value
                query_params["limit"] = params.limit
            if params.recency_weight != 0.0:  # Only when not default value
                query_params["recency_weight"] = params.recency_weight

            response_data = await self._make_request_with_retry(
                method="GET", url="/api/memories/search", params=query_params
            )

            result = SearchResponse(**response_data)
            logger.info(
                f"Search completed via API, found {len(result.results)} results"
            )
            return result

        except ValueError as e:
            logger.warning(f"Invalid parameters for search_memories: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to search memories via API: {e}")
            raise RuntimeError(f"Failed to search memories via API: {e}")

    async def get_context(
        self, memory_id: str, depth: int, project_id: Optional[str]
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
            RuntimeError: API 호출 오류
        """
        if not self.client:
            raise RuntimeError("Storage backend not initialized")

        try:
            logger.debug(
                f"Getting context via API for memory_id: {memory_id}, depth: {depth}"
            )

            # Build query parameters
            query_params = {"depth": depth}
            if project_id:
                query_params["project_id"] = project_id

            response_data = await self._make_request_with_retry(
                method="GET",
                url=f"/api/memories/{memory_id}/context",
                params=query_params,
            )

            result = ContextResponse(**response_data)
            logger.info(
                f"Context retrieved via API for memory {memory_id}, found {len(result.related_memories)} related memories"
            )
            return result

        except ValueError as e:
            logger.warning(f"Invalid parameters for get_context: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get context via API: {e}")
            raise RuntimeError(f"Failed to get context via API: {e}")

    async def update_memory(
        self, memory_id: str, params: UpdateParams
    ) -> UpdateResponse:
        """메모리 업데이트

        Args:
            memory_id: 업데이트할 메모리 ID
            params: 업데이트 파라미터

        Returns:
            UpdateResponse: 업데이트 결과

        Raises:
            ValueError: 잘못된 파라미터
            RuntimeError: API 호출 오류
        """
        if not self.client:
            raise RuntimeError("Storage backend not initialized")

        try:
            logger.debug(f"Updating memory via API: {memory_id}")

            response_data = await self._make_request_with_retry(
                method="PUT",
                url=f"/api/memories/{memory_id}",
                json_data=params.model_dump(exclude_none=True),
            )

            result = UpdateResponse(**response_data)
            logger.info(f"Memory updated successfully via API: {memory_id}")
            return result

        except ValueError as e:
            logger.warning(f"Invalid parameters for update_memory: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to update memory via API: {e}")
            raise RuntimeError(f"Failed to update memory via API: {e}")

    async def delete_memory(self, memory_id: str) -> DeleteResponse:
        """메모리 삭제

        Args:
            memory_id: 삭제할 메모리 ID

        Returns:
            DeleteResponse: 삭제 결과

        Raises:
            ValueError: 잘못된 파라미터
            RuntimeError: API 호출 오류
        """
        if not self.client:
            raise RuntimeError("Storage backend not initialized")

        try:
            logger.debug(f"Deleting memory via API: {memory_id}")

            response_data = await self._make_request_with_retry(
                method="DELETE", url=f"/api/memories/{memory_id}"
            )

            result = DeleteResponse(**response_data)
            logger.info(f"Memory deleted successfully via API: {memory_id}")
            return result

        except ValueError as e:
            logger.warning(f"Invalid parameters for delete_memory: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to delete memory via API: {e}")
            raise RuntimeError(f"Failed to delete memory via API: {e}")

    async def get_stats(self, params: StatsParams) -> StatsResponse:
        """통계 조회

        Args:
            params: 통계 조회 요청 파라미터

        Returns:
            StatsResponse: 통계 정보

        Raises:
            ValueError: 잘못된 파라미터
            RuntimeError: API 호출 오류
        """
        if not self.client:
            raise RuntimeError("Storage backend not initialized")

        try:
            logger.debug(f"Getting stats via API with group_by: {params.group_by}")

            # Build query parameters
            query_params = {}
            if params.project_id:
                query_params["project_id"] = params.project_id
            if params.start_date:
                query_params["start_date"] = params.start_date
            if params.end_date:
                query_params["end_date"] = params.end_date
            if params.group_by != "overall":  # Only when not default value
                query_params["group_by"] = params.group_by

            response_data = await self._make_request_with_retry(
                method="GET", url="/api/memories/stats", params=query_params
            )

            result = StatsResponse(**response_data)
            logger.info(
                f"Stats retrieved successfully via API, total memories: {result.total_memories}"
            )
            return result

        except ValueError as e:
            logger.warning(f"Invalid parameters for get_stats: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get stats via API: {e}")
            raise RuntimeError(f"Failed to get stats via API: {e}")

    # Private helper methods

    async def _check_server_health(self) -> None:
        """서버 상태 확인"""
        try:
            response = await self.client.get("/api/health")
            response.raise_for_status()
            logger.info("API server health check passed")
        except Exception as e:
            logger.error(f"API server health check failed: {e}")
            raise RuntimeError(f"API server is not available: {e}")

    async def _make_request_with_retry(
        self,
        method: str,
        url: str,
        json_data: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """재시도 로직을 포함한 HTTP 요청

        Args:
            method: HTTP 메서드 (GET, POST, PUT, DELETE)
            url: 요청 URL
            json_data: JSON 요청 본문 (선택사항)
            params: 쿼리 파라미터 (선택사항)

        Returns:
            dict: 응답 JSON 데이터

        Raises:
            RuntimeError: 모든 재시도 실패 후
        """
        last_error = None

        for attempt in range(self.max_retries + 1):  # First attempt + retries
            try:
                logger.debug(
                    f"Making {method} request to {url} (attempt {attempt + 1}/{self.max_retries + 1})"
                )

                # Execute HTTP request
                if method.upper() == "GET":
                    response = await self.client.get(url, params=params)
                elif method.upper() == "POST":
                    response = await self.client.post(
                        url, json=json_data, params=params
                    )
                elif method.upper() == "PUT":
                    response = await self.client.put(url, json=json_data, params=params)
                elif method.upper() == "DELETE":
                    response = await self.client.delete(url, params=params)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                # Check HTTP status code
                if response.status_code == 404:
                    # Do not retry 404
                    response.raise_for_status()
                elif response.status_code >= 400:
                    # Retry on 4xx/5xx errors
                    response.raise_for_status()

                # Handle successful response
                return response.json()

            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(f"Request timeout (attempt {attempt + 1}): {e}")

            except httpx.ConnectError as e:
                last_error = e
                logger.warning(f"Connection error (attempt {attempt + 1}): {e}")

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    # Fail immediately on 404 without retry
                    logger.error(f"Resource not found (404): {e}")
                    raise RuntimeError(f"Resource not found: {e}")
                elif e.response.status_code >= 500:
                    # Retry on 5xx server errors
                    last_error = e
                    logger.warning(f"Server error (attempt {attempt + 1}): {e}")
                else:
                    # Do not retry 4xx client errors
                    logger.error(f"Client error (4xx): {e}")
                    raise RuntimeError(f"Client error: {e}")

            except Exception as e:
                last_error = e
                logger.warning(f"Unexpected error (attempt {attempt + 1}): {e}")

            # Wait before retry if not last attempt
            if attempt < self.max_retries:
                delay = self.retry_delay * (2**attempt)  # Exponential backoff
                logger.debug(f"Waiting {delay:.1f}s before retry...")
                await asyncio.sleep(delay)

        # All retries failed
        logger.error(f"All retry attempts failed for {method} {url}")
        raise RuntimeError(
            f"Request failed after {self.max_retries + 1} attempts: {last_error}"
        )
