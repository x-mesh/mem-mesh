
import asyncio
import os
import logging
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.unified_search import UnifiedSearchService
from app.core.services.cache_manager import reset_cache_manager
from app.core.config import Settings

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SearchVerifier")

async def verify_features():
    print("\n" + "="*60)
    print("🔍 UnifiedSearchService 기능 검증 시작")
    print("="*60)

    # 캐시 초기화
    reset_cache_manager()

    # 1. 초기화
    settings = Settings()
    db = Database(settings.database_path)
    embedding_service = EmbeddingService()
    
    # DB 연결
    if hasattr(db, 'connect'):
        await db.connect()
    elif hasattr(db, '_connect'):
        await db._connect()
        
    print(f"✅ 데이터베이스 연결됨: {settings.database_path}")
    print(f"✅ 임베딩 서비스 초기화됨: {embedding_service.model_name}")

    query = "dashboard" # 테스트 쿼리
    print(f"\n🧪 테스트 쿼리: '{query}'")

    # 2. 각 기능별 테스트 케이스 정의
    test_cases = [
        {
            "name": "모든 기능 끄기 (Baseline)",
            "config": {
                "enable_quality_features": False,
                "enable_korean_optimization": False,
                "enable_noise_filter": False,
                "enable_score_normalization": False
            }
        },
        {
            "name": "Quality Features (의도 분석) 활성화",
            "config": {
                "enable_quality_features": True,
                "enable_korean_optimization": False,
                "enable_noise_filter": False,
                "enable_score_normalization": False
            }
        },
        {
            "name": "Noise Filter 활성화",
            "config": {
                "enable_quality_features": False,
                "enable_korean_optimization": False,
                "enable_noise_filter": True,
                "enable_score_normalization": False
            }
        },
        {
            "name": "Score Normalization 활성화",
            "config": {
                "enable_quality_features": False,
                "enable_korean_optimization": False,
                "enable_noise_filter": False,
                "enable_score_normalization": True
            }
        },
         {
            "name": "Query Expansion (한국어 최적화) 활성화",
            "config": {
                "enable_quality_features": False,
                "enable_korean_optimization": True,
                "enable_noise_filter": False,
                "enable_score_normalization": False
            }
        }
    ]

    results = {}

    # 3. 테스트 실행
    for case in test_cases:
        print(f"\n>> 테스트 케이스 실행: {case['name']}")
        
        service = UnifiedSearchService(
            db=db,
            embedding_service=embedding_service,
            cache_search_ttl=0,  # 캐시 비활성화
            **case['config']
        )
        
        try:
            response = await service.search(query=query, limit=10)
            
            results[case['name']] = {
                "count": len(response.results),
                "top_score": response.results[0].similarity_score if response.results else 0.0,
                "top_content": response.results[0].content[:50] if response.results else "N/A"
            }
            
            print(f"   결과 개수: {len(response.results)}")
            if response.results:
                print(f"   Top 1 점수: {response.results[0].similarity_score:.4f}")
                print(f"   Top 1 내용: {response.results[0].content[:50]}...")
            else:
                print("   결과 없음")

            # 추가 검증: Intent Analysis
            if case['config']['enable_quality_features'] and service.intent_analyzer:
                intent = service.intent_analyzer.analyze(query)
                print(f"   [검증] 의도 분석 결과: {intent.intent_type}, urgency={intent.urgency}")

            # 추가 검증: Query Expansion
            if case['config']['enable_korean_optimization']:
                expanded = service._expand_query(query)
                print(f"   [검증] 확장된 쿼리: '{expanded}'")

        except Exception as e:
            print(f"   ❌ 에러 발생: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "="*60)
    print("📊 종합 결과 요약")
    print("="*60)
    
    baseline = results.get("모든 기능 끄기 (Baseline)")
    
    for name, res in results.items():
        diff_msg = ""
        if baseline and name != "모든 기능 끄기 (Baseline)":
            count_diff = res['count'] - baseline['count']
            score_diff = res['top_score'] - baseline['top_score']
            diff_msg = f"(개수: {count_diff:+d}, 점수: {score_diff:+.4f})"
        
        print(f"[{name}]")
        print(f"  Count: {res['count']}, Top Score: {res['top_score']:.4f} {diff_msg}")
        print(f"  Content: {res['top_content']}")
        print("-" * 30)

if __name__ == "__main__":
    asyncio.run(verify_features())
