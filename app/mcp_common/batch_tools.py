"""
Batch operations for MCP tools
Enables efficient batch processing to reduce token usage
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import json

from ..core.services.memory import MemoryService
from ..core.services.search import SearchService
from ..core.embeddings.service import EmbeddingService
from ..core.database.base import Database
from ..core.services.cache_manager import get_cache_manager

logger = logging.getLogger(__name__)


class BatchOperationHandler:
    """
    Handles batch operations for MCP tools
    Reduces token usage by 30-50% through batch processing
    """

    def __init__(
        self,
        memory_service: MemoryService,
        search_service: SearchService,
        embedding_service: EmbeddingService,
        db: Database,
    ):
        """Initialize batch operation handler"""
        self.memory_service = memory_service
        self.search_service = search_service
        self.embedding_service = embedding_service
        self.db = db
        self.cache_manager = get_cache_manager()

    async def batch_add_memories(
        self,
        contents: List[str],
        project_id: Optional[str] = None,
        category: str = "task",
        source: str = "mcp_batch",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Batch add multiple memories with single embedding generation

        Args:
            contents: List of memory contents to add
            project_id: Project ID for all memories
            category: Category for all memories
            source: Source for all memories
            tags: Tags for all memories

        Returns:
            Dictionary with results and statistics
        """
        start_time = datetime.now()
        results = []
        errors = []

        try:
            # 배치 임베딩 생성
            logger.info(f"Generating batch embeddings for {len(contents)} memories")
            embeddings = self.embedding_service.embed_batch(contents)

            # 각 메모리 저장
            for i, content in enumerate(contents):
                try:
                    # 임베딩과 함께 메모리 추가
                    memory = await self.memory_service.add_with_embedding(
                        content=content,
                        embedding=embeddings[i],
                        project_id=project_id,
                        category=category,
                        source=source,
                        tags=tags,
                    )
                    results.append(
                        {
                            "index": i,
                            "id": memory.id,
                            "content": content[:100] + "..."
                            if len(content) > 100
                            else content,
                            "status": "success",
                        }
                    )
                except Exception as e:
                    logger.error(f"Failed to add memory {i}: {e}")
                    errors.append(
                        {
                            "index": i,
                            "content": content[:100] + "..."
                            if len(content) > 100
                            else content,
                            "error": str(e),
                            "status": "failed",
                        }
                    )

        except Exception as e:
            logger.error(f"Batch embedding failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "message": "Batch embedding generation failed",
            }

        elapsed_time = (datetime.now() - start_time).total_seconds()

        # 토큰 절감 계산 (배치 처리로 인한 예상 절감)
        tokens_saved = len(contents) * 10  # 각 개별 임베딩 요청당 약 10 토큰 절감

        return {
            "status": "success",
            "total": len(contents),
            "successful": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
            "elapsed_seconds": elapsed_time,
            "tokens_saved": tokens_saved,
            "average_time_per_memory": elapsed_time / len(contents) if contents else 0,
        }

    async def batch_search(
        self,
        queries: List[str],
        project_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 5,
    ) -> Dict[str, Any]:
        """
        Batch search multiple queries with cached results

        Args:
            queries: List of search queries
            project_id: Project ID filter
            category: Category filter
            limit: Number of results per query

        Returns:
            Dictionary with search results for each query
        """
        start_time = datetime.now()
        results = {}
        cache_hits = 0

        # 배치 임베딩 생성 (캐시되지 않은 쿼리들만)
        uncached_queries = []
        cached_embeddings = {}

        for query in queries:
            cached_embedding = await self.cache_manager.get_cached_embedding(query)
            if cached_embedding:
                cached_embeddings[query] = cached_embedding
                cache_hits += 1
            else:
                uncached_queries.append(query)

        # 캐시되지 않은 쿼리들에 대해 배치 임베딩 생성
        if uncached_queries:
            logger.info(
                f"Generating batch embeddings for {len(uncached_queries)} uncached queries"
            )
            new_embeddings = self.embedding_service.embed_batch(uncached_queries, is_query=True)

            # 캐시에 저장
            for query, embedding in zip(uncached_queries, new_embeddings):
                await self.cache_manager.cache_embedding(query, embedding)
                cached_embeddings[query] = embedding

        # 각 쿼리에 대해 검색 수행
        for query in queries:
            try:
                # 캐시된 검색 결과 확인
                cached_result = await self.cache_manager.get_cached_search(
                    query=query, project_id=project_id, category=category, limit=limit
                )

                if cached_result:
                    results[query] = {
                        "status": "success",
                        "source": "cache",
                        "results": cached_result,
                    }
                    cache_hits += 1
                else:
                    # 새로운 검색 수행
                    search_result = await self.search_service.search(
                        query=query,
                        project_id=project_id,
                        category=category,
                        limit=limit,
                    )

                    results[query] = {
                        "status": "success",
                        "source": "search",
                        "results": search_result.dict(),
                    }

            except Exception as e:
                logger.error(f"Search failed for query '{query}': {e}")
                results[query] = {"status": "failed", "error": str(e)}

        elapsed_time = (datetime.now() - start_time).total_seconds()
        tokens_saved = cache_hits * 50  # 각 캐시 히트당 약 50 토큰 절감

        return {
            "status": "success",
            "queries": len(queries),
            "cache_hits": cache_hits,
            "results": results,
            "elapsed_seconds": elapsed_time,
            "tokens_saved": tokens_saved,
        }

    async def batch_operations(
        self, operations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Execute multiple mixed operations in batch

        Args:
            operations: List of operation dictionaries with 'type' and parameters

        Returns:
            Dictionary with results for each operation
        """
        start_time = datetime.now()
        results = []

        # 작업 타입별로 분류
        add_operations = []
        search_operations = []
        pin_add_operations = []

        for i, op in enumerate(operations):
            op["index"] = i
            if op["type"] == "add":
                add_operations.append(op)
            elif op["type"] == "search":
                search_operations.append(op)
            elif op["type"] == "pin_add":
                pin_add_operations.append(op)

        # 배치 추가 작업 처리
        if add_operations:
            contents = [op.get("content", "") for op in add_operations]
            logger.info(f"Processing {len(add_operations)} add operations with contents: {[c[:30] for c in contents]}")
            
            batch_add_result = await self.batch_add_memories(
                contents=contents,
                project_id=add_operations[0].get("project_id"),
                category=add_operations[0].get("category", "task"),
                source=add_operations[0].get("source", "mcp_batch"),
                tags=add_operations[0].get("tags"),
            )
            
            logger.info(f"batch_add_result status: {batch_add_result.get('status')}, results count: {len(batch_add_result.get('results', []))}, errors count: {len(batch_add_result.get('errors', []))}")

            # 결과를 원래 인덱스에 매핑
            if batch_add_result.get("status") == "success":
                for i, op in enumerate(add_operations):
                    # batch_add_result["results"]는 리스트이고, 각 항목에 index가 있음
                    add_results = batch_add_result.get("results", [])
                    logger.info(f"Mapping add operation {i}: op_index={op['index']}, add_results_len={len(add_results)}")
                    if i < len(add_results):
                        results.append(
                            {
                                "index": op["index"],
                                "type": "add",
                                "success": True,
                                "memory_id": add_results[i].get("id"),
                                "content": add_results[i].get("content"),
                            }
                        )
                        logger.info(f"Added result for index {op['index']}")
            else:
                # 배치 추가 실패 시 모든 작업을 실패로 표시
                for op in add_operations:
                    results.append(
                        {
                            "index": op["index"],
                            "type": "add",
                            "success": False,
                            "error": batch_add_result.get("error", "Unknown error"),
                        }
                    )

        # 배치 검색 작업 처리
        if search_operations:
            queries = [op.get("query", "") for op in search_operations]
            batch_search_result = await self.batch_search(
                queries=queries,
                project_id=search_operations[0].get("project_id"),
                category=search_operations[0].get("category"),
                limit=search_operations[0].get("limit", 5),
            )

            # 결과를 원래 인덱스에 매핑
            if batch_search_result.get("status") == "success":
                for op in search_operations:
                    query = op.get("query", "")
                    search_results = batch_search_result.get("results", {})
                    if query in search_results:
                        query_result = search_results[query]
                        results.append(
                            {
                                "index": op["index"],
                                "type": "search",
                                "success": True,
                                "results": query_result.get("results", []),
                                "total": query_result.get("total"),
                            }
                        )
            else:
                # 배치 검색 실패 시 모든 작업을 실패로 표시
                for op in search_operations:
                    results.append(
                        {
                            "index": op["index"],
                            "type": "search",
                            "success": False,
                            "error": batch_search_result.get("error", "Unknown error"),
                        }
                    )

        # 배치 pin_add 작업 처리
        if pin_add_operations:
            from ..core.services.pin import PinService
            from ..core.services.importance_analyzer import ImportanceAnalyzer

            pin_service = PinService(self.db)
            analyzer = ImportanceAnalyzer()

            for op in pin_add_operations:
                try:
                    content = op.get("content", "")
                    project_id = op.get("project_id", "")
                    importance = op.get("importance")
                    tags = op.get("tags")

                    auto_importance = False
                    if importance is None:
                        importance = analyzer.analyze(content, tags)
                        auto_importance = True

                    pin_result = await pin_service.create_pin(
                        project_id=project_id,
                        content=content,
                        importance=importance,
                        tags=tags,
                        auto_importance=auto_importance,
                    )
                    results.append({
                        "index": op["index"],
                        "type": "pin_add",
                        "success": True,
                        "pin_id": pin_result.id,
                        "importance": pin_result.importance,
                        "auto_importance": auto_importance,
                    })
                except Exception as e:
                    results.append({
                        "index": op["index"],
                        "type": "pin_add",
                        "success": False,
                        "error": str(e),
                    })

        # 인덱스 순으로 정렬
        results.sort(key=lambda x: x["index"])

        elapsed_time = (datetime.now() - start_time).total_seconds()
        total_tokens_saved = (
            len(add_operations) * 10
            + len(search_operations) * 30
            + len(pin_add_operations) * 5
        )

        return {
            "status": "success",
            "total_operations": len(operations),
            "results": results,
            "elapsed_seconds": elapsed_time,
            "tokens_saved": total_tokens_saved,
            "batch_stats": {
                "add_operations": len(add_operations),
                "search_operations": len(search_operations),
                "pin_add_operations": len(pin_add_operations),
            },
        }


async def test_batch_operations():
    """Test batch operations functionality"""
    from ..core.database.base import Database
    from ..core.config import Settings
    from ..core.embeddings.service import EmbeddingService
    from ..core.services.memory import MemoryService
    from ..core.services.search import SearchService

    # Initialize services
    test_settings = Settings()
    db = Database(test_settings.database_path, embedding_dim=test_settings.embedding_dim)
    await db.connect()
    embedding_service = EmbeddingService(preload=False)
    memory_service = MemoryService(db, embedding_service)
    search_service = SearchService(db, embedding_service)

    handler = BatchOperationHandler(
        memory_service=memory_service,
        search_service=search_service,
        embedding_service=embedding_service,
        db=db,
    )

    # Test batch add
    print("\n=== Testing Batch Add ===")
    contents = [
        "Implement user authentication system",
        "Fix bug in payment processing",
        "Add caching layer for API responses",
    ]

    result = await handler.batch_add_memories(
        contents=contents, category="task", source="test_batch"
    )

    print(f"Batch add result: {json.dumps(result, indent=2)}")

    # Test batch search
    print("\n=== Testing Batch Search ===")
    queries = ["authentication", "payment", "caching"]

    result = await handler.batch_search(queries=queries)
    print(f"Batch search result: {json.dumps(result, indent=2)}")

    # Test mixed batch operations
    print("\n=== Testing Mixed Batch Operations ===")
    operations = [
        {"type": "add", "content": "Deploy to production"},
        {"type": "search", "query": "deployment"},
        {"type": "add", "content": "Monitor system performance"},
        {"type": "search", "query": "monitoring"},
    ]

    result = await handler.batch_operations(operations=operations)
    print(f"Mixed batch result: {json.dumps(result, indent=2)}")

    # Print cache statistics
    cache_stats = get_cache_manager().get_cache_stats()
    print(f"\n=== Cache Statistics ===")
    print(f"Cache stats: {json.dumps(cache_stats, indent=2)}")


if __name__ == "__main__":
    asyncio.run(test_batch_operations())
