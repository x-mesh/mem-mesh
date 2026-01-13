# 임베딩 모델 테스트 가이드

mem-mesh의 검색 품질을 향상시키기 위한 임베딩 모델 테스트 및 최적화 가이드입니다.

## 개요

mem-mesh는 다양한 sentence-transformers 모델을 지원하며, 각 모델은 서로 다른 특성을 가집니다:

- **소형 모델**: 빠른 속도, 낮은 메모리 사용량, 적당한 정확도
- **중형 모델**: 균형잡힌 성능과 정확도
- **대형 모델**: 높은 정확도, 느린 속도, 높은 메모리 사용량

## 지원되는 모델

### 소형 모델 (384차원)
- `all-MiniLM-L6-v2` (기본값)
- `paraphrase-MiniLM-L6-v2`
- `multi-qa-MiniLM-L6-cos-v1`
- `intfloat/multilingual-e5-small`

### 중형 모델 (512-768차원)
- `all-MiniLM-L12-v2`
- `distiluse-base-multilingual-cased-v2`
- `intfloat/multilingual-e5-base`

### 대형 모델 (768-1024차원)
- `all-mpnet-base-v2`
- `multi-qa-mpnet-base-cos-v1`
- `intfloat/multilingual-e5-large`

## 테스트 도구 사용법

### 1. 종합 벤치마크 실행

모든 모델의 성능을 자동으로 비교 평가합니다.

```bash
# 모든 기본 모델 테스트
python scripts/benchmark_embedding_models.py

# 특정 모델들만 테스트
python scripts/benchmark_embedding_models.py --models all-MiniLM-L6-v2 all-mpnet-base-v2

# 결과를 특정 파일에 저장
python scripts/benchmark_embedding_models.py --output my_benchmark.json

# 시각화 결과를 특정 디렉토리에 저장
python scripts/benchmark_embedding_models.py --plot-dir my_plots
```

**출력 결과:**
- 임베딩 생성 시간
- 검색 시간
- 메모리 사용량
- 검색 정확도
- 성능 비교 차트

### 2. A/B 테스트 실행

두 모델을 직접 비교하여 사용자 선호도를 측정합니다.

```bash
# 두 모델 비교
python scripts/ab_test_embeddings.py all-MiniLM-L6-v2 all-mpnet-base-v2

# 사용자 정의 쿼리로 테스트
python scripts/ab_test_embeddings.py model_a model_b --queries "버그 수정" "성능 최적화" "API 구현"

# 결과 저장
python scripts/ab_test_embeddings.py model_a model_b --output ab_results.json
```

**대화형 프로세스:**
1. 각 쿼리에 대해 두 모델의 검색 결과 표시
2. 사용자가 더 나은 결과 선택
3. 통계적 분석 및 추천 제공

### 3. 검색 품질 정량 평가

다양한 메트릭으로 검색 품질을 객관적으로 측정합니다.

```bash
# 현재 모델 평가
python scripts/evaluate_search_quality.py

# 여러 모델 비교 평가
python scripts/evaluate_search_quality.py --models all-MiniLM-L6-v2 all-mpnet-base-v2 intfloat/multilingual-e5-base

# 결과를 파일로 저장
python scripts/evaluate_search_quality.py --models model1 model2 --output quality_report.txt
```

**평가 메트릭:**
- **Precision@K**: 상위 K개 결과 중 관련 항목 비율
- **Recall@K**: 전체 관련 항목 중 상위 K개에서 찾은 비율
- **NDCG@K**: 순위를 고려한 정규화된 할인 누적 이득
- **MRR**: 평균 역순위 (첫 번째 관련 결과의 순위)
- **MAP**: 평균 정밀도
- **다양성**: 결과의 카테고리 다양성
- **커버리지**: 전체 카테고리 대비 검색된 카테고리 비율

### 4. 대화형 검색 도구

실시간으로 다양한 모델을 전환하며 검색 결과를 확인할 수 있는 대화형 도구입니다.

```bash
# 기본 실행
python scripts/interactive_search.py

# 상세 로그와 함께 실행
python scripts/interactive_search.py -v

# 특정 모델로 시작
python scripts/interactive_search.py --model all-mpnet-base-v2

# 기본 검색 결과 개수 설정
python scripts/interactive_search.py --limit 10
```

**대화형 명령어:**
- `models` - 사용 가능한 모델 목록 표시
- `model <name>` - 모델 전환 (번호로도 가능)
- `search <query>` - 검색 실행
- `limit <number>` - 검색 결과 개수 설정
- `project <id>` - 프로젝트 필터 설정/해제
- `category <cat>` - 카테고리 필터 설정/해제
- `clear` - 필터 초기화
- `help` - 도움말 표시
- `quit` - 종료

**사용 예시:**
```
search(multilingual-e5-small, limit=5)> models
search(multilingual-e5-small, limit=5)> model 8
search(all-mpnet-base-v2, limit=5)> search 버그 수정
search(all-mpnet-base-v2, limit=5)> limit 10
search(all-mpnet-base-v2, limit=10)> category decision
search(all-mpnet-base-v2, limit=10) [category:decision]> search 아키텍처
```

### 5. 모델 전환

테스트 결과를 바탕으로 새로운 모델로 안전하게 전환합니다.

```bash
# 기본 전환 (백업 생성)
python scripts/switch_embedding_model.py intfloat/multilingual-e5-base

# 강제 재임베딩 (모든 메모리 다시 임베딩)
python scripts/switch_embedding_model.py new_model --force

# 백업 없이 전환 (주의!)
python scripts/switch_embedding_model.py new_model --no-backup

# 배치 크기 조정 (메모리 사용량 제어)
python scripts/switch_embedding_model.py new_model --batch-size 50

# 환경 파일도 함께 업데이트
python scripts/switch_embedding_model.py new_model --update-env
```

**전환 과정:**
1. 새 모델 유효성 검증
2. 현재 데이터베이스 백업
3. 모든 메모리 재임베딩
4. 메타데이터 업데이트
5. 결과 보고

## 모델 선택 가이드

### 사용 사례별 추천

#### 1. 빠른 응답이 중요한 경우
- **추천**: `all-MiniLM-L6-v2`, `paraphrase-MiniLM-L6-v2`
- **특징**: 빠른 임베딩 생성, 낮은 메모리 사용
- **적합**: 실시간 검색, 리소스 제한 환경

#### 2. 정확도가 최우선인 경우
- **추천**: `all-mpnet-base-v2`, `intfloat/multilingual-e5-large`
- **특징**: 높은 검색 정확도, 의미적 이해 우수
- **적합**: 정밀한 검색이 필요한 전문 분야

#### 3. 다국어 지원이 필요한 경우
- **추천**: `intfloat/multilingual-e5-base`, `distiluse-base-multilingual-cased-v2`
- **특징**: 다양한 언어 지원, 언어 간 검색 가능
- **적합**: 국제적 프로젝트, 다국어 문서

#### 4. 균형잡힌 성능이 필요한 경우
- **추천**: `all-MiniLM-L12-v2`, `intfloat/multilingual-e5-base`
- **특징**: 적당한 속도와 정확도
- **적합**: 일반적인 사용 사례

### 성능 비교 기준

| 모델 | 차원 | 속도 | 정확도 | 메모리 | 다국어 |
|------|------|------|--------|--------|--------|
| all-MiniLM-L6-v2 | 384 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| all-mpnet-base-v2 | 768 | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ |
| multilingual-e5-base | 768 | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| multilingual-e5-large | 1024 | ⭐ | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ |

## 테스트 모범 사례

### 1. 테스트 데이터 준비
- **충분한 데이터**: 최소 100개 이상의 메모리
- **다양한 카테고리**: 모든 카테고리가 포함되도록
- **실제 사용 패턴**: 실제 검색 쿼리와 유사한 테스트 쿼리

### 2. 평가 방법
- **정량적 평가**: 벤치마크와 품질 평가 도구 사용
- **정성적 평가**: A/B 테스트로 실제 사용자 경험 확인
- **성능 평가**: 응답 시간과 리소스 사용량 측정

### 3. 단계적 전환
1. **테스트 환경**에서 먼저 평가
2. **백업 생성** 후 전환
3. **점진적 배포**: 일부 쿼리부터 적용
4. **모니터링**: 전환 후 성능 지속 관찰

### 4. 성능 모니터링
- **검색 응답 시간** 추적
- **검색 결과 품질** 정기 평가
- **사용자 피드백** 수집
- **시스템 리소스** 모니터링

## 문제 해결

### 일반적인 문제

#### 1. 모델 로딩 실패
```bash
# 모델 캐시 확인
ls ~/.cache/huggingface/transformers/

# 수동 다운로드
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('model_name')"
```

#### 2. 메모리 부족
- 더 작은 배치 크기 사용: `--batch-size 50`
- 더 작은 모델 선택: `all-MiniLM-L6-v2`
- 시스템 메모리 확인 및 정리

#### 3. 검색 품질 저하
- 더 큰 모델 시도: `all-mpnet-base-v2`
- 다국어 모델 사용: `multilingual-e5-base`
- 테스트 데이터 품질 확인

#### 4. 전환 실패 시 복구
```bash
# 백업으로 복구
python scripts/switch_embedding_model.py --rollback backup_file.db

# 또는 수동 복구
cp backup_file.db data/memories.db
```

## 고급 사용법

### 1. 커스텀 평가 메트릭
```python
# evaluate_search_quality.py 수정
def custom_relevance_function(query, memory):
    # 사용자 정의 관련성 계산
    pass
```

### 2. 하이브리드 검색
- 키워드 검색과 벡터 검색 결합
- 가중치 조정으로 최적화
- 카테고리별 다른 모델 사용

### 3. 동적 모델 선택
- 쿼리 유형에 따른 모델 자동 선택
- 성능 기반 적응적 모델 전환
- 사용자 선호도 학습

## 결론

임베딩 모델 선택은 검색 품질에 큰 영향을 미칩니다. 제공된 도구들을 활용하여:

1. **체계적 평가**: 정량적, 정성적 평가 병행
2. **점진적 개선**: 작은 변화부터 시작
3. **지속적 모니터링**: 성능 변화 추적
4. **사용자 중심**: 실제 사용 패턴 반영

이를 통해 mem-mesh의 검색 품질을 지속적으로 향상시킬 수 있습니다.