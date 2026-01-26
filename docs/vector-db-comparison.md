# 벡터 DB 비교 가이드

SQLite-vec vs PostgreSQL (pgvector) vs Qdrant 성능 및 품질 비교

## 개요

mem-mesh의 벡터 검색 백엔드를 평가하기 위한 체계적인 비교 프레임워크입니다.

## 비교 대상

| DB | 장점 | 단점 | 사용 사례 |
|----|------|------|----------|
| **SQLite-vec** | 단순, 의존성 없음, 빠른 시작 | 확장성 제한, 고급 기능 부족 | 소규모, 프로토타입 |
| **PostgreSQL + pgvector** | 성숙한 생태계, ACID, 복잡한 쿼리 | 설정 복잡, 리소스 많이 사용 | 중대규모, 엔터프라이즈 |
| **Qdrant** | 벡터 검색 특화, 빠름, 확장성 | 별도 서비스 필요, 학습 곡선 | 대규모, 고성능 요구 |

## 설치 및 설정

### 1. PostgreSQL + pgvector

```bash
# Docker로 PostgreSQL 실행
docker run -d \
  --name postgres-pgvector \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=memesh \
  -p 5432:5432 \
  ankane/pgvector

# Python 패키지 설치
pip install asyncpg
```

### 2. Qdrant

```bash
# Docker로 Qdrant 실행
docker run -d \
  --name qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  qdrant/qdrant

# Python 패키지 설치
pip install qdrant-client
```

## 사용 방법

### Step 1: 데이터 마이그레이션

```bash
# PostgreSQL로 마이그레이션
python scripts/migrate_to_postgres.py \
  --pg-url "postgresql://postgres:password@localhost:5432/memesh"

# Qdrant로 마이그레이션
python scripts/migrate_to_qdrant.py \
  --qdrant-url "http://localhost:6333" \
  --test-search
```

### Step 2: 벤치마크 실행

```bash
# SQLite만 테스트
python scripts/benchmark_vector_dbs.py --dbs sqlite

# 모든 DB 테스트
python scripts/benchmark_vector_dbs.py --dbs all --output results.json
```

### Step 3: 결과 분석

```bash
# 결과 파일 확인
cat results.json | python -m json.tool
```

## 평가 지표

### 1. 검색 품질

- **Precision@5**: 상위 5개 결과 중 관련 문서 비율
- **Recall@5**: 전체 관련 문서 중 상위 5개에 포함된 비율
- **MRR (Mean Reciprocal Rank)**: 첫 번째 관련 문서의 순위 역수

### 2. 성능

- **쿼리 속도**: 검색 쿼리 실행 시간 (ms)
- **인덱싱 속도**: 데이터 삽입 시간
- **메모리 사용량**: 런타임 메모리 사용량

### 3. 운영

- **디스크 사용량**: 데이터베이스 파일 크기
- **설정 복잡도**: 초기 설정 난이도
- **유지보수**: 백업, 복구, 모니터링

## 벤치마크 쿼리 세트

기본 제공되는 쿼리:

1. "MCP 설정 방법" - 설정 관련
2. "데이터베이스 마이그레이션" - 기술 문서
3. "검색 품질 개선" - 알고리즘 관련
4. "서버 실행 모드" - 운영 관련
5. "벡터 임베딩 모델" - 모델 관련

### 커스텀 쿼리 추가

`scripts/benchmark_vector_dbs.py`의 `get_benchmark_queries()` 메서드를 수정:

```python
def get_benchmark_queries(self) -> List[BenchmarkQuery]:
    return [
        BenchmarkQuery(
            id="custom1",
            query="내 쿼리",
            expected_results=["memory-id-1", "memory-id-2"],
            description="설명"
        ),
        # ...
    ]
```

## 예상 결과

### 소규모 데이터셋 (< 1,000개)

- **SQLite-vec**: 가장 빠름, 설정 간단
- **PostgreSQL**: 중간 성능, 복잡한 쿼리 가능
- **Qdrant**: 오버헤드로 인해 느릴 수 있음

### 중대규모 데이터셋 (1,000 - 100,000개)

- **SQLite-vec**: 성능 저하 시작
- **PostgreSQL**: 안정적인 성능
- **Qdrant**: 성능 우위 시작

### 대규모 데이터셋 (> 100,000개)

- **SQLite-vec**: 권장하지 않음
- **PostgreSQL**: 인덱스 튜닝 필요
- **Qdrant**: 최고 성능

## 의사결정 가이드

### SQLite-vec 유지 (현재)

**선택 조건:**
- 데이터셋 < 10,000개
- 단일 서버 배포
- 설정 단순성 중요
- 의존성 최소화

### PostgreSQL 전환

**선택 조건:**
- 기존 PostgreSQL 인프라 존재
- 복잡한 관계형 쿼리 필요
- ACID 트랜잭션 중요
- 엔터프라이즈 지원 필요

### Qdrant 전환

**선택 조건:**
- 데이터셋 > 100,000개
- 검색 성능이 최우선
- 수평 확장 필요
- 벡터 검색 전용 기능 활용

## 마이그레이션 전략

### 점진적 전환 (권장)

1. **Phase 1**: 병렬 운영
   - SQLite-vec 유지
   - 새 DB에 데이터 복제
   - 읽기 트래픽 일부 전환

2. **Phase 2**: 검증
   - 검색 품질 비교
   - 성능 모니터링
   - 버그 수정

3. **Phase 3**: 완전 전환
   - 모든 트래픽 전환
   - SQLite-vec 백업 유지
   - 롤백 계획 준비

### 롤백 계획

```bash
# PostgreSQL → SQLite 역마이그레이션
python scripts/migrate_from_postgres.py

# Qdrant → SQLite 역마이그레이션
python scripts/migrate_from_qdrant.py
```

## 트러블슈팅

### PostgreSQL 연결 실패

```bash
# 연결 테스트
psql -h localhost -U postgres -d memesh

# 로그 확인
docker logs postgres-pgvector
```

### Qdrant 연결 실패

```bash
# 상태 확인
curl http://localhost:6333/health

# 로그 확인
docker logs qdrant
```

### 임베딩 차원 불일치

현재 설정: 384차원 (paraphrase-multilingual-MiniLM-L12-v2)

다른 모델 사용 시 마이그레이션 스크립트의 `size` 파라미터 수정 필요.

## 참고 자료

- [SQLite-vec 문서](https://github.com/asg017/sqlite-vec)
- [pgvector 문서](https://github.com/pgvector/pgvector)
- [Qdrant 문서](https://qdrant.tech/documentation/)
- [벡터 검색 비교 논문](https://arxiv.org/abs/2101.08281)
