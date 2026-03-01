#!/usr/bin/env python3
"""
Search Quality Testing and Benchmarking
검색 품질 테스트 및 벤치마킹
"""

import asyncio
import json
import time
from typing import List, Dict
from datetime import datetime
import statistics

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.search import SearchService
from app.core.services.enhanced_search import EnhancedSearchService
from app.core.config import Settings


class SearchQualityTester:
    """Test and benchmark search quality"""

    def __init__(self):
        """Initialize test environment"""
        settings = Settings()
        self.db = Database(db_path=settings.database_path)
        self.embedding_service = EmbeddingService(preload=False)

        # Initialize both search services for comparison
        self.basic_search = SearchService(self.db, self.embedding_service)
        self.enhanced_search = EnhancedSearchService(
            self.db,
            self.embedding_service,
            enable_quality_scoring=True,
            enable_feedback=True,
            enable_dynamic_embedding=False  # Keep false for fair comparison
        )

        # Test queries with expected results
        self.test_cases = [
            {
                'query': 'urgent authentication bug',
                'expected_category': 'bug',
                'expected_keywords': ['auth', 'login', 'error'],
                'intent': 'debug'
            },
            {
                'query': 'how to implement caching',
                'expected_category': 'code_snippet',
                'expected_keywords': ['cache', 'implement', 'code'],
                'intent': 'lookup'
            },
            {
                'query': 'recent deployment issues',
                'expected_category': 'incident',
                'expected_keywords': ['deploy', 'issue', 'recent'],
                'intent': 'review'
            },
            {
                'query': 'database optimization ideas',
                'expected_category': 'idea',
                'expected_keywords': ['database', 'optimize', 'performance'],
                'intent': 'explore'
            },
            {
                'query': 'UserAuthenticationManager.validateToken',
                'expected_category': 'code_snippet',
                'expected_keywords': ['UserAuthenticationManager', 'validateToken'],
                'intent': 'lookup'
            }
        ]

    async def test_search_quality(self):
        """Run comprehensive search quality tests"""
        print("=" * 60)
        print("SEARCH QUALITY TEST SUITE")
        print("=" * 60)

        results = {
            'basic': [],
            'enhanced': []
        }

        for test_case in self.test_cases:
            print(f"\n🔍 Testing: '{test_case['query']}'")
            print(f"   Expected: {test_case['expected_category']} ({test_case['intent']})")

            # Test basic search
            basic_result = await self._test_basic_search(test_case)
            results['basic'].append(basic_result)

            # Test enhanced search
            enhanced_result = await self._test_enhanced_search(test_case)
            results['enhanced'].append(enhanced_result)

            # Compare results
            self._compare_results(test_case, basic_result, enhanced_result)

        # Generate summary report
        self._generate_summary_report(results)

    async def _test_basic_search(self, test_case: Dict) -> Dict:
        """Test basic search service"""
        start_time = time.time()

        response = await self.basic_search.search(
            query=test_case['query'],
            limit=5,
            search_mode='hybrid'
        )

        search_time = time.time() - start_time

        # Evaluate results
        evaluation = self._evaluate_results(
            test_case,
            response.results,
            search_time
        )

        return {
            'query': test_case['query'],
            'time': search_time,
            'count': len(response.results),
            'evaluation': evaluation
        }

    async def _test_enhanced_search(self, test_case: Dict) -> Dict:
        """Test enhanced search service"""
        start_time = time.time()

        response = await self.enhanced_search.search(
            query=test_case['query'],
            limit=5,
            search_mode='smart',
            performance_mode='balanced',
            min_quality_score=0.3
        )

        search_time = time.time() - start_time

        # Evaluate results
        evaluation = self._evaluate_results(
            test_case,
            response.results,
            search_time
        )

        # Add quality-specific metrics
        if response.results:
            evaluation['avg_quality_score'] = statistics.mean([
                getattr(r, 'quality_score', 0) for r in response.results
            ])

        # Check intent detection
        if hasattr(response, 'metadata') and response.metadata:
            detected_intent = response.metadata.get('intent', {}).get('type')
            evaluation['intent_match'] = detected_intent == test_case['intent']

        return {
            'query': test_case['query'],
            'time': search_time,
            'count': len(response.results),
            'evaluation': evaluation,
            'metadata': response.metadata if hasattr(response, 'metadata') else {}
        }

    def _evaluate_results(
        self,
        test_case: Dict,
        results: List,
        search_time: float
    ) -> Dict:
        """Evaluate search results quality"""
        evaluation = {
            'category_match': False,
            'keyword_coverage': 0.0,
            'relevance_score': 0.0,
            'response_time_ok': search_time < 1.0
        }

        if not results:
            return evaluation

        # Check category match in top result
        if results[0].category == test_case['expected_category']:
            evaluation['category_match'] = True

        # Calculate keyword coverage
        expected_keywords = test_case['expected_keywords']
        found_keywords = 0
        for keyword in expected_keywords:
            for result in results[:3]:  # Check top 3
                if keyword.lower() in result.content.lower():
                    found_keywords += 1
                    break

        evaluation['keyword_coverage'] = found_keywords / len(expected_keywords)

        # Calculate average relevance score
        scores = [r.similarity_score for r in results if hasattr(r, 'similarity_score')]
        if scores:
            evaluation['relevance_score'] = statistics.mean(scores)

        return evaluation

    def _compare_results(self, test_case: Dict, basic: Dict, enhanced: Dict):
        """Compare basic vs enhanced search results"""
        print("\n   📊 Comparison:")

        # Response time
        time_diff = enhanced['time'] - basic['time']
        time_pct = (time_diff / basic['time']) * 100 if basic['time'] > 0 else 0
        print(f"   Time: Basic {basic['time']:.3f}s vs Enhanced {enhanced['time']:.3f}s "
              f"({'+' if time_pct > 0 else ''}{time_pct:.1f}%)")

        # Category match
        basic_cat = basic['evaluation']['category_match']
        enhanced_cat = enhanced['evaluation']['category_match']
        print(f"   Category Match: Basic {'✓' if basic_cat else '✗'} vs "
              f"Enhanced {'✓' if enhanced_cat else '✗'}")

        # Keyword coverage
        basic_kw = basic['evaluation']['keyword_coverage']
        enhanced_kw = enhanced['evaluation']['keyword_coverage']
        print(f"   Keyword Coverage: Basic {basic_kw:.1%} vs Enhanced {enhanced_kw:.1%}")

        # Intent detection (enhanced only)
        if 'intent_match' in enhanced['evaluation']:
            intent_match = enhanced['evaluation']['intent_match']
            print(f"   Intent Detection: {'✓' if intent_match else '✗'} "
                  f"(detected: {enhanced['metadata'].get('intent', {}).get('type')})")

        # Quality score (enhanced only)
        if 'avg_quality_score' in enhanced['evaluation']:
            print(f"   Avg Quality Score: {enhanced['evaluation']['avg_quality_score']:.3f}")

    def _generate_summary_report(self, results: Dict):
        """Generate summary report of all tests"""
        print("\n" + "=" * 60)
        print("SUMMARY REPORT")
        print("=" * 60)

        # Calculate aggregate metrics
        for service_name, service_results in results.items():
            print(f"\n📈 {service_name.upper()} Search:")

            # Response time
            times = [r['time'] for r in service_results]
            print(f"   Avg Response Time: {statistics.mean(times):.3f}s")
            print(f"   Max Response Time: {max(times):.3f}s")

            # Category accuracy
            category_matches = sum(
                1 for r in service_results
                if r['evaluation']['category_match']
            )
            print(f"   Category Accuracy: {category_matches}/{len(service_results)} "
                  f"({category_matches/len(service_results)*100:.0f}%)")

            # Keyword coverage
            keyword_coverages = [r['evaluation']['keyword_coverage'] for r in service_results]
            print(f"   Avg Keyword Coverage: {statistics.mean(keyword_coverages):.1%}")

            # Relevance score
            relevance_scores = [r['evaluation']['relevance_score'] for r in service_results]
            print(f"   Avg Relevance Score: {statistics.mean(relevance_scores):.3f}")

            # Enhanced-specific metrics
            if service_name == 'enhanced':
                # Intent accuracy
                intent_matches = sum(
                    1 for r in service_results
                    if r['evaluation'].get('intent_match', False)
                )
                print(f"   Intent Accuracy: {intent_matches}/{len(service_results)} "
                      f"({intent_matches/len(service_results)*100:.0f}%)")

                # Quality scores
                quality_scores = [
                    r['evaluation'].get('avg_quality_score', 0)
                    for r in service_results
                ]
                if any(quality_scores):
                    print(f"   Avg Quality Score: {statistics.mean(quality_scores):.3f}")

        # Overall comparison
        print("\n🏆 OVERALL COMPARISON:")

        basic_scores = []
        enhanced_scores = []

        for i in range(len(self.test_cases)):
            # Calculate composite score
            basic = results['basic'][i]['evaluation']
            enhanced = results['enhanced'][i]['evaluation']

            basic_score = (
                basic['category_match'] * 0.3 +
                basic['keyword_coverage'] * 0.3 +
                basic['relevance_score'] * 0.3 +
                basic['response_time_ok'] * 0.1
            )
            basic_scores.append(basic_score)

            enhanced_score = (
                enhanced['category_match'] * 0.25 +
                enhanced['keyword_coverage'] * 0.25 +
                enhanced['relevance_score'] * 0.25 +
                enhanced.get('intent_match', False) * 0.15 +
                enhanced['response_time_ok'] * 0.1
            )
            enhanced_scores.append(enhanced_score)

        basic_avg = statistics.mean(basic_scores)
        enhanced_avg = statistics.mean(enhanced_scores)
        improvement = ((enhanced_avg - basic_avg) / basic_avg) * 100 if basic_avg > 0 else 0

        print(f"   Basic Search Score: {basic_avg:.3f}")
        print(f"   Enhanced Search Score: {enhanced_avg:.3f}")
        print(f"   Quality Improvement: {improvement:+.1f}%")

        # Save detailed results
        self._save_results(results)

    def _save_results(self, results: Dict):
        """Save detailed test results"""
        output = {
            'timestamp': datetime.now().isoformat(),
            'test_cases': self.test_cases,
            'results': results
        }

        with open('search_quality_results.json', 'w') as f:
            json.dump(output, f, indent=2, default=str)

        print("\n💾 Detailed results saved to: search_quality_results.json")

    async def benchmark_performance(self):
        """Benchmark search performance under load"""
        print("\n" + "=" * 60)
        print("PERFORMANCE BENCHMARK")
        print("=" * 60)

        queries = [
            "authentication error",
            "database optimization",
            "cache implementation",
            "deployment process",
            "bug fix urgent"
        ] * 10  # 50 total queries

        # Test basic search
        print("\n⏱️  Basic Search Performance:")
        basic_times = []
        for query in queries:
            start = time.time()
            await self.basic_search.search(query, limit=5)
            basic_times.append(time.time() - start)

        print(f"   Total time: {sum(basic_times):.2f}s")
        print(f"   Avg per query: {statistics.mean(basic_times):.3f}s")
        print(f"   P95 latency: {sorted(basic_times)[int(len(basic_times)*0.95)]:.3f}s")

        # Test enhanced search
        print("\n⏱️  Enhanced Search Performance:")
        enhanced_times = []
        for query in queries:
            start = time.time()
            await self.enhanced_search.search(
                query,
                limit=5,
                search_mode='smart',
                performance_mode='fast'
            )
            enhanced_times.append(time.time() - start)

        print(f"   Total time: {sum(enhanced_times):.2f}s")
        print(f"   Avg per query: {statistics.mean(enhanced_times):.3f}s")
        print(f"   P95 latency: {sorted(enhanced_times)[int(len(enhanced_times)*0.95)]:.3f}s")

        # Compare
        overhead = ((statistics.mean(enhanced_times) - statistics.mean(basic_times)) /
                   statistics.mean(basic_times)) * 100
        print(f"\n   Performance overhead: {overhead:+.1f}%")

    async def test_edge_cases(self):
        """Test edge cases and error handling"""
        print("\n" + "=" * 60)
        print("EDGE CASE TESTING")
        print("=" * 60)

        edge_cases = [
            "",  # Empty query
            "a",  # Single character
            "the and or",  # Stop words only
            "🔍 emoji search 😊",  # Emojis
            "SELECT * FROM users WHERE",  # SQL injection attempt
            "x" * 1000,  # Very long query
            "品質 テスト",  # Non-English
            "user@example.com",  # Email
            "https://example.com/path",  # URL
            "function_name_with_underscores"  # Technical identifier
        ]

        for query in edge_cases:
            print(f"\n🧪 Testing: '{query[:50]}{'...' if len(query) > 50 else ''}'")
            try:
                # Test enhanced search
                response = await self.enhanced_search.search(
                    query=query,
                    limit=3,
                    search_mode='smart'
                )
                print(f"   ✓ Handled successfully - {len(response.results)} results")

                if hasattr(response, 'metadata') and response.metadata:
                    intent = response.metadata.get('intent', {})
                    print(f"   Intent: {intent.get('type', 'unknown')}, "
                          f"Specificity: {intent.get('specificity', 0):.2f}")

            except Exception as e:
                print(f"   ✗ Error: {str(e)[:100]}")


async def main():
    """Run all search quality tests"""
    tester = SearchQualityTester()

    # Run quality tests
    await tester.test_search_quality()

    # Run performance benchmark
    await tester.benchmark_performance()

    # Run edge case tests
    await tester.test_edge_cases()

    print("\n✅ All tests completed!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Tests interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()