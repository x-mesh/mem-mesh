
import asyncio
import os
import logging
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.unified_search import UnifiedSearchService
from app.core.services.cache_manager import reset_cache_manager
from app.core.config import Settings

# 로깅을 좀 더 조용하게 설정
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.basicConfig(level=logging.ERROR) # 기본 ERROR로 하고
logger = logging.getLogger("SearchVerifier")
logger.setLevel(logging.INFO) # 검증기만 INFO

async def verify_features():
    print("\n" + "="*60)
    print("🔍 RRF 하이브리드 검색 & 스마트 쿼리 확장 검증")
    print("="*60)

    # 캐시 초기화
    reset_cache_manager()

    # 초기화
    settings = Settings()
    db = Database(settings.database_path)
    if hasattr(db, 'connect'):
        await db.connect()
    
    # 임베딩 서비스 (preload=True 하면 로딩 로그 뜸)
    print("Loading embedding model...")
    embedding_service = EmbeddingService(preload=True)
    
    # 테스트할 쿼리들
    # 1. dashboard: 영어 -> 번역 안 됨 (스마트 확장 체크) -> RRF로 텍스트 매칭 부스팅
    # 2. 버그 수정: 한글 -> 번역 됨 -> 의미 검색 강화
    # 3. access log: 영어 -> 번역 안 됨 -> RRF 부스팅
    queries = ["dashboard", "버그 수정", "Access Log"]
    
    # 서비스 인스턴스 생성 (한 번만)
    service = UnifiedSearchService(
        db=db,
        embedding_service=embedding_service,
        cache_search_ttl=0,
        enable_quality_features=True,
        enable_korean_optimization=True,
        enable_noise_filter=False, # 결과 확인을 위해 노이즈 필터는 끔 (RRF 점수 분포 확인용)
        enable_score_normalization=True
    )

    for query in queries:
        print(f"\n" + "-"*60)
        print(f"🧪 Query: '{query}'")
        print("-"*60)
        
        try:
            # 검색 실행
            response = await service.search(query=query, limit=3)
            
            print(f"   결과 개수: {len(response.results)}")
            for i, res in enumerate(response.results):
                title = res.content.split('\n')[0][:50]
                print(f"   [{i+1}] Score: {res.similarity_score:.4f} | {title}...")
            
            # 쿼리 확장 로직 검증 출력
            is_korean = service._is_korean(query)
            expanded = service._expand_query(query)
            print(f"   [검증] 한국어 감지: {is_korean}")
            print(f"   [검증] 최종 쿼리: '{expanded}'")
            
            if not is_korean and expanded == query:
                print("   ✅ 스마트 확장 성공 (영어 쿼리 보존됨)")
            elif is_korean and len(expanded) > len(query):
                print("   ✅ 스마트 확장 성공 (한국어 쿼리 번역됨)")

        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_features())
