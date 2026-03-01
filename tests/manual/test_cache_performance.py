#!/usr/bin/env python3
"""
Cache Performance Test Script
Tests the effectiveness of caching and batch operations

Run with: python test_cache_performance.py
"""

import asyncio
import time
import json
from typing import Dict, Any

# Add parent directory to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.memory import MemoryService
from app.core.services.search import SearchService
from app.core.services.cache_manager import get_cache_manager, reset_cache_manager
from app.mcp_common.batch_tools import BatchOperationHandler


class PerformanceTest:
    """Performance testing for cache and batch operations"""

    def __init__(self):
        """Initialize test environment"""
        # Use default database path
        from app.core.config import Settings
        settings = Settings()
        self.db = Database(db_path=settings.database_path)
        self.embedding_service = EmbeddingService(preload=False)
        self.memory_service = MemoryService(self.db, self.embedding_service)
        self.search_service = SearchService(self.db, self.embedding_service)
        self.batch_handler = BatchOperationHandler(
            memory_service=self.memory_service,
            search_service=self.search_service,
            embedding_service=self.embedding_service,
            db=self.db
        )
        self.cache_manager = get_cache_manager()

        # Test data
        self.test_queries = [
            "user authentication",
            "database optimization",
            "API rate limiting",
            "error handling",
            "caching strategies",
            "performance monitoring",
            "security vulnerabilities",
            "deployment pipeline",
            "unit testing",
            "code review process"
        ]

        self.test_contents = [
            "Implement OAuth2 authentication for API endpoints",
            "Optimize database queries with proper indexing",
            "Add rate limiting to prevent API abuse",
            "Improve error handling with custom exception classes",
            "Implement Redis caching for frequently accessed data",
            "Set up performance monitoring with Prometheus",
            "Fix SQL injection vulnerability in search endpoint",
            "Configure CI/CD pipeline with GitHub Actions",
            "Write unit tests for authentication module",
            "Establish code review guidelines for the team"
        ]

    async def test_search_without_cache(self) -> Dict[str, Any]:
        """Test search performance without caching"""
        print("\n=== Testing Search WITHOUT Cache ===")
        reset_cache_manager()  # Clear all caches
        self.cache_manager = get_cache_manager()

        start_time = time.time()
        results = []

        for query in self.test_queries:
            query_start = time.time()
            result = await self.search_service.search(query, limit=5)
            query_time = time.time() - query_start
            results.append({
                'query': query,
                'time': query_time,
                'result_count': len(result.results)
            })
            print(f"  Query '{query[:30]}...': {query_time:.3f}s")

        total_time = time.time() - start_time

        return {
            'total_time': total_time,
            'average_time': total_time / len(self.test_queries),
            'queries': len(self.test_queries),
            'results': results
        }

    async def test_search_with_cache(self) -> Dict[str, Any]:
        """Test search performance with caching"""
        print("\n=== Testing Search WITH Cache ===")
        # Don't reset cache - use existing cache

        start_time = time.time()
        results = []
        cache_hits = 0

        # Run same queries twice to test cache
        for round_num in range(2):
            print(f"\n  Round {round_num + 1}:")
            for query in self.test_queries:
                query_start = time.time()
                result = await self.search_service.search(query, limit=5)
                query_time = time.time() - query_start

                # Check if it was a cache hit
                if query_time < 0.01:  # Very fast = likely cache hit
                    cache_hits += 1

                results.append({
                    'round': round_num + 1,
                    'query': query,
                    'time': query_time,
                    'result_count': len(result.results)
                })
                print(f"    Query '{query[:30]}...': {query_time:.3f}s {'[CACHE HIT]' if query_time < 0.01 else ''}")

        total_time = time.time() - start_time

        return {
            'total_time': total_time,
            'average_time': total_time / (len(self.test_queries) * 2),
            'queries': len(self.test_queries) * 2,
            'cache_hits': cache_hits,
            'cache_hit_rate': cache_hits / (len(self.test_queries) * 2),
            'results': results
        }

    async def test_batch_add_vs_individual(self) -> Dict[str, Any]:
        """Compare batch add vs individual add operations"""
        print("\n=== Testing Batch Add vs Individual Add ===")

        # Test individual adds
        print("\n  Individual Adds:")
        individual_start = time.time()
        individual_results = []

        for content in self.test_contents[:5]:  # Test with 5 items
            add_start = time.time()
            result = await self.memory_service.create(
                content=content,
                category="test",
                source="performance_test"
            )
            add_time = time.time() - add_start
            individual_results.append({
                'content': content[:50],
                'time': add_time,
                'status': result.status
            })
            print(f"    Add '{content[:30]}...': {add_time:.3f}s")

        individual_total = time.time() - individual_start

        # Test batch add
        print("\n  Batch Add:")
        batch_start = time.time()
        batch_result = await self.batch_handler.batch_add_memories(
            contents=self.test_contents[5:10],  # Different 5 items
            category="test",
            source="performance_test_batch"
        )
        batch_total = time.time() - batch_start
        print(f"    Batch add 5 items: {batch_total:.3f}s")

        return {
            'individual': {
                'total_time': individual_total,
                'average_time': individual_total / 5,
                'items': 5,
                'results': individual_results
            },
            'batch': {
                'total_time': batch_total,
                'average_time': batch_total / 5,
                'items': batch_result['total'],
                'successful': batch_result['successful'],
                'tokens_saved': batch_result.get('tokens_saved', 0)
            },
            'speedup': individual_total / batch_total if batch_total > 0 else 0,
            'time_saved': individual_total - batch_total
        }

    async def test_batch_search(self) -> Dict[str, Any]:
        """Test batch search performance"""
        print("\n=== Testing Batch Search ===")

        # Clear cache for fair comparison
        reset_cache_manager()
        self.cache_manager = get_cache_manager()

        # Test individual searches
        print("\n  Individual Searches:")
        individual_start = time.time()
        for query in self.test_queries[:5]:
            query_start = time.time()
            await self.search_service.search(query, limit=3)
            print(f"    Query '{query[:30]}...': {time.time() - query_start:.3f}s")
        individual_total = time.time() - individual_start

        # Test batch search
        print("\n  Batch Search:")
        batch_start = time.time()
        batch_result = await self.batch_handler.batch_search(
            queries=self.test_queries[5:10],
            limit=3
        )
        batch_total = time.time() - batch_start
        print(f"    Batch search 5 queries: {batch_total:.3f}s")

        return {
            'individual_time': individual_total,
            'batch_time': batch_total,
            'speedup': individual_total / batch_total if batch_total > 0 else 0,
            'cache_hits': batch_result.get('cache_hits', 0),
            'tokens_saved': batch_result.get('tokens_saved', 0)
        }

    async def test_cache_statistics(self) -> Dict[str, Any]:
        """Get overall cache statistics"""
        print("\n=== Cache Statistics ===")
        stats = self.cache_manager.get_cache_stats()

        print(f"  Total tokens saved: {stats['total_tokens_saved']}")
        print(f"  Estimated cost saved: ${stats['estimated_cost_saved']:.4f}")
        print(f"  Embedding cache hit rate: {stats['caches']['embedding']['hit_rate']:.2%}")
        print(f"  Search cache hit rate: {stats['caches']['search']['hit_rate']:.2%}")

        return stats

    async def run_all_tests(self) -> None:
        """Run all performance tests"""
        print("=" * 60)
        print("CACHE PERFORMANCE TEST SUITE")
        print("=" * 60)

        results = {}

        # Test 1: Search without cache
        results['search_without_cache'] = await self.test_search_without_cache()

        # Test 2: Search with cache
        results['search_with_cache'] = await self.test_search_with_cache()

        # Test 3: Batch add vs individual
        results['batch_add'] = await self.test_batch_add_vs_individual()

        # Test 4: Batch search
        results['batch_search'] = await self.test_batch_search()

        # Test 5: Cache statistics
        results['cache_stats'] = await self.test_cache_statistics()

        # Print summary
        print("\n" + "=" * 60)
        print("PERFORMANCE TEST SUMMARY")
        print("=" * 60)

        # Search performance improvement
        search_improvement = (
            (results['search_without_cache']['average_time'] -
             results['search_with_cache']['average_time']) /
            results['search_without_cache']['average_time'] * 100
        )
        print("\n📊 Search Performance:")
        print(f"  Without cache: {results['search_without_cache']['average_time']:.3f}s avg")
        print(f"  With cache: {results['search_with_cache']['average_time']:.3f}s avg")
        print(f"  Cache hit rate: {results['search_with_cache']['cache_hit_rate']:.2%}")
        print(f"  Performance improvement: {search_improvement:.1f}%")

        # Batch operations performance
        print("\n📦 Batch Operations:")
        print(f"  Add speedup: {results['batch_add']['speedup']:.2f}x faster")
        print(f"  Search speedup: {results['batch_search']['speedup']:.2f}x faster")
        print(f"  Time saved (add): {results['batch_add']['time_saved']:.2f}s")
        print(f"  Time saved (search): {results['batch_search']['individual_time'] - results['batch_search']['batch_time']:.2f}s")

        # Token savings
        total_tokens_saved = (
            results['cache_stats']['total_tokens_saved'] +
            results['batch_add']['batch'].get('tokens_saved', 0) +
            results['batch_search'].get('tokens_saved', 0)
        )
        estimated_cost_saved = total_tokens_saved * 0.00002  # Rough estimate

        print("\n💰 Token & Cost Savings:")
        print(f"  Total tokens saved: {total_tokens_saved:,}")
        print(f"  Estimated cost saved: ${estimated_cost_saved:.4f}")

        # Overall efficiency
        print("\n✨ Overall Efficiency Gains:")
        print(f"  Average search speedup with cache: {search_improvement:.1f}%")
        print(f"  Batch operations speedup: {((results['batch_add']['speedup'] + results['batch_search']['speedup']) / 2):.2f}x")
        print("  Memory efficiency: Reduced redundant embeddings")

        # Save detailed results
        with open("cache_performance_results.json", "w") as f:
            json.dump(results, f, indent=2, default=str)
        print("\n📁 Detailed results saved to: cache_performance_results.json")


async def main():
    """Main test runner"""
    tester = PerformanceTest()
    await tester.run_all_tests()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    except Exception as e:
        print(f"\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()