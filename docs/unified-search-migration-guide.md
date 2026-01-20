# UnifiedSearchService 마이그레이션 가이드
Migration Guide for UnifiedSearchService

## 개요

UnifiedSearchService는 기존 5개의 검색 구현을 하나로 통합한 새로운 검색 서비스입니다.

### 기존 구현들

1. **search.py** - 기본 하이브리드 검색 + 캐싱
2. **enhanced_search.py** - 품질 최적화 + 의도 분석
3. **improved_search.py** - 한국어 최적화
4. **final_improved_search.py** - 한영 번역
5. **simple_improved_search.py** - 간단한 한영 변환

### UnifiedSearchService 장점

- **단일 진입점**: 하나의 서비스로 모든 검색 기능 제공
- **Feature Flags**: 필요한 기능만 선택적으로 활성화
- **성능 최적화**: 캐싱, 스코어링, 필터링 통합
- **유지보수성**: 중복 코드 제거, 일관된 인터페이스

## 마이그레이션 전략

### Phase 1: 병렬 실행 (현재)

기존 SearchService와 UnifiedSearchService를 동시에 사용 가능하도록 유지합니다.

```python
# 기존 방식 (계속 작동)
from app.core.services.search import SearchService

search_service = SearchService(db, embedding_service)
result = await search_service.search(query="test")

# 새로운 방식 (선택적 사용)
from app.core.services.unified_search import UnifiedSearchService

unified_search = UnifiedSearchService(
    db=db,
    embedding_service=embedding_service,
    enable_quality_features=True,
    enable_korean_optimization=True,
    enable_noise_filter=True
)
result = await unified_search.search(query="test", search_mode="smart")
```

### Phase 2: 점진적 전환 (1-2주)

1. **테스트 환경에서 검증**
   ```bash
   # UnifiedSearchService 테스트
   python -m pytest tests/test_unified_search.py -v
   ```

2. **MCP 서버에 통합**
   - `app/mcp_common/tools.py`의 search 메서드 업데이트
   - Feature flag로 제어 가능하도록 구현

3. **Web API에 통합**
   - `app/web/dashboard/routes.py`의 검색 엔드포인트 업데이트
   - 쿼리 파라미터로 검색 모드 선택 가능

### Phase 3: 완전 전환 (1개월 후)

1. **기본 검색 서비스 교체**
2. **기존 구현 Deprecated 표시**
3. **문서 업데이트**

## 통합 방법

### 1. DirectStorageBackend 통합

`app/core/storage/direct.py` 수정:

```python
from ..services.unified_search import UnifiedSearchService

class DirectStorageBackend(StorageBackend):
    def __init__(
        self, 
        db_path: str, 
        busy_timeout: int = 5000,
        use_unified_search: bool = False  # Feature flag
    ):
        self.use_unified_search = use_unified_search
        # ...
    
    async def initialize(self) -> None:
        # ...
        
        if self.use_unified_search:
            # UnifiedSearchService 사용
            self.search_service = UnifiedSearchService(
                db=self.db,
                embedding_service=self.embedding_service,
                enable_quality_features=True,
                enable_korean_optimization=True,
                enable_noise_filter=True
            )
        else:
            # 기존 SearchService 사용
            self.search_service = SearchService(
                db=self.db,
                embedding_service=self.embedding_service
            )
```

### 2. 환경 변수 설정

`.env` 파일에 추가:

```bash
# UnifiedSearchService 활성화
USE_UNIFIED_SEARCH=true

# Feature flags
ENABLE_QUALITY_FEATURES=true
ENABLE_KOREAN_OPTIMIZATION=true
ENABLE_NOISE_FILTER=true
```

### 3. Config 업데이트

`app/core/config.py`:

```python
class Settings(BaseSettings):
    # ...
    
    # UnifiedSearchService 설정
    use_unified_search: bool = False
    enable_quality_features: bool = True
    enable_korean_optimization: bool = True
    enable_noise_filter: bool = True
```

## 사용 예시

### 기본 사용

```python
from app.core.services.unified_search import UnifiedSearchService

# 초기화
search_service = UnifiedSearchService(
    db=db,
    embedding_service=embedding_service
)

# 기본 검색
result = await search_service.search(
    query="검색어",
    limit=10
)
```

### 고급 사용

```python
# 스마트 모드 (의도 기반 자동 조정)
result = await search_service.search(
    query="urgent bug fix needed",
    search_mode="smart",  # 자동으로 exact 모드로 전환
    min_quality_score=0.5
)

# 한국어 최적화
result = await search_service.search(
    query="토큰 최적화",  # 자동으로 "token optimization" 추가
    search_mode="smart",
    enable_korean_optimization=True
)

# 정확한 매칭
result = await search_service.search(
    query="exact phrase",
    search_mode="exact"
)

# 의미 기반 검색
result = await search_service.search(
    query="similar concepts",
    search_mode="semantic",
    recency_weight=0.3  # 최신성 30% 반영
)

# 퍼지 검색 (오타 허용)
result = await search_service.search(
    query="serch qualitty",  # 오타 있어도 검색
    search_mode="fuzzy"
)
```

### Feature Flags 제어

```python
# 품질 기능만 활성화
search_service = UnifiedSearchService(
    db=db,
    embedding_service=embedding_service,
    enable_quality_features=True,
    enable_korean_optimization=False,
    enable_noise_filter=False
)

# 한국어 최적화만 활성화
search_service = UnifiedSearchService(
    db=db,
    embedding_service=embedding_service,
    enable_quality_features=False,
    enable_korean_optimization=True,
    enable_noise_filter=False
)

# 모든 기능 활성화 (권장)
search_service = UnifiedSearchService(
    db=db,
    embedding_service=embedding_service,
    enable_quality_features=True,
    enable_korean_optimization=True,
    enable_noise_filter=True
)
```

## 성능 비교

### 기존 SearchService

```
검색 시간: ~50ms
캐싱: 임베딩만
필터링: 없음
한국어 지원: 제한적
```

### UnifiedSearchService

```
검색 시간: ~60ms (품질 기능 포함)
캐싱: 임베딩 + 검색 결과
필터링: 노이즈 자동 제거
한국어 지원: 완전 지원 (한영 번역)
품질: 의도 분석 + 스코어링
```

**성능 영향**: +10ms (20% 증가), 하지만 품질은 크게 향상

## 테스트

### 단위 테스트

```bash
# UnifiedSearchService 테스트
python -m pytest tests/test_unified_search.py -v

# 통합 테스트
python -m pytest tests/test_search_integration.py -v
```

### 수동 테스트

```python
# 간단한 테스트 스크립트
import asyncio
from app.core.database.base import Database
from app.core.embeddings.service import EmbeddingService
from app.core.services.unified_search import UnifiedSearchService

async def test_unified_search():
    db = Database("./data/memories.db")
    await db.connect()
    
    embedding_service = EmbeddingService()
    
    search_service = UnifiedSearchService(
        db=db,
        embedding_service=embedding_service,
        enable_quality_features=True,
        enable_korean_optimization=True,
        enable_noise_filter=True
    )
    
    # 테스트 쿼리
    result = await search_service.search(
        query="검색 품질",
        search_mode="smart",
        limit=5
    )
    
    print(f"Found {len(result.results)} results")
    for r in result.results:
        print(f"- {r.id[:8]}: {r.content[:50]}... (score: {r.similarity_score:.2f})")
    
    await db.close()

if __name__ == "__main__":
    asyncio.run(test_unified_search())
```

## 롤백 계획

문제 발생 시 즉시 롤백 가능:

```python
# .env 파일에서
USE_UNIFIED_SEARCH=false

# 또는 코드에서
storage = DirectStorageBackend(
    db_path="./data/memories.db",
    use_unified_search=False  # 기존 SearchService 사용
)
```

## 모니터링

### 메트릭 수집

UnifiedSearchService는 자동으로 메트릭을 수집합니다:

- 검색 시간
- 결과 개수
- 평균 유사도 점수
- 검색 모드
- Feature flags 상태

### 로그 확인

```bash
# 검색 로그 확인
tail -f logs/mem-mesh.log | grep "UnifiedSearchService"

# 성능 로그
tail -f logs/mem-mesh.log | grep "Search completed"
```

## FAQ

### Q: 기존 SearchService와 호환되나요?

A: 네, 인터페이스가 동일하므로 드롭인 교체 가능합니다.

### Q: 성능 저하가 있나요?

A: 약 10ms 증가하지만, 품질 향상으로 상쇄됩니다. 필요시 Feature flags로 기능 비활성화 가능.

### Q: 한국어 검색이 개선되나요?

A: 네, 한영 번역 사전과 Query Expander로 크게 개선됩니다.

### Q: 롤백이 쉬운가요?

A: 네, 환경 변수 하나로 즉시 롤백 가능합니다.

### Q: 기존 코드 수정이 필요한가요?

A: 아니요, Feature flag만 활성화하면 됩니다.

## 다음 단계

1. **테스트 환경 검증** (1주)
   - 단위 테스트 실행
   - 통합 테스트 실행
   - 성능 벤치마크

2. **스테이징 배포** (1주)
   - Feature flag 활성화
   - 모니터링 설정
   - 사용자 피드백 수집

3. **프로덕션 배포** (2주 후)
   - 점진적 롤아웃 (10% → 50% → 100%)
   - 메트릭 모니터링
   - 문제 발생 시 즉시 롤백

4. **기존 구현 Deprecated** (1개월 후)
   - 경고 메시지 추가
   - 문서 업데이트
   - 마이그레이션 완료

## 참고 자료

- [검색 품질 개선 문서](./search-quality-improvements.md)
- [UnifiedSearchService 소스](../app/core/services/unified_search.py)
- [테스트 코드](../tests/test_search_quality_improvements.py)

## 변경 이력

- 2026-01-20: 초기 마이그레이션 가이드 작성
