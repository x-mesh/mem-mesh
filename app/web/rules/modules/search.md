# Search Rules — 검색 최적화

mem-mesh 검색 품질을 높이는 쿼리 작성법과 파라미터 가이드.

---

## 쿼리 작성법

### ✅ 권장
- **구문 사용**: `"token optimization strategy"`, `"검색 품질 최적화"`
- **구체적 표현**: `"E5 모델 query prefix 적용"`, `"FTS 한국어 복합어 분해"`

### ❌ 비권장
- 단일 단어: `"token"`, `"검색"` — 노이즈 많음
- 모호한 표현: `"문제"`, `"수정"`

---

## 한국어 검색

- **복합어**: 4음절 이상 한국어 복합어는 자동 n-gram 분해
- 예: "토큰최적화" → "토큰", "최적화" OR 검색
- 한영 혼합: `"RRF 가중치 설정"` — 벡터+FTS 하이브리드로 처리

---

## 검색 엔진 동작 (P1~P6 최적화 반영)

- **하이브리드**: 벡터(의미) + FTS(키워드) 동시 검색, RRF로 결합
- **E5 모델**: query/passage prefix 자동 적용 (E5 계열 감지 시)
- **Sigmoid 정규화**: 점수 분포 0.3~0.7에 맞게 조정
- **RRF 가중치**: FTS 키워드 매칭 우대 (vector_weight=1.0, text_weight=1.2)

---

## 파라미터

| 파라미터 | 기본값 | 용도 |
|----------|--------|------|
| `project_id` | - | 프로젝트 필터 (항상 지정 권장) |
| `category` | - | task, bug, decision 등 |
| `limit` | 5 | 1~20, 3~5 권장 |
| `recency_weight` | 0.0 | 0.2~0.5 시 최근 메모리 우선 |
| `response_format` | standard | minimal/compact/standard/full |

---

## 예시

```
# 프로젝트 내 구체적 검색
search(query="임베딩 모델 마이그레이션", project_id="mem-mesh", limit=5)

# 최근 결정만
search(query="", category="decision", project_id="my-app", limit=5)

# 최근성 가중
search(query="버그 수정", project_id="my-app", recency_weight=0.3)

# 토큰 절약 (ID+점수만)
search(query="...", project_id="...", response_format="minimal")
```
