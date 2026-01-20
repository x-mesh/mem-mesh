"""
Search Warmup Service
첫 검색 성능을 개선하기 위한 워밍업 서비스
"""

import asyncio
import logging
from typing import Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class SearchWarmupService:
    """
    검색 워밍업 서비스
    
    첫 검색이 느린 이유:
    1. 임베딩 모델 로딩 (lazy loading)
    2. 데이터베이스 연결 초기화
    3. 캐시 미스
    
    해결 방법:
    1. 서버 시작 시 임베딩 모델 preload
    2. 자주 사용되는 쿼리 미리 캐싱
    3. 데이터베이스 워밍업 쿼리 실행
    """
    
    def __init__(self):
        self.is_warmed_up = False
        self.warmup_start_time: Optional[datetime] = None
        self.warmup_end_time: Optional[datetime] = None
        
        logger.info("SearchWarmupService initialized")
    
    async def warmup(
        self,
        embedding_service,
        db,
        cache_manager
    ) -> dict:
        """
        검색 시스템 워밍업 수행
        
        Args:
            embedding_service: EmbeddingService 인스턴스
            db: Database 인스턴스
            cache_manager: CacheManager 인스턴스
            
        Returns:
            워밍업 결과 딕셔너리
        """
        self.warmup_start_time = datetime.now()
        logger.info("Starting search warmup...")
        
        results = {
            "embedding_preload": False,
            "db_warmup": False,
            "cache_warmup": False,
            "total_time_ms": 0,
            "errors": []
        }
        
        try:
            # 1. 임베딩 모델 preload
            logger.info("Preloading embedding model...")
            await self._preload_embedding_model(embedding_service)
            results["embedding_preload"] = True
            logger.info("✓ Embedding model preloaded")
            
        except Exception as e:
            logger.error(f"Failed to preload embedding model: {e}")
            results["errors"].append(f"Embedding preload: {str(e)}")
        
        try:
            # 2. 데이터베이스 워밍업
            logger.info("Warming up database...")
            await self._warmup_database(db)
            results["db_warmup"] = True
            logger.info("✓ Database warmed up")
            
        except Exception as e:
            logger.error(f"Failed to warmup database: {e}")
            results["errors"].append(f"DB warmup: {str(e)}")
        
        try:
            # 3. 캐시 워밍업 (자주 사용되는 쿼리)
            logger.info("Warming up cache...")
            await self._warmup_cache(embedding_service, cache_manager)
            results["cache_warmup"] = True
            logger.info("✓ Cache warmed up")
            
        except Exception as e:
            logger.error(f"Failed to warmup cache: {e}")
            results["errors"].append(f"Cache warmup: {str(e)}")
        
        self.warmup_end_time = datetime.now()
        self.is_warmed_up = True
        
        # 총 시간 계산
        total_time = (self.warmup_end_time - self.warmup_start_time).total_seconds()
        results["total_time_ms"] = int(total_time * 1000)
        
        logger.info(f"Search warmup completed in {results['total_time_ms']}ms")
        
        return results
    
    async def _preload_embedding_model(self, embedding_service):
        """임베딩 모델 preload"""
        # 더미 텍스트로 모델 로딩
        dummy_texts = [
            "search",
            "검색",
            "quality",
            "품질"
        ]
        
        for text in dummy_texts:
            _ = embedding_service.embed(text)
            await asyncio.sleep(0.01)  # 약간의 딜레이
    
    async def _warmup_database(self, db):
        """데이터베이스 워밍업"""
        # 간단한 쿼리로 연결 확인
        warmup_queries = [
            "SELECT COUNT(*) FROM memories",
            "SELECT COUNT(DISTINCT project_id) FROM memories",
            "SELECT COUNT(DISTINCT category) FROM memories",
        ]
        
        for query in warmup_queries:
            await db.fetchone(query, ())
            await asyncio.sleep(0.01)
    
    async def _warmup_cache(self, embedding_service, cache_manager):
        """캐시 워밍업 - 자주 사용되는 쿼리 미리 캐싱"""
        # 자주 사용되는 검색어 목록
        common_queries = [
            "search",
            "검색",
            "quality",
            "품질",
            "optimization",
            "최적화",
            "test",
            "테스트",
            "bug",
            "버그",
            "feature",
            "기능",
        ]
        
        for query in common_queries:
            try:
                # 임베딩 생성 및 캐싱
                embedding = embedding_service.embed(query)
                await cache_manager.cache_embedding(query, embedding)
                await asyncio.sleep(0.01)
            except Exception as e:
                logger.warning(f"Failed to cache query '{query}': {e}")
    
    def get_warmup_status(self) -> dict:
        """워밍업 상태 반환"""
        if not self.is_warmed_up:
            return {
                "is_warmed_up": False,
                "message": "Not warmed up yet"
            }
        
        warmup_time = (
            self.warmup_end_time - self.warmup_start_time
        ).total_seconds() if self.warmup_start_time and self.warmup_end_time else 0
        
        return {
            "is_warmed_up": True,
            "warmup_time_ms": int(warmup_time * 1000),
            "warmup_start": self.warmup_start_time.isoformat() if self.warmup_start_time else None,
            "warmup_end": self.warmup_end_time.isoformat() if self.warmup_end_time else None
        }


# 전역 인스턴스
_warmup_service: Optional[SearchWarmupService] = None


def get_warmup_service() -> SearchWarmupService:
    """전역 SearchWarmupService 인스턴스 반환"""
    global _warmup_service
    if _warmup_service is None:
        _warmup_service = SearchWarmupService()
    return _warmup_service
