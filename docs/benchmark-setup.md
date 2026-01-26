# 벡터 DB 벤치마크 환경 설정

PostgreSQL (pgvector)와 Qdrant를 Docker Compose로 실행하는 가이드

## 빠른 시작

### 0. 필수 패키지 설치

벤치마크를 실행하기 전에 필요한 Python 패키지를 설치하세요:

```bash
# 벤치마크용 패키지 설치
pip install asyncpg qdrant-client

# 또는 requirements.txt에서 주석 해제 후 설치
# requirements.txt에서 다음 줄의 주석(#)을 제거:
# asyncpg>=0.29.0
# qdrant-client>=1.7.0
pip install -r requirements.txt
```

### 1. 벤치마크 환경 실행

```bash
# PostgreSQL + Qdrant 실행
docker-compose -f docker-compose.benchmark.yml up -d

# 상태 확인
docker-compose -f docker-compose.benchmark.yml ps

# 로그 확인
docker-compose -f docker-compose.benchmark.yml logs -f
```

### 2. 헬스체크

```bash
# PostgreSQL 연결 테스트
docker exec mem-mesh-postgres pg_isready -U memesh

# Qdrant 상태 확인
curl http://localhost:6333/health

# PostgreSQL 버전 및 pgvector 확인
docker exec mem-mesh-postgres psql -U memesh -d memesh -c "SELECT version(); SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

### 3. 데이터 마이그레이션

**주의:** 마이그레이션 전에 필수 패키지가 설치되어 있어야 합니다 (위의 0단계 참조).

```bash
# PostgreSQL로 마이그레이션
python scripts/migrate_to_postgres.py \
  --pg-url "postgresql://memesh:memesh_password@localhost:5432/memesh"

# Qdrant로 마이그레이션
python scripts/migrate_to_qdrant.py \
  --qdrant-url "http://localhost:6333" \
  --test-search
```

**Makefile 사용 (권장):**

```bash
# 패키지 설치 확인 포함
make benchmark-migrate-postgres
make benchmark-migrate-qdrant
```

### 4. 벤치마크 실행

**주의:** 현재 PostgreSQL과 Qdrant 벤치마크는 구현 중입니다. SQLite-vec 벤치마크만 사용 가능합니다.

```bash
# SQLite-vec 벤치마크 (현재 사용 가능)
python scripts/benchmark_vector_dbs.py \
  --dbs sqlite \
  --output benchmark_results.json

# 결과 확인
cat benchmark_results.json | python -m json.tool
```

**Makefile 사용:**

```bash
make benchmark-run
```

**전체 파이프라인 (환경 시작 → 마이그레이션 → 벤치마크):**

```bash
make benchmark-full
```

## 서비스 정보

### PostgreSQL + pgvector

- **포트:** 5432
- **사용자:** memesh
- **비밀번호:** memesh_password
- **데이터베이스:** memesh
- **연결 문자열:** `postgresql://memesh:memesh_password@localhost:5432/memesh`

**직접 접속:**
```bash
# psql 클라이언트
docker exec -it mem-mesh-postgres psql -U memesh -d memesh

# 테이블 확인
\dt

# 벡터 검색 테스트
SELECT id, content, embedding <=> '[0.1, 0.2, ...]'::vector as distance
FROM memories
ORDER BY distance
LIMIT 5;
```

### Qdrant

- **HTTP API:** http://localhost:6333
- **gRPC API:** localhost:6334
- **대시보드:** http://localhost:6333/dashboard

**API 테스트:**
```bash
# 컬렉션 목록
curl http://localhost:6333/collections

# 컬렉션 정보
curl http://localhost:6333/collections/mem-mesh

# 검색 테스트
curl -X POST http://localhost:6333/collections/mem-mesh/points/search \
  -H "Content-Type: application/json" \
  -d '{
    "vector": [0.1, 0.2, ...],
    "limit": 5
  }'
```

### pgAdmin (선택사항)

pgAdmin을 사용하려면 `--profile tools` 옵션으로 실행:

```bash
docker-compose -f docker-compose.benchmark.yml --profile tools up -d
```

- **URL:** http://localhost:5050
- **이메일:** admin@memesh.local
- **비밀번호:** admin

**서버 추가:**
1. 좌측 "Servers" 우클릭 → "Register" → "Server"
2. General 탭: Name = "mem-mesh-postgres"
3. Connection 탭:
   - Host: postgres-pgvector
   - Port: 5432
   - Database: memesh
   - Username: memesh
   - Password: memesh_password

## 성능 튜닝

### PostgreSQL

**인덱스 생성 (데이터 1000개 이상 권장):**

```sql
-- IVFFlat 인덱스 (빠른 근사 검색)
CREATE INDEX idx_memories_embedding 
ON memories USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- HNSW 인덱스 (더 빠르지만 메모리 많이 사용)
CREATE INDEX idx_memories_embedding_hnsw
ON memories USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

**쿼리 최적화:**

```sql
-- 검색 정확도 조정 (IVFFlat)
SET ivfflat.probes = 10;  -- 기본값: 1, 높을수록 정확하지만 느림

-- 검색 정확도 조정 (HNSW)
SET hnsw.ef_search = 40;  -- 기본값: 40, 높을수록 정확하지만 느림
```

### Qdrant

**컬렉션 최적화:**

```python
from qdrant_client import QdrantClient
from qdrant_client.models import OptimizersConfigDiff

client = QdrantClient(url="http://localhost:6333")

# 인덱싱 임계값 조정
client.update_collection(
    collection_name="mem-mesh",
    optimizer_config=OptimizersConfigDiff(
        indexing_threshold=10000  # 기본값: 20000
    )
)
```

## 데이터 관리

### 백업

```bash
# PostgreSQL 백업
docker exec mem-mesh-postgres pg_dump -U memesh memesh > backup.sql

# Qdrant 백업 (스냅샷)
curl -X POST http://localhost:6333/collections/mem-mesh/snapshots
```

### 복원

```bash
# PostgreSQL 복원
docker exec -i mem-mesh-postgres psql -U memesh memesh < backup.sql

# Qdrant 복원
curl -X PUT http://localhost:6333/collections/mem-mesh/snapshots/upload \
  --data-binary @snapshot.tar
```

### 데이터 삭제

```bash
# PostgreSQL 데이터 삭제
docker exec mem-mesh-postgres psql -U memesh -d memesh -c "TRUNCATE TABLE memories CASCADE;"

# Qdrant 컬렉션 삭제
curl -X DELETE http://localhost:6333/collections/mem-mesh
```

## 종료 및 정리

```bash
# 서비스 중지
docker-compose -f docker-compose.benchmark.yml down

# 데이터 포함 완전 삭제
docker-compose -f docker-compose.benchmark.yml down -v

# 특정 서비스만 중지
docker-compose -f docker-compose.benchmark.yml stop postgres-pgvector
docker-compose -f docker-compose.benchmark.yml stop qdrant
```

## 트러블슈팅

### PostgreSQL 연결 실패

```bash
# 로그 확인
docker logs mem-mesh-postgres

# 컨테이너 재시작
docker-compose -f docker-compose.benchmark.yml restart postgres-pgvector

# 포트 충돌 확인
lsof -i :5432
```

### Qdrant 연결 실패

```bash
# 로그 확인
docker logs mem-mesh-qdrant

# 컨테이너 재시작
docker-compose -f docker-compose.benchmark.yml restart qdrant

# 포트 충돌 확인
lsof -i :6333
```

### 디스크 공간 부족

```bash
# Docker 볼륨 확인
docker volume ls

# 사용하지 않는 볼륨 정리
docker volume prune

# 특정 볼륨 삭제
docker volume rm mem-mesh_postgres_data
docker volume rm mem-mesh_qdrant_data
```

### 메모리 부족

Docker Desktop 설정에서 메모리 할당 증가:
- 권장: 최소 4GB, 이상적으로 8GB

## 모니터링

### PostgreSQL 통계

```sql
-- 테이블 크기
SELECT 
    pg_size_pretty(pg_total_relation_size('memories')) as total_size,
    pg_size_pretty(pg_relation_size('memories')) as table_size,
    pg_size_pretty(pg_indexes_size('memories')) as indexes_size;

-- 인덱스 사용 통계
SELECT 
    schemaname, tablename, indexname, 
    idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
WHERE tablename = 'memories';

-- 쿼리 성능
SELECT 
    query, calls, total_exec_time, mean_exec_time
FROM pg_stat_statements
WHERE query LIKE '%memories%'
ORDER BY mean_exec_time DESC
LIMIT 10;
```

### Qdrant 통계

```bash
# 컬렉션 정보
curl http://localhost:6333/collections/mem-mesh

# 클러스터 상태
curl http://localhost:6333/cluster

# 메트릭
curl http://localhost:6333/metrics
```

## 참고 자료

- [pgvector GitHub](https://github.com/pgvector/pgvector)
- [pgvector 성능 가이드](https://github.com/pgvector/pgvector#performance)
- [Qdrant 문서](https://qdrant.tech/documentation/)
- [Qdrant 최적화 가이드](https://qdrant.tech/documentation/guides/optimize/)
