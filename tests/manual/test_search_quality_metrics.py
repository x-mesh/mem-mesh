"""
검색 품질 메트릭 API 테스트

새로 추가된 3개의 API 엔드포인트를 테스트합니다:
- GET /api/monitoring/search/quality-stats
- GET /api/monitoring/search/project-stats
- GET /api/monitoring/cache/performance-stats
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.database.base import Database
from app.core.services.metrics_collector import MetricsCollector


async def test_search_quality_stats():
    """검색 품질 통계 테스트"""
    print("\n=== 검색 품질 통계 테스트 ===")
    
    db = Database("./data/memories.db")
    await db.connect()
    
    try:
        collector = MetricsCollector(database=db, hash_queries=False)
        
        # 24시간 통계 조회
        stats = await collector.get_search_quality_stats(hours=24)
        
        print(f"\n📊 기간: {stats['period']['hours']}시간")
        print(f"   시작: {stats['period']['start_time']}")
        print(f"   종료: {stats['period']['end_time']}")
        
        print("\n📈 요약:")
        summary = stats['summary']
        print(f"   총 검색: {summary['total_searches']:,}")
        print(f"   평균 결과 수: {summary['avg_results_per_search']:.2f}")
        print(f"   평균 유사도: {summary['avg_similarity_score']:.3f}")
        print(f"   평균 최고 점수: {summary['avg_top_score']:.3f}")
        print(f"   평균 응답시간: {summary['avg_response_time_ms']:.1f}ms")
        print(f"   Zero-result 비율: {summary['zero_result_rate']:.2f}%")
        print(f"   낮은 점수 비율: {summary['low_score_rate']:.2f}%")
        
        print("\n🔍 소스별 통계:")
        for source in stats['by_source']:
            print(f"   {source['source']}: {source['count']}회, "
                  f"평균 {source['avg_results']:.2f}개 결과, "
                  f"{source['avg_response_time_ms']:.1f}ms")
        
        print(f"\n📉 시간대별 트렌드 (최근 {len(stats['trend'])}개):")
        for trend in stats['trend'][:5]:  # 최근 5개만 표시
            print(f"   {trend['hour']}: {trend['search_count']}회, "
                  f"평균 {trend['avg_results']:.2f}개 결과, "
                  f"점수 {trend['avg_score']:.3f}")
        
        if stats['popular_queries']:
            print("\n🔥 인기 검색어 Top 5:")
            for query in stats['popular_queries'][:5]:
                print(f"   \"{query['query']}\": {query['count']}회, "
                      f"평균 {query['avg_results']:.2f}개 결과")
        else:
            print("\n🔥 인기 검색어: 쿼리 해싱 활성화됨")
        
        print("\n✅ 검색 품질 통계 테스트 성공")
        
    finally:
        await db.close()


async def test_project_search_stats():
    """프로젝트별 검색 통계 테스트"""
    print("\n=== 프로젝트별 검색 통계 테스트 ===")
    
    db = Database("./data/memories.db")
    await db.connect()
    
    try:
        collector = MetricsCollector(database=db)
        
        # 24시간 통계 조회
        stats = await collector.get_project_search_stats(hours=24)
        
        print(f"\n🗂️ 프로젝트별 통계 ({len(stats)}개 프로젝트):")
        for project in stats[:10]:  # 상위 10개만 표시
            print(f"\n   프로젝트: {project['project_id']}")
            print(f"   - 검색 수: {project['search_count']:,}")
            print(f"   - 평균 결과: {project['avg_results']:.2f}")
            print(f"   - 평균 점수: {project['avg_score']:.3f}")
            print(f"   - 평균 응답시간: {project['avg_response_time_ms']:.1f}ms")
            print(f"   - Zero-result 비율: {project['zero_result_rate']:.2f}%")
        
        if len(stats) > 10:
            print(f"\n   ... 외 {len(stats) - 10}개 프로젝트")
        
        print("\n✅ 프로젝트별 검색 통계 테스트 성공")
        
    finally:
        await db.close()


async def test_cache_performance_stats():
    """캐시 성능 통계 테스트"""
    print("\n=== 캐시 성능 통계 테스트 ===")
    
    db = Database("./data/memories.db")
    await db.connect()
    
    try:
        collector = MetricsCollector(database=db)
        
        # 24시간 통계 조회
        stats = await collector.get_cache_performance_stats(hours=24)
        
        print(f"\n📊 기간: {stats['period']['hours']}시간")
        print(f"   시작: {stats['period']['start_time']}")
        print(f"   종료: {stats['period']['end_time']}")
        
        print("\n💾 임베딩 캐시 성능:")
        cache = stats['embedding_cache']
        print(f"   총 작업: {cache['total_operations']:,}")
        print(f"   캐시 히트: {cache['cache_hits']:,}")
        print(f"   캐시 미스: {cache['cache_misses']:,}")
        print(f"   히트율: {cache['hit_rate']:.2f}%")
        print(f"   평균 시간: {cache['avg_time_ms']:.1f}ms")
        
        # 캐시 효율성 평가
        if cache['hit_rate'] >= 80:
            print("   ✅ 캐시 효율성: 매우 좋음")
        elif cache['hit_rate'] >= 60:
            print("   ⚠️ 캐시 효율성: 보통")
        else:
            print("   ❌ 캐시 효율성: 개선 필요")
        
        print("\n✅ 캐시 성능 통계 테스트 성공")
        
    finally:
        await db.close()


async def test_with_sample_data():
    """샘플 데이터로 메트릭 수집 및 조회 테스트"""
    print("\n=== 샘플 데이터 테스트 ===")
    
    db = Database("./data/memories.db")
    await db.connect()
    
    try:
        collector = MetricsCollector(database=db, hash_queries=False)
        await collector.start()
        
        # 샘플 검색 메트릭 수집
        print("\n📝 샘플 검색 메트릭 수집 중...")
        for i in range(5):
            await collector.collect_search_metric(
                query=f"테스트 쿼리 {i+1}",
                result_count=10 - i,
                response_time_ms=100 + i * 20,
                avg_similarity=0.8 - i * 0.05,
                top_similarity=0.9 - i * 0.05,
                project_id="test-project",
                category="task",
                source="test"
            )
        
        # 샘플 임베딩 메트릭 수집
        print("📝 샘플 임베딩 메트릭 수집 중...")
        for i in range(3):
            await collector.collect_embedding_metric(
                operation="generate",
                count=1,
                total_time_ms=50 + i * 10,
                cache_hit=i % 2 == 0,
                model_name="test-model"
            )
        
        # 버퍼 플러시
        await collector.flush()
        print("✅ 샘플 데이터 수집 완료")
        
        # 통계 조회
        print("\n📊 수집된 데이터 통계 조회...")
        quality_stats = await collector.get_search_quality_stats(hours=1)
        print(f"   최근 1시간 검색: {quality_stats['summary']['total_searches']}회")
        
        cache_stats = await collector.get_cache_performance_stats(hours=1)
        print(f"   최근 1시간 임베딩 작업: {cache_stats['embedding_cache']['total_operations']}회")
        
        await collector.stop()
        print("\n✅ 샘플 데이터 테스트 성공")
        
    finally:
        await db.close()


async def main():
    """모든 테스트 실행"""
    print("=" * 60)
    print("검색 품질 메트릭 API 테스트")
    print("=" * 60)
    
    try:
        # 실제 데이터로 테스트
        await test_search_quality_stats()
        await test_project_search_stats()
        await test_cache_performance_stats()
        
        # 샘플 데이터로 테스트
        await test_with_sample_data()
        
        print("\n" + "=" * 60)
        print("✅ 모든 테스트 성공!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
