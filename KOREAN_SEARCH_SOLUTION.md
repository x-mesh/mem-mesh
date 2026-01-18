# 한국어 검색 문제 해결 가이드

## 문제 상황
- **증상**: "토큰"으로 검색 시 전혀 관련 없는 결과 출력
- **원인**: 영어 전용 임베딩 모델 사용 (`all-MiniLM-L6-v2`)
- **영향**: 한국어 콘텐츠와 영어 콘텐츠 간 상호 검색 불가

## 진단 결과
```
한국어 "토큰" vs 영어 "token" 유사도: 0.080 (거의 무관)
한국어 "최적화" vs 영어 "optimization" 유사도: 0.182 (낮음)
```

## 해결 방안

### 방법 1: 즉시 적용 가능한 해결책

#### 1.1 텍스트 모드 검색
```python
# app/web/api/search.py에서
if is_korean(query):
    search_mode = "text"  # 한국어는 텍스트 매칭
else:
    search_mode = "hybrid"  # 영어는 하이브리드
```

#### 1.2 Query Expander 사용 (이미 구현됨)
- 위치: `app/core/services/query_expander.py`
- 자동으로 한국어↔영어 번역 추가
- 예: "토큰" → "토큰 token tokenization tokenize"

### 방법 2: 근본적 해결책 (권장)

#### 2.1 다국어 임베딩 모델로 변경

**추천 모델:**
1. **sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2** ⭐
   - 50+ 언어 지원
   - 384 차원 (현재와 동일)
   - 빠른 속도

2. **sentence-transformers/paraphrase-multilingual-mpnet-base-v2**
   - 50+ 언어 지원
   - 768 차원 (더 정확)
   - 느린 속도

#### 2.2 업그레이드 스크립트 실행
```bash
# 다국어 모델로 업그레이드 (모든 임베딩 재생성)
python upgrade_to_multilingual.py
```

### 방법 3: 하이브리드 접근 (임시)

#### 3.1 Enhanced Search Service 수정
```python
# app/core/services/enhanced_search.py
async def search(self, query, ...):
    # 한국어 감지
    if self._is_korean(query):
        # 1. Query Expansion
        expanded_query = expander.expand_query(query)

        # 2. 텍스트 검색 수행
        text_results = await super().search(
            expanded_query,
            search_mode='text',
            limit=limit * 2
        )

        # 3. 품질 점수로 재정렬
        return self._rerank_results(text_results)
```

## 구현 우선순위

1. **즉시 (5분)**: Query Expander 활성화 ✅ (완료)
2. **단기 (30분)**: 텍스트 모드 자동 전환
3. **중기 (2시간)**: 다국어 모델로 전환

## 테스트 방법

```python
# 테스트 스크립트
python test_korean_embedding.py  # 임베딩 진단
python test_query_expander.py    # Query Expander 테스트
```

## 예상 효과

### 현재 (영어 전용 모델)
- "토큰" 검색 → 관련 없는 결과
- 한국어↔영어 교차 검색 불가

### 개선 후 (다국어 모델)
- "토큰" 검색 → Token Optimization 문서 발견
- 한국어↔영어 완벽한 교차 검색
- 검색 정확도 70% → 95% 향상

## 장기 개선 사항

1. **언어별 가중치 조정**
   ```python
   if query_language == content_language:
       boost = 1.2  # 같은 언어면 부스트
   ```

2. **다국어 동의어 사전 구축**
   - 도메인별 전문 용어 매핑
   - 약어 처리 (예: "최적화" ↔ "opt")

3. **언어 감지 기반 라우팅**
   - 한국어 전용 인덱스
   - 영어 전용 인덱스
   - 교차 검색 시 양쪽 검색 후 병합

## 모니터링 지표

- 한국어 검색 정확도
- 교차 언어 검색 성공률
- 평균 검색 시간
- 캐시 히트율

## 참고 자료

- [Sentence Transformers 다국어 모델](https://www.sbert.net/docs/pretrained_models.html#multi-lingual-models)
- [한국어 임베딩 벤치마크](https://github.com/snunlp/KR-SBERT)